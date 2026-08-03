import json
from unittest.mock import AsyncMock

import pytest

from src.config import Config
from src.services.task_reaper import (
    QUEUE_TIMEOUT_MESSAGE,
    WORKER_LOST_MESSAGE,
    TaskReaper,
)


class FakeRedis:
    """Redis holding the heartbeats of the workers that are still alive."""

    def __init__(self, live_heartbeats=(), fail_on_exists=False):
        self.live_heartbeats = set(live_heartbeats)
        self.fail_on_exists = fail_on_exists
        self.published: list[tuple[str, dict]] = []
        self.keys: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        if self.fail_on_exists:
            raise ConnectionError("redis is down")
        return 1 if key in self.live_heartbeats else 0

    async def setex(self, key: str, ttl: int, value: str):
        self.keys[key] = value

    async def publish(self, channel: str, payload: str):
        self.published.append((channel, json.loads(payload)))


def build_reaper(active_tasks, redis=None, failed=True) -> TaskReaper:
    config = Config()
    config.queued_task_timeout_seconds = 180
    config.processing_task_timeout_seconds = 900

    reaper = TaskReaper(db=AsyncMock(), redis=redis or FakeRedis(), config=config)
    reaper.task_repo.get_active_tasks = AsyncMock(return_value=active_tasks)
    reaper.task_repo.fail_task_if_status = AsyncMock(return_value=failed)
    return reaper


@pytest.mark.asyncio
async def test_a_queued_task_past_the_queue_timeout_is_failed():
    reaper = build_reaper(
        [{"id": "task-1", "status": "queued", "age_seconds": 181.0}]
    )

    assert await reaper.sweep() == ["task-1"]
    reaper.task_repo.fail_task_if_status.assert_awaited_once_with(
        reaper.db,
        "task-1",
        expected_status="queued",
        message=QUEUE_TIMEOUT_MESSAGE,
    )


@pytest.mark.asyncio
async def test_a_queued_task_inside_the_queue_timeout_is_left_alone():
    reaper = build_reaper(
        [{"id": "task-1", "status": "queued", "age_seconds": 30.0}]
    )

    assert await reaper.sweep() == []
    reaper.task_repo.fail_task_if_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_processing_task_without_a_heartbeat_is_failed():
    reaper = build_reaper(
        [{"id": "task-1", "status": "processing", "age_seconds": 901.0}]
    )

    assert await reaper.sweep() == ["task-1"]
    reaper.task_repo.fail_task_if_status.assert_awaited_once_with(
        reaper.db,
        "task-1",
        expected_status="processing",
        message=WORKER_LOST_MESSAGE,
    )


@pytest.mark.asyncio
async def test_a_processing_task_with_a_live_heartbeat_is_never_failed():
    # A long render updates the database rarely, so only the heartbeat can
    # tell a slow task apart from an abandoned one.
    redis = FakeRedis(live_heartbeats={"task_heartbeat:task-1"})
    reaper = build_reaper(
        [{"id": "task-1", "status": "processing", "age_seconds": 100_000.0}],
        redis=redis,
    )

    assert await reaper.sweep() == []
    reaper.task_repo.fail_task_if_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_processing_task_inside_the_grace_period_is_left_alone():
    # The heartbeat is written just after the worker picks the task up; the
    # grace period covers that gap.
    reaper = build_reaper(
        [{"id": "task-1", "status": "processing", "age_seconds": 5.0}]
    )

    assert await reaper.sweep() == []
    reaper.task_repo.fail_task_if_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unreachable_redis_fails_nothing():
    # Without heartbeats the sweep cannot tell live tasks from dead ones,
    # so it must do nothing rather than fail every running task.
    reaper = build_reaper(
        [{"id": "task-1", "status": "processing", "age_seconds": 901.0}],
        redis=FakeRedis(fail_on_exists=True),
    )

    assert await reaper.sweep() == []
    reaper.task_repo.fail_task_if_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_task_is_announced_so_open_progress_streams_close():
    redis = FakeRedis()
    reaper = build_reaper(
        [{"id": "task-1", "status": "queued", "age_seconds": 181.0}], redis=redis
    )

    await reaper.sweep()

    assert redis.published == [
        (
            "progress:task-1",
            {
                "task_id": "task-1",
                "progress": 0,
                "message": QUEUE_TIMEOUT_MESSAGE,
                "status": "error",
            },
        )
    ]


@pytest.mark.asyncio
async def test_a_task_that_moved_on_is_neither_announced_nor_reported():
    redis = FakeRedis()
    reaper = build_reaper(
        [{"id": "task-1", "status": "queued", "age_seconds": 181.0}],
        redis=redis,
        failed=False,
    )

    assert await reaper.sweep() == []
    assert redis.published == []


@pytest.mark.asyncio
async def test_one_broken_task_does_not_stop_the_rest_of_the_sweep():
    reaper = build_reaper(
        [
            {"id": "task-1", "status": "queued", "age_seconds": 181.0},
            {"id": "task-2", "status": "queued", "age_seconds": 181.0},
        ]
    )
    reaper.task_repo.fail_task_if_status = AsyncMock(
        side_effect=[RuntimeError("database gone"), True]
    )

    assert await reaper.sweep() == ["task-2"]
