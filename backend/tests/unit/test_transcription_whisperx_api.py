import httpx
import pytest

from src.config import Config, set_config_override
from src.transcription_whisperx import (
    _transcript_from_asr_payload,
    get_video_transcript_whisperx,
)


# One /asr?output=json response: whisperx's aligned result, i.e. segments whose
# words carry second-precision bounds plus optional diarization labels.
ASR_PAYLOAD = {
    "segments": [
        {
            "start": 0.5,
            "end": 1.8,
            "text": "Hello there.",
            "words": [
                {"word": "Hello", "start": 0.5, "end": 1.0, "score": 0.9,
                 "speaker": "SPEAKER_00"},
                {"word": "there.", "start": 1.2, "end": 1.8, "score": 0.8,
                 "speaker": "SPEAKER_00"},
            ],
        },
        {
            "start": 2.0,
            "end": 2.6,
            "text": "Hi!",
            "words": [
                {"word": "Hi!", "start": 2.0, "end": 2.6, "score": 0.95,
                 "speaker": "SPEAKER_01"},
            ],
        },
    ],
    "language": "en",
}


def test_whisperx_api_url_is_read_from_env(monkeypatch):
    monkeypatch.setenv("WHISPERX_API_URL", "http://whisperx:9000")

    config = Config()

    assert config.whisperx_api_url == "http://whisperx:9000"


def test_whisperx_api_url_defaults_to_none(monkeypatch):
    monkeypatch.delenv("WHISPERX_API_URL", raising=False)

    config = Config()

    assert config.whisperx_api_url is None


def test_blank_whisperx_api_url_means_in_process(monkeypatch):
    """An empty value must not be mistaken for a configured endpoint."""
    monkeypatch.setenv("WHISPERX_API_URL", "   ")

    config = Config()

    assert config.whisperx_api_url is None


def test_payload_maps_to_assemblyai_shaped_words():
    transcript = _transcript_from_asr_payload(ASR_PAYLOAD)

    assert [word.text for word in transcript.words] == ["Hello", "there.", "Hi!"]
    # Seconds in, integer milliseconds out — the unit every consumer expects.
    assert [(word.start, word.end) for word in transcript.words] == [
        (500, 1000),
        (1200, 1800),
        (2000, 2600),
    ]
    assert transcript.text == "Hello there. Hi!"


def test_payload_maps_diarization_labels_to_letters():
    transcript = _transcript_from_asr_payload(ASR_PAYLOAD)

    assert [word.speaker for word in transcript.words] == ["A", "A", "B"]
    assert [utterance.speaker for utterance in transcript.utterances] == ["A", "B"]


def test_payload_without_speakers_has_no_utterances():
    payload = {
        "segments": [
            {
                "start": 0.0,
                "end": 0.4,
                "text": "Solo.",
                "words": [{"word": "Solo.", "start": 0.0, "end": 0.4}],
            }
        ]
    }

    transcript = _transcript_from_asr_payload(payload)

    assert [word.speaker for word in transcript.words] == [None]
    assert transcript.utterances == []


def test_empty_payload_is_rejected():
    """A 200 with no segments means the service transcribed nothing usable."""
    with pytest.raises(RuntimeError, match="no transcript segments"):
        _transcript_from_asr_payload({"segments": []})


@pytest.fixture
def media_file(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"not really a video")
    return path


@pytest.fixture
def whisperx_config(monkeypatch):
    """Config with WHISPERX_API_URL set, installed as the process-wide override."""
    monkeypatch.setenv("WHISPERX_API_URL", "http://whisperx:9000")
    monkeypatch.setenv("WHISPERX_DIARIZE", "true")
    config = Config()
    set_config_override(config)
    yield config
    set_config_override(None)


def test_configured_url_transcribes_over_http(monkeypatch, media_file, whisperx_config):
    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["params"] = kwargs["params"]
        calls["files"] = kwargs["files"]
        return httpx.Response(
            200, json=ASR_PAYLOAD, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    formatted = get_video_transcript_whisperx(media_file)

    assert calls["url"] == "http://whisperx:9000/asr"
    assert calls["params"]["output"] == "json"
    assert calls["params"]["diarize"] == "true"
    assert "audio_file" in calls["files"]
    # Timestamped, speaker-attributed lines — the same shape AssemblyAI yields.
    assert formatted.splitlines() == [
        "[00:00 - 00:01] Speaker A: Hello there.",
        "[00:02 - 00:02] Speaker B: Hi!",
    ]


def test_unset_url_runs_whisperx_in_process(monkeypatch, media_file):
    monkeypatch.delenv("WHISPERX_API_URL", raising=False)
    set_config_override(Config())

    def fail_post(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("HTTP must not be used when WHISPERX_API_URL is unset")

    monkeypatch.setattr(httpx, "post", fail_post)
    called = {}

    def fake_in_process(video_path, config):
        called["video_path"] = video_path
        return "in-process transcript"

    monkeypatch.setattr(
        "src.transcription_whisperx._transcribe_in_process", fake_in_process
    )

    try:
        assert get_video_transcript_whisperx(media_file) == "in-process transcript"
    finally:
        set_config_override(None)

    assert called["video_path"] == media_file


def test_unreachable_service_raises_an_actionable_error(
    monkeypatch, media_file, whisperx_config
):
    def refuse(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", refuse)

    with pytest.raises(RuntimeError) as excinfo:
        get_video_transcript_whisperx(media_file)

    message = str(excinfo.value)
    assert "http://whisperx:9000" in message
    assert "docker/options/whisperx.yml" in message


def test_error_response_reports_the_status_code(
    monkeypatch, media_file, whisperx_config
):
    def fail(url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(503, text="model loading", request=request)

    monkeypatch.setattr(httpx, "post", fail)

    with pytest.raises(RuntimeError, match="HTTP 503"):
        get_video_transcript_whisperx(media_file)
