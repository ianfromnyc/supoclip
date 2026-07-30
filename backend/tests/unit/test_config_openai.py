from src.config import Config


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
