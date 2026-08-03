from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.repositories.task_repository import TaskRepository


class FakeResult:
    def __init__(self, rows=(), rowcount=0):
        self._rows = list(rows)
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows


def build_db(result: FakeResult) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_get_active_tasks_returns_age_measured_by_the_database():
    # The age comes from the database clock, so an application server whose
    # clock drifts cannot fail a healthy task.
    db = build_db(
        FakeResult(
            rows=[SimpleNamespace(id="task-1", status="processing", age_seconds=42.5)]
        )
    )

    tasks = await TaskRepository.get_active_tasks(db)

    assert tasks == [{"id": "task-1", "status": "processing", "age_seconds": 42.5}]
    query = str(db.execute.await_args.args[0])
    assert "NOW()" in query


@pytest.mark.asyncio
async def test_get_active_tasks_reads_only_active_tasks():
    db = build_db(FakeResult(rows=[]))

    await TaskRepository.get_active_tasks(db)

    query = str(db.execute.await_args.args[0])
    assert "'queued'" in query and "'processing'" in query
    assert "completed" not in query


@pytest.mark.asyncio
async def test_fail_task_if_status_guards_the_status_it_expects():
    # Guarding on the expected status is what stops the sweep overwriting a
    # task that finished between the read and the write.
    db = build_db(FakeResult(rowcount=1))

    failed = await TaskRepository.fail_task_if_status(
        db, "task-1", expected_status="processing", message="Worker stopped"
    )

    assert failed is True
    params = db.execute.await_args.args[1]
    assert params["expected_status"] == "processing"
    assert params["message"] == "Worker stopped"
    query = str(db.execute.await_args.args[0])
    assert "status = :expected_status" in query
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_fail_task_if_status_reports_a_task_that_moved_on():
    db = build_db(FakeResult(rowcount=0))

    failed = await TaskRepository.fail_task_if_status(
        db, "task-1", expected_status="processing", message="Worker stopped"
    )

    assert failed is False
