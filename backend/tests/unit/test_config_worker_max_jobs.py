from src.config import Config


def test_worker_max_jobs_defaults_to_four(monkeypatch):
    monkeypatch.delenv("WORKER_MAX_JOBS", raising=False)

    assert Config().worker_max_jobs == 4


def test_worker_max_jobs_reads_env_var(monkeypatch):
    monkeypatch.setenv("WORKER_MAX_JOBS", "2")

    assert Config().worker_max_jobs == 2


def test_worker_max_jobs_non_integer_falls_back_with_warning(monkeypatch, caplog):
    monkeypatch.setenv("WORKER_MAX_JOBS", "lots")

    with caplog.at_level("WARNING", logger="src.config"):
        assert Config().worker_max_jobs == 4

    assert "WORKER_MAX_JOBS" in caplog.text


def test_worker_max_jobs_below_one_clamps_to_one_with_warning(monkeypatch, caplog):
    monkeypatch.setenv("WORKER_MAX_JOBS", "0")

    with caplog.at_level("WARNING", logger="src.config"):
        assert Config().worker_max_jobs == 1

    assert "WORKER_MAX_JOBS" in caplog.text
