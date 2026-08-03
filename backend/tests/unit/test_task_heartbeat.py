import asyncio

import pytest

from src.workers.heartbeat import TaskHeartbeat, heartbeat_key


class FakeRedis:
    """Records the heartbeat writes a worker makes."""

    def __init__(self):
        self.keys: dict[str, tuple[int, str]] = {}
        self.setex_calls: list[tuple[str, int, str]] = []
        self.deleted: list[str] = []

    async def setex(self, key: str, ttl: int, value: str):
        self.keys[key] = (ttl, value)
        self.setex_calls.append((key, ttl, value))

    async def delete(self, key: str):
        self.keys.pop(key, None)
        self.deleted.append(key)


async def wait_for(condition, timeout: float = 1.0):
    """Poll until condition() is true, so timing tests do not sleep blindly."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.005)
    return False


def test_heartbeat_key_is_namespaced_per_task():
    assert heartbeat_key("task-1") == "task_heartbeat:task-1"


@pytest.mark.asyncio
async def test_heartbeat_key_expires_after_three_intervals():
    redis = FakeRedis()

    async with TaskHeartbeat(redis, "task-1", interval_seconds=30):
        assert redis.keys["task_heartbeat:task-1"][0] == 90


@pytest.mark.asyncio
async def test_heartbeat_is_written_before_the_first_interval_elapses():
    redis = FakeRedis()

    async with TaskHeartbeat(redis, "task-1", interval_seconds=30):
        # A task that dies in its first seconds must still have been seen
        # as alive, so the key is written on entry rather than after a wait.
        assert "task_heartbeat:task-1" in redis.keys


@pytest.mark.asyncio
async def test_heartbeat_is_refreshed_while_the_task_runs():
    redis = FakeRedis()

    async with TaskHeartbeat(redis, "task-1", interval_seconds=0.01):
        refreshed = await wait_for(lambda: len(redis.setex_calls) >= 3)

    assert refreshed


@pytest.mark.asyncio
async def test_heartbeat_key_is_dropped_when_the_task_finishes():
    redis = FakeRedis()

    async with TaskHeartbeat(redis, "task-1", interval_seconds=30):
        pass

    assert redis.deleted == ["task_heartbeat:task-1"]
    assert "task_heartbeat:task-1" not in redis.keys


@pytest.mark.asyncio
async def test_heartbeat_key_is_dropped_when_the_task_raises():
    redis = FakeRedis()

    with pytest.raises(RuntimeError):
        async with TaskHeartbeat(redis, "task-1", interval_seconds=30):
            raise RuntimeError("render failed")

    assert redis.deleted == ["task_heartbeat:task-1"]


@pytest.mark.asyncio
async def test_a_failing_redis_never_breaks_the_task():
    class BrokenRedis(FakeRedis):
        async def setex(self, key, ttl, value):
            raise ConnectionError("redis is down")

        async def delete(self, key):
            raise ConnectionError("redis is down")

    async with TaskHeartbeat(BrokenRedis(), "task-1", interval_seconds=0.01):
        await asyncio.sleep(0.03)
