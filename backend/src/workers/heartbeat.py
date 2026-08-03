"""
Task heartbeat - proof that a worker is still holding a task.

A worker refreshes a short-lived Redis key while it processes a task. If the
worker dies, the key expires and the task reaper can tell that nothing is
working on the task any more.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

TASK_HEARTBEAT_KEY_PREFIX = "task_heartbeat:"

# The key survives a few missed refreshes, so a busy event loop does not
# make a healthy worker look dead.
HEARTBEAT_TTL_INTERVALS = 3


def heartbeat_key(task_id: str) -> str:
    """Redis key that exists while a worker owns this task."""
    return f"{TASK_HEARTBEAT_KEY_PREFIX}{task_id}"


class TaskHeartbeat:
    """Async context manager that keeps a task's heartbeat key alive."""

    def __init__(self, redis, task_id: str, interval_seconds: float = 30):
        self.redis = redis
        self.task_id = task_id
        self.interval_seconds = interval_seconds
        self.ttl_seconds = max(1, int(interval_seconds * HEARTBEAT_TTL_INTERVALS))
        self.key = heartbeat_key(task_id)
        self._beat_loop: asyncio.Task | None = None

    async def beat(self) -> None:
        """Write the key. A dead Redis must not fail the task it tracks."""
        try:
            await self.redis.setex(self.key, self.ttl_seconds, "1")
        except Exception:
            logger.warning(
                "Could not write heartbeat for task %s", self.task_id, exc_info=True
            )

    async def _beat_forever(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            await self.beat()

    async def __aenter__(self) -> "TaskHeartbeat":
        # Beat once up front: a task that dies seconds after it starts must
        # still look alive until the timeout, not from the first refresh on.
        await self.beat()
        self._beat_loop = asyncio.create_task(self._beat_forever())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._beat_loop is not None:
            self._beat_loop.cancel()
            try:
                await self._beat_loop
            except asyncio.CancelledError:
                pass
            self._beat_loop = None

        try:
            await self.redis.delete(self.key)
        except Exception:
            logger.warning(
                "Could not clear heartbeat for task %s", self.task_id, exc_info=True
            )
