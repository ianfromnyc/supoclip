import logging

import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from src import ai
from src import config as config_module
from src.ai import _build_transcript_model, _get_missing_llm_key_error
from src.config import Config


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


def _base_url_of(model: OpenAIChatModel) -> str:
    # The OpenAI SDK appends a trailing slash to the configured base URL.
    return str(model.client.base_url).rstrip("/")


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


def test_hosted_openai_keeps_the_published_endpoint(monkeypatch):
    monkeypatch.setenv("LLM", "openai:gpt-5.2")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    model = _build_transcript_model(Config())

    assert _base_url_of(model) == "https://api.openai.com/v1"
