import logging

import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from src import ai
from src import config as config_module
from src.ai import (
    _build_transcript_model,
    _build_transcript_model_settings,
    _get_missing_llm_key_error,
    get_transcript_agent,
)
from src.config import Config, set_config_override


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch):
    """Start every test from a blank LLM environment.

    Config reads these straight from the process environment, and a developer
    machine (or a leftover .env) can otherwise leak real credentials into the
    assertions below.
    """
    for name in (
        "LLM",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_SERVICE_TIER",
        "OLLAMA_BASE_URL",
        "OLLAMA_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    # The deprecation warning fires once per process; reset it per test.
    monkeypatch.setattr(ai, "_deprecated_provider_alias_warned", set())
    # Drop any agent cached by an earlier test so signatures start clean.
    monkeypatch.setattr(ai, "_transcript_agent", None)
    monkeypatch.setattr(ai, "_transcript_agent_signature", None)
    yield
    set_config_override(None)


def _base_url_of(model: OpenAIChatModel) -> str:
    # The OpenAI SDK appends a trailing slash to the configured base URL.
    return str(model.client.base_url).rstrip("/")


def _api_key_of(model: OpenAIChatModel) -> str | None:
    # What the client will actually send as the bearer token.
    return model.client.api_key


def test_openai_model_uses_custom_base_url_without_an_api_key(monkeypatch):
    monkeypatch.setenv("LLM", "openai:qwen3-coder")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8080/v1")

    model = _build_transcript_model(Config())

    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "qwen3-coder"
    assert _base_url_of(model) == "http://localhost:8080/v1"


def test_ollama_alias_routes_through_the_openai_compatible_model(monkeypatch):
    monkeypatch.setenv("LLM", "ollama:gpt-oss:20b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.example/v1")

    model = _build_transcript_model(Config())

    assert isinstance(model, OpenAIChatModel)
    # Only the first colon separates provider from model name.
    assert model.model_name == "gpt-oss:20b"
    assert _base_url_of(model) == "http://ollama.example/v1"


def test_ollama_alias_falls_back_to_the_default_local_endpoint(monkeypatch):
    monkeypatch.setattr(config_module.os.path, "exists", lambda path: False)
    monkeypatch.setenv("LLM", "ollama:gpt-oss:20b")

    model = _build_transcript_model(Config())

    assert _base_url_of(model) == "http://localhost:11434/v1"


def test_openai_base_url_takes_precedence_over_the_ollama_alias(monkeypatch):
    monkeypatch.setenv("LLM", "ollama:gpt-oss:20b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.example/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://llama-swap.example/v1")

    model = _build_transcript_model(Config())

    assert _base_url_of(model) == "http://llama-swap.example/v1"


def test_ollama_alias_never_leaks_the_openai_key_to_the_legacy_endpoint(monkeypatch):
    # The key must be paired with the base URL it belongs to: an OPENAI_API_KEY
    # set for some other purpose must not be sent as a bearer token to the
    # user's local Ollama server.
    monkeypatch.setenv("LLM", "ollama:gpt-oss:20b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-hosted-openai-secret")

    model = _build_transcript_model(Config())

    assert _base_url_of(model) == "http://ollama.example/v1"
    assert _api_key_of(model) != "sk-hosted-openai-secret"


def test_ollama_alias_default_endpoint_never_leaks_the_openai_key(monkeypatch):
    # Same pairing rule when the base URL comes from the localhost default
    # rather than from OLLAMA_BASE_URL.
    monkeypatch.setattr(config_module.os.path, "exists", lambda path: False)
    monkeypatch.setenv("LLM", "ollama:gpt-oss:20b")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-hosted-openai-secret")

    model = _build_transcript_model(Config())

    assert _base_url_of(model) == "http://localhost:11434/v1"
    assert _api_key_of(model) != "sk-hosted-openai-secret"


def test_ollama_alias_uses_the_ollama_key_for_the_legacy_endpoint(monkeypatch):
    monkeypatch.setenv("LLM", "ollama:gpt-oss:20b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.example/v1")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-hosted-openai-secret")

    model = _build_transcript_model(Config())

    assert _api_key_of(model) == "ollama-key"


def test_ollama_alias_pairs_the_openai_key_with_the_openai_base_url(monkeypatch):
    # When OPENAI_BASE_URL wins the base URL, the OpenAI key travels with it —
    # the legacy OLLAMA_API_KEY belongs to the endpoint that was not chosen.
    monkeypatch.setenv("LLM", "ollama:gpt-oss:20b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.example/v1")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://llama-swap.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-hosted-openai-secret")

    model = _build_transcript_model(Config())

    assert _base_url_of(model) == "http://llama-swap.example/v1"
    assert _api_key_of(model) == "sk-hosted-openai-secret"


def test_ollama_alias_logs_a_deprecation_warning_once(monkeypatch, caplog):
    monkeypatch.setenv("LLM", "ollama:gpt-oss:20b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.example/v1")

    with caplog.at_level(logging.WARNING, logger="src.ai"):
        _build_transcript_model(Config())
        _build_transcript_model(Config())

    deprecation_records = [
        record for record in caplog.records if "deprecated" in record.getMessage()
    ]
    assert len(deprecation_records) == 1
    assert "openai:" in deprecation_records[0].getMessage()


def test_hosted_openai_without_an_api_key_is_a_config_error(monkeypatch):
    monkeypatch.setenv("LLM", "openai:gpt-5.2")

    error = _get_missing_llm_key_error("openai:gpt-5.2", Config())

    assert error is not None
    assert "OPENAI_API_KEY" in error
    # The message must point at the escape hatch for local/self-hosted servers.
    assert "OPENAI_BASE_URL" in error


def test_custom_openai_base_url_does_not_require_an_api_key(monkeypatch):
    monkeypatch.setenv("LLM", "openai:qwen3-coder")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8080/v1")

    assert _get_missing_llm_key_error("openai:qwen3-coder", Config()) is None


@pytest.mark.parametrize(
    "tier", ["auto", "default", "flex", "scale", "priority"]
)
def test_every_documented_service_tier_is_accepted(monkeypatch, tier):
    monkeypatch.setenv("LLM", "openai:gpt-5.2")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", tier)

    assert _get_missing_llm_key_error("openai:gpt-5.2", Config()) is None


def test_unknown_service_tier_is_a_config_error(monkeypatch):
    monkeypatch.setenv("LLM", "openai:gpt-5.2")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", "turbo")

    error = _get_missing_llm_key_error("openai:gpt-5.2", Config())

    assert error is not None
    assert "OPENAI_SERVICE_TIER" in error
    assert "turbo" in error
    assert "flex" in error


def test_service_tier_is_sent_with_each_request_when_set(monkeypatch):
    monkeypatch.setenv("LLM", "openai:gpt-5.2")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", "Flex")

    settings = _build_transcript_model_settings(Config())

    # Normalized, because OpenAI only accepts the lowercase spellings.
    assert settings == {"openai_service_tier": "flex"}


def test_no_model_settings_when_service_tier_is_unset(monkeypatch):
    monkeypatch.setenv("LLM", "openai:gpt-5.2")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    assert _build_transcript_model_settings(Config()) is None


def test_service_tier_is_not_sent_to_non_openai_providers(monkeypatch):
    monkeypatch.setenv("LLM", "anthropic:claude-4-sonnet")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", "flex")

    assert _build_transcript_model_settings(Config()) is None


def test_agent_cache_is_invalidated_when_the_base_url_changes(monkeypatch):
    monkeypatch.setenv("LLM", "openai:qwen3-coder")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://first.example/v1")

    set_config_override(Config())
    first = get_transcript_agent()
    assert get_transcript_agent() is first

    monkeypatch.setenv("OPENAI_BASE_URL", "http://second.example/v1")
    set_config_override(Config())

    assert get_transcript_agent() is not first


def test_agent_cache_is_invalidated_when_the_service_tier_changes(monkeypatch):
    monkeypatch.setenv("LLM", "openai:qwen3-coder")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://first.example/v1")

    set_config_override(Config())
    first = get_transcript_agent()

    monkeypatch.setenv("OPENAI_SERVICE_TIER", "flex")
    set_config_override(Config())

    assert get_transcript_agent() is not first


def test_hosted_openai_keeps_the_published_endpoint(monkeypatch):
    monkeypatch.setenv("LLM", "openai:gpt-5.2")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    model = _build_transcript_model(Config())

    assert _base_url_of(model) == "https://api.openai.com/v1"
