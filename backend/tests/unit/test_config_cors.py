from src.config import Config


def test_cors_origins_default_covers_published_docker_and_dev_ports(monkeypatch):
    # Stock `docker-compose up` publishes the frontend on host port 3001, while
    # local `next dev` runs on 3107. Browser requests come from either origin,
    # so both must be allowed out of the box.
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    origins = Config().cors_origins

    assert "http://localhost:3001" in origins
    assert "http://localhost:3107" in origins


def test_cors_origins_default_covers_loopback_ip_host(monkeypatch):
    # The compose port is published on 127.0.0.1, so a user may well browse to
    # http://127.0.0.1:3001 instead of localhost. Browsers treat that as a
    # distinct origin, so it needs its own allow-list entry.
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert "http://127.0.0.1:3001" in Config().cors_origins


def test_cors_origins_reads_env_var(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com,https://example.com")

    assert Config().cors_origins == [
        "https://app.example.com",
        "https://example.com",
    ]
