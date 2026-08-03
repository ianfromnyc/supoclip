"""The reaper against a real database, where its SQL has to hold up."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from src.config import Config
from src.services.task_reaper import (
    QUEUE_TIMEOUT_MESSAGE,
    WORKER_LOST_MESSAGE,
    TaskReaper,
)
from tests.fixtures.factories import create_source, create_user


class FakeRedis:
    """Holds the heartbeats of the workers that are still alive."""

    def __init__(self, live_heartbeats=()):
        self.live_heartbeats = set(live_heartbeats)
        self.published = []

    async def exists(self, key):
        return 1 if key in self.live_heartbeats else 0

    async def setex(self, key, ttl, value):
        return None

    async def publish(self, channel, payload):
        self.published.append(channel)


async def create_aged_task(session, *, user_id, source_id, status, age_seconds):
    """Insert a task that was last updated `age_seconds` ago.

    The row is inserted rather than updated because the `updated_at` trigger
    overwrites the column on every UPDATE.
    """
    task_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO tasks (
                id, user_id, source_id, generated_clips_ids, status,
                font_family, font_size, font_color, created_at, updated_at
            ) VALUES (
                :id, :user_id, :source_id, ARRAY[]::VARCHAR(36)[], :status,
                'TikTokSans-Regular', 24, '#FFFFFF',
                NOW() - (:age_seconds * INTERVAL '1 second'),
                NOW() - (:age_seconds * INTERVAL '1 second')
            )
            """
        ),
        {
            "id": task_id,
            "user_id": user_id,
            "source_id": source_id,
            "status": status,
            "age_seconds": age_seconds,
        },
    )
    await session.commit()
    return task_id


async def read_task(session, task_id):
    result = await session.execute(
        text("SELECT status, progress_message FROM tasks WHERE id = :id"),
        {"id": task_id},
    )
    row = result.fetchone()
    # Close the transaction the read opened: the shared session is torn down
    # on another event loop, where a late rollback cannot reach the database.
    await session.commit()
    return {"status": row.status, "progress_message": row.progress_message}


def build_reaper(db_session, redis=None) -> TaskReaper:
    config = Config()
    config.queued_task_timeout_seconds = 180
    config.processing_task_timeout_seconds = 900
    return TaskReaper(db_session, redis or FakeRedis(), config)


async def seed_owner(session):
    """A user and source to hang test tasks off."""
    user = await create_user(session, user_id=str(uuid4()))
    source = await create_source(session, title="Reaper source")
    return {"user_id": user["id"], "source_id": source["id"]}


@pytest.mark.asyncio
async def test_sweep_fails_a_task_nobody_ever_picked_up(db_session):
    owner = await seed_owner(db_session)
    task_id = await create_aged_task(
        db_session, **owner, status="queued", age_seconds=600
    )

    reaped = await build_reaper(db_session).sweep()

    assert task_id in reaped
    task = await read_task(db_session, task_id)
    assert task["status"] == "error"
    assert task["progress_message"] == QUEUE_TIMEOUT_MESSAGE


@pytest.mark.asyncio
async def test_sweep_fails_a_task_whose_worker_died(db_session):
    owner = await seed_owner(db_session)
    task_id = await create_aged_task(
        db_session, **owner, status="processing", age_seconds=3600
    )

    reaped = await build_reaper(db_session).sweep()

    assert task_id in reaped
    task = await read_task(db_session, task_id)
    assert task["status"] == "error"
    assert task["progress_message"] == WORKER_LOST_MESSAGE


@pytest.mark.asyncio
async def test_sweep_leaves_a_long_render_alone(db_session):
    # A three-hour render writes progress rarely; its heartbeat is what says
    # it is alive.
    owner = await seed_owner(db_session)
    task_id = await create_aged_task(
        db_session, **owner, status="processing", age_seconds=10_000
    )
    redis = FakeRedis(live_heartbeats={f"task_heartbeat:{task_id}"})

    reaped = await build_reaper(db_session, redis).sweep()

    assert task_id not in reaped
    assert (await read_task(db_session, task_id))["status"] == "processing"


@pytest.mark.asyncio
async def test_sweep_leaves_a_finished_task_alone(db_session):
    owner = await seed_owner(db_session)
    task_id = await create_aged_task(
        db_session, **owner, status="completed", age_seconds=10_000
    )

    reaped = await build_reaper(db_session).sweep()

    assert task_id not in reaped
    assert (await read_task(db_session, task_id))["status"] == "completed"
