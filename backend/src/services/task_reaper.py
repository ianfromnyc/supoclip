"""
Task reaper - rescues active tasks that nothing is working on any more.

A task is active while it is `queued` or `processing`. Either state can be
left behind: a task nobody picked up stays `queued`, and a task whose worker
died stays `processing`. The reaper moves both to `error`, which is a state
the user can resume from.

The sweep runs on a timer rather than when somebody reads the task, so a task
nobody is watching is rescued too.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Config, get_config
from ..repositories.task_repository import TaskRepository
from ..workers.heartbeat import heartbeat_key
from ..workers.progress import ProgressTracker

logger = logging.getLogger(__name__)

QUEUE_TIMEOUT_MESSAGE = (
    "Task timed out while waiting in queue. "
    "Ensure the worker service is running and healthy (docker logs supoclip-worker)."
)

WORKER_LOST_MESSAGE = (
    "The worker stopped while processing this task. "
    "Resume the task to try again, and check the worker service is healthy "
    "(docker logs supoclip-worker)."
)


class TaskReaper:
    """Fails active tasks that no worker is holding."""

    def __init__(
        self,
        db: AsyncSession,
        redis,
        config: Optional[Config] = None,
    ):
        self.db = db
        self.redis = redis
        self.task_repo = TaskRepository()
        self.config = config or get_config()

    async def sweep(self) -> List[str]:
        """Fail every abandoned task. Returns the IDs that were failed."""
        reaped: List[str] = []

        for task in await self.task_repo.get_active_tasks(self.db):
            try:
                message = await self._abandonment_reason(task)
                if message and await self._fail(task, message):
                    reaped.append(task["id"])
            except Exception:
                # One unrescuable task must not hide the rest of the queue.
                logger.exception("Could not sweep task %s", task.get("id"))

        if reaped:
            logger.warning("Reaper failed %d abandoned task(s): %s", len(reaped), reaped)

        return reaped

    async def _abandonment_reason(self, task: Dict[str, Any]) -> Optional[str]:
        """Why this task is abandoned, or None while it is still healthy."""
        age_seconds = task.get("age_seconds") or 0

        if task["status"] == "queued":
            if age_seconds >= self.config.queued_task_timeout_seconds:
                return QUEUE_TIMEOUT_MESSAGE
            return None

        if task["status"] == "processing":
            # The age is only a grace period. The heartbeat is the real
            # signal, because a long render can go a while without writing
            # progress to the database.
            if age_seconds < self.config.processing_task_timeout_seconds:
                return None
            if await self._has_heartbeat(task["id"]):
                return None
            return WORKER_LOST_MESSAGE

        return None

    async def _has_heartbeat(self, task_id: str) -> bool:
        """True while a worker still refreshes this task's heartbeat.

        An unreachable Redis reads as "alive": without heartbeats the reaper
        cannot tell a live task from a dead one, and failing a running task
        is worse than leaving a dead one for the next sweep.
        """
        try:
            return bool(await self.redis.exists(heartbeat_key(task_id)))
        except Exception:
            logger.warning(
                "Could not read the heartbeat of task %s; leaving it alone",
                task_id,
                exc_info=True,
            )
            return True

    async def _fail(self, task: Dict[str, Any], message: str) -> bool:
        """Move the task to error and tell whoever is watching it."""
        failed = await self.task_repo.fail_task_if_status(
            self.db,
            task["id"],
            expected_status=task["status"],
            message=message,
        )
        if not failed:
            return False

        try:
            await ProgressTracker(self.redis, task["id"]).error(message)
        except Exception:
            # The database is authoritative; a missed publish only means the
            # browser learns about the failure on its next read.
            logger.warning(
                "Could not publish the failure of task %s", task["id"], exc_info=True
            )

        return True


async def sweep_once(config: Optional[Config] = None) -> List[str]:
    """Run one sweep with its own database session and Redis connection."""
    from ..database import AsyncSessionLocal

    runtime_config = config or get_config()
    redis_client = redis.Redis(
        host=runtime_config.redis_host,
        port=runtime_config.redis_port,
        password=runtime_config.redis_password,
        decode_responses=True,
    )
    try:
        async with AsyncSessionLocal() as db:
            return await TaskReaper(db, redis_client, runtime_config).sweep()
    finally:
        await redis_client.close()


async def sweep_periodically(config: Optional[Config] = None) -> None:
    """Sweep on a timer for as long as the API runs."""
    runtime_config = config or get_config()
    interval = runtime_config.task_sweep_interval_seconds

    while True:
        await asyncio.sleep(interval)
        try:
            await sweep_once(runtime_config)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failing sweep must be retried, not abandoned: it is the only
            # rescue path a stuck task has.
            logger.exception("Task sweep failed; retrying on the next interval")


def start_task_sweeper(config: Optional[Config] = None) -> Optional[asyncio.Task]:
    """Start the background sweep. Returns None when it is turned off."""
    runtime_config = config or get_config()
    if runtime_config.task_sweep_interval_seconds <= 0:
        logger.info("Task sweep is disabled (TASK_SWEEP_INTERVAL_SECONDS=0)")
        return None

    logger.info(
        "Task sweep every %ss", runtime_config.task_sweep_interval_seconds
    )
    return asyncio.create_task(sweep_periodically(runtime_config))
