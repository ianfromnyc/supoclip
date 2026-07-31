from pathlib import Path

from src.config import Config

REPO_ROOT = Path(__file__).resolve().parents[3]
HOSTED_OPENAI_BASE_URL = "https://api.openai.com/v1"


def test_shipped_config_never_leaves_openai_base_url_blank():
    # The endpoint scheme rests on this. A blank OPENAI_BASE_URL is not "use the
    # default" — the OpenAI client reads the empty string as a configured
    # endpoint, skips its own default, and fails every request.
    for env_example in (
        REPO_ROOT / ".env.example",
        REPO_ROOT / "backend" / ".env.example",
    ):
        assignments = [
            line.split("=", 1)[1]
            for line in env_example.read_text().splitlines()
            if line.startswith("OPENAI_BASE_URL=")
        ]
        assert assignments == [HOSTED_OPENAI_BASE_URL], env_example

    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    # Compose substitutes its own default, so an older .env cannot reintroduce
    # the blank value inside the container.
    assert "OPENAI_BASE_URL=${OPENAI_BASE_URL:-}" not in compose
    assert (
        f"OPENAI_BASE_URL=${{OPENAI_BASE_URL:-{HOSTED_OPENAI_BASE_URL}}}" in compose
    )


def test_openai_base_url_and_service_tier_are_read_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", "flex")

    config = Config()

    assert config.openai_base_url == "http://localhost:8080/v1"
    assert config.openai_service_tier == "flex"


def test_openai_endpoint_settings_default_to_none(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_SERVICE_TIER", raising=False)

    config = Config()

    assert config.openai_base_url is None
    assert config.openai_service_tier is None


def test_openai_endpoint_settings_are_exposed_as_runtime_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", "priority")

    settings = Config().as_runtime_settings()

    assert settings["OPENAI_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert settings["OPENAI_SERVICE_TIER"] == "priority"
