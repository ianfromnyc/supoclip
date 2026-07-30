import pytest

from src.api.routes.admin import transcription_provider_error


def test_unknown_provider_is_rejected():
    error = transcription_provider_error("wisperx")

    assert error is not None
    assert "wisperx" in error


def test_assemblyai_is_always_accepted():
    assert transcription_provider_error("assemblyai") is None


def test_whisperx_is_accepted_when_a_webservice_is_configured(monkeypatch):
    """The Docker stack transcribes over HTTP, so the local extra is irrelevant."""
    monkeypatch.setenv("WHISPERX_API_URL", "http://whisperx:9000")

    assert transcription_provider_error("whisperx") is None


def test_whisperx_without_url_or_extra_is_rejected(monkeypatch):
    import importlib.util

    monkeypatch.delenv("WHISPERX_API_URL", raising=False)
    if importlib.util.find_spec("whisperx") is not None:
        pytest.skip("whisperx extra is installed, so selecting it is valid")

    error = transcription_provider_error("whisperx")

    assert error is not None
    assert "WHISPERX_API_URL" in error
