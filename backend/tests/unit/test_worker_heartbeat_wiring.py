from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from src import database as database_module
from src import runtime_settings as runtime_settings_module
from src.services import task_service as task_service_module
from src.workers.tasks import process_video_task


class FakeRedis:
    """Enough Redis for one worker run."""

    def __init__(self):
        self.keys: dict[str, str] = {}
        self.sets: dict[str, set] = {}
        self.published: list[tuple[str, str]] = []

    async def setex(self, key, ttl, value):
        self.keys[key] = value

    async def set(self, key, value):
        self.keys[key] = value

    async def get(self, key):
        return self.keys.get(key)

    async def delete(self, key):
        self.keys.pop(key, None)

    async def exists(self, key):
        return 1 if key in self.keys else 0

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    async def publish(self, channel, payload):
        self.published.append((channel, payload))


@pytest.fixture()
def worker_environment(monkeypatch):
    """Stub the database and settings the worker loads on every run."""

    @asynccontextmanager
    async def fake_session():
        yield AsyncMock()

    monkeypatch.setattr(database_module, "AsyncSessionLocal", fake_session)
    monkeypatch.setattr(
        runtime_settings_module, "load_runtime_settings_cache", AsyncMock()
    )


def install_task_service(monkeypatch, process_task):
    class FakeTaskService:
        def __init__(self, db):
            self.db = db

        async def process_task(self, **kwargs):
            return await process_task(**kwargs)

    monkeypatch.setattr(task_service_module, "TaskService", FakeTaskService)


async def run_worker(redis: FakeRedis):
    return await process_video_task(
        {"redis": redis, "job_try": 1},
        "task-1",
        "https://www.youtube.com/watch?v=demo",
        "youtube",
        "user-1",
    )


@pytest.mark.asyncio
async def test_a_task_being_processed_has_a_live_heartbeat(
    monkeypatch, worker_environment
):
    redis = FakeRedis()
    seen = {}

    async def process_task(**kwargs):
        seen["heartbeat"] = await redis.exists("task_heartbeat:task-1")
        return {"task_id": "task-1", "clips_count": 1}

    install_task_service(monkeypatch, process_task)

    await run_worker(redis)

    assert seen["heartbeat"] == 1


@pytest.mark.asyncio
async def test_the_heartbeat_stops_when_the_task_finishes(
    monkeypatch, worker_environment
):
    redis = FakeRedis()
    install_task_service(
        monkeypatch, AsyncMock(return_value={"task_id": "task-1", "clips_count": 1})
    )

    await run_worker(redis)

    assert await redis.exists("task_heartbeat:task-1") == 0


@pytest.mark.asyncio
async def test_the_heartbeat_stops_when_the_task_fails(
    monkeypatch, worker_environment
):
    redis = FakeRedis()
    install_task_service(monkeypatch, AsyncMock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        await run_worker(redis)

    assert await redis.exists("task_heartbeat:task-1") == 0
