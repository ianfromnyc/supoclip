import asyncio
from unittest.mock import AsyncMock

import pytest

from src.config import Config
from src.services import task_reaper as task_reaper_module
from src.services.task_reaper import start_task_sweeper, sweep_periodically


def build_config(interval_seconds) -> Config:
    config = Config()
    config.task_sweep_interval_seconds = interval_seconds
    return config


async def wait_for(condition, timeout: float = 1.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.005)
    return False


@pytest.mark.asyncio
async def test_the_sweep_repeats_on_its_interval(monkeypatch):
    sweeps = []
    monkeypatch.setattr(
        task_reaper_module,
        "sweep_once",
        AsyncMock(side_effect=lambda config: sweeps.append(1) or []),
    )

    loop_task = asyncio.create_task(sweep_periodically(build_config(0.01)))
    try:
        assert await wait_for(lambda: len(sweeps) >= 3)
    finally:
        loop_task.cancel()


@pytest.mark.asyncio
async def test_a_failed_sweep_does_not_end_the_loop(monkeypatch):
    # A database blip must not silently retire the only rescue path.
    calls = []

    async def flaky_sweep(config):
        calls.append(1)
        raise RuntimeError("database gone")

    monkeypatch.setattr(task_reaper_module, "sweep_once", flaky_sweep)

    loop_task = asyncio.create_task(sweep_periodically(build_config(0.01)))
    try:
        assert await wait_for(lambda: len(calls) >= 3)
    finally:
        loop_task.cancel()


@pytest.mark.asyncio
async def test_the_sweeper_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(task_reaper_module, "sweep_once", AsyncMock(return_value=[]))

    assert start_task_sweeper(build_config(0)) is None


@pytest.mark.asyncio
async def test_the_sweeper_runs_in_the_background_when_enabled(monkeypatch):
    sweeps = []
    monkeypatch.setattr(
        task_reaper_module,
        "sweep_once",
        AsyncMock(side_effect=lambda config: sweeps.append(1) or []),
    )

    sweeper = start_task_sweeper(build_config(0.01))
    try:
        assert sweeper is not None
        assert await wait_for(lambda: len(sweeps) >= 1)
    finally:
        sweeper.cancel()
