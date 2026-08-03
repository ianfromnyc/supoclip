from src.config import Config


def test_processing_task_timeout_defaults_to_fifteen_minutes(monkeypatch):
    monkeypatch.delenv("PROCESSING_TASK_TIMEOUT_SECONDS", raising=False)

    assert Config().processing_task_timeout_seconds == 900


def test_processing_task_timeout_reads_env_var(monkeypatch):
    monkeypatch.setenv("PROCESSING_TASK_TIMEOUT_SECONDS", "120")

    assert Config().processing_task_timeout_seconds == 120


def test_task_heartbeat_interval_defaults_to_thirty_seconds(monkeypatch):
    monkeypatch.delenv("TASK_HEARTBEAT_INTERVAL_SECONDS", raising=False)

    assert Config().task_heartbeat_interval_seconds == 30


def test_task_heartbeat_interval_reads_env_var(monkeypatch):
    monkeypatch.setenv("TASK_HEARTBEAT_INTERVAL_SECONDS", "5")

    assert Config().task_heartbeat_interval_seconds == 5


def test_task_sweep_interval_defaults_to_sixty_seconds(monkeypatch):
    monkeypatch.delenv("TASK_SWEEP_INTERVAL_SECONDS", raising=False)

    assert Config().task_sweep_interval_seconds == 60


def test_task_sweep_interval_reads_env_var(monkeypatch):
    monkeypatch.setenv("TASK_SWEEP_INTERVAL_SECONDS", "10")

    assert Config().task_sweep_interval_seconds == 10


def test_task_sweep_can_be_disabled(monkeypatch):
    # 0 turns the background sweep off for deployments that run their own.
    monkeypatch.setenv("TASK_SWEEP_INTERVAL_SECONDS", "0")

    assert Config().task_sweep_interval_seconds == 0
