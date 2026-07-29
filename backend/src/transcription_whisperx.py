"""
Local transcription provider built on WhisperX
(faster-whisper ASR + wav2vec2 forced alignment + optional pyannote diarization).

Selected via TRANSCRIPTION_PROVIDER=whisperx. Emits the exact transcript shape
the AssemblyAI path produces — millisecond word timings, "A"/"B" speaker
labels, utterances, and the same .transcript_cache.json layout — so every
downstream consumer (subtitles, clip editor, AI analysis) works unchanged.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from .config import get_config

logger = logging.getLogger(__name__)

# AssemblyAI labels speakers "A", "B", ... — map WhisperX's "SPEAKER_00" style
# labels onto the same convention so transcripts and captions look identical.
_SPEAKER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# The ARQ worker runs up to max_jobs=4 tasks concurrently and transcription is
# pushed onto a thread, so without a lock four Whisper models could load onto
# one GPU at once and OOM it. The lock serializes the whole WhisperX path; the
# caches keep loaded models resident so serialized tasks skip the reload (and
# first-run download) cost — deliberately trading memory for latency.
_WHISPERX_LOCK = threading.Lock()
_ASR_CACHE: Dict[Tuple[str, str, str], Any] = {}
_ALIGN_CACHE: Dict[Tuple[Optional[str], str], Tuple[Any, Any]] = {}
_DIARIZE_CACHE: Dict[str, Any] = {}


def _import_whisperx():
    """Import whisperx lazily so the heavy torch stack stays optional."""
    try:
        import whisperx
    except ImportError as exc:
        raise RuntimeError(
            "TRANSCRIPTION_PROVIDER=whisperx but the whisperx package is not "
            "installed. Install the backend's optional extra first: "
            "`uv sync --extra whisperx`."
        ) from exc
    return whisperx


def _resolve_device(configured: str) -> str:
    """Resolve WHISPERX_DEVICE (`auto` picks cuda when available, else cpu).

    Lives behind the lazy whisperx import because detection needs torch,
    which is only installed with the whisperx extra.
    """
    if configured in ("cuda", "cpu"):
        return configured
    if configured not in ("", "auto"):
        logger.warning(
            "Unknown WHISPERX_DEVICE=%r; auto-detecting instead", configured
        )

    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _get_asr_model(whisperx, model_name: str, device: str, compute_type: str):
    key = (model_name, device, compute_type)
    model = _ASR_CACHE.get(key)
    if model is None:
        model = whisperx.load_model(model_name, device, compute_type=compute_type)
        _ASR_CACHE[key] = model
    return model


def _get_align_model(whisperx, language: Optional[str], device: str):
    key = (language, device)
    cached = _ALIGN_CACHE.get(key)
    if cached is None:
        cached = whisperx.load_align_model(language_code=language, device=device)
        _ALIGN_CACHE[key] = cached
    return cached


def _normalize_speaker(
    raw_speaker: Optional[str], speaker_map: Dict[str, str]
) -> Optional[str]:
    """Map diarization labels (SPEAKER_00, ...) to letters in order of appearance."""
    if not raw_speaker:
        return None
    if raw_speaker not in speaker_map:
        index = len(speaker_map)
        speaker_map[raw_speaker] = (
            _SPEAKER_ALPHABET[index]
            if index < len(_SPEAKER_ALPHABET)
            else raw_speaker
        )
    return speaker_map[raw_speaker]


def _build_segment_words(
    segment: Dict[str, Any], speaker_map: Dict[str, str]
) -> List[SimpleNamespace]:
    """Convert one aligned WhisperX segment into AssemblyAI-shaped word objects.

    WhisperX leaves words it could not force-align (numerals, etc.) without
    timestamps, so missing bounds are borrowed from neighbours / the segment.
    Times are converted from seconds to integer milliseconds (AssemblyAI units).
    """
    raw_words = segment.get("words") or []
    words: List[SimpleNamespace] = []
    prev_end = segment.get("start")

    for index, raw in enumerate(raw_words):
        text = (raw.get("word") or "").strip()
        if not text:
            continue

        start = raw.get("start")
        end = raw.get("end")
        if start is None:
            start = prev_end if prev_end is not None else segment.get("start", 0.0)
        if end is None:
            # Use the next aligned word's start, else the segment end.
            end = next(
                (
                    w.get("start")
                    for w in raw_words[index + 1:]
                    if w.get("start") is not None
                ),
                segment.get("end", start),
            )
        # A borrowed end can precede the start (e.g. the segment end is earlier
        # than the previous word's end); clamp to avoid negative durations.
        start = float(start)
        end = max(float(end), start)
        prev_end = end

        words.append(
            SimpleNamespace(
                text=text,
                start=int(round(start * 1000)),
                end=int(round(end * 1000)),
                confidence=float(raw.get("score", 1.0)),
                speaker=_normalize_speaker(raw.get("speaker"), speaker_map),
            )
        )

    return words


def _build_transcript(segments: List[Dict[str, Any]]) -> SimpleNamespace:
    """Assemble a transcript object mirroring the AssemblyAI SDK's shape.

    Only the attributes downstream code reads are provided: .text, .words and
    .utterances (each utterance with text/start/end/speaker/words). Utterances
    are only built when diarization produced speaker labels — without speakers
    the words-based fallback formatting gives better timestamp granularity.
    """
    speaker_map: Dict[str, str] = {}
    all_words: List[SimpleNamespace] = []
    segment_entries: List[Dict[str, Any]] = []
    text_parts: List[str] = []

    for segment in segments:
        seg_words = _build_segment_words(segment, speaker_map)
        if not seg_words:
            continue
        seg_text = (segment.get("text") or "").strip()
        text_parts.append(seg_text)
        all_words.extend(seg_words)

        # A segment's speaker is the one who spoke most of its words.
        speaker_counts: Dict[Optional[str], int] = {}
        for word in seg_words:
            speaker_counts[word.speaker] = speaker_counts.get(word.speaker, 0) + 1
        segment_speaker = max(speaker_counts, key=speaker_counts.get)

        segment_entries.append(
            {"text": seg_text, "speaker": segment_speaker, "words": seg_words}
        )

    utterances: List[SimpleNamespace] = []
    if speaker_map:
        # Merge consecutive same-speaker segments into speaker turns, matching
        # AssemblyAI's utterance semantics.
        for entry in segment_entries:
            if utterances and utterances[-1].speaker == entry["speaker"]:
                current = utterances[-1]
                current.text = f"{current.text} {entry['text']}".strip()
                current.words.extend(entry["words"])
                current.end = entry["words"][-1].end
            else:
                utterances.append(
                    SimpleNamespace(
                        text=entry["text"],
                        start=entry["words"][0].start,
                        end=entry["words"][-1].end,
                        speaker=entry["speaker"],
                        words=list(entry["words"]),
                    )
                )

    return SimpleNamespace(
        text=" ".join(part for part in text_parts if part),
        words=all_words,
        utterances=utterances,
    )


def _apply_diarization(aligned, audio, device: str, hf_token: str):
    """Run pyannote diarization and attach per-word speaker labels."""
    # whisperx's __init__ does not re-export DiarizationPipeline, so import
    # straight from the diarize submodule (stable in the pinned <3.4 series).
    from whisperx.diarize import DiarizationPipeline, assign_word_speakers

    pipeline = _DIARIZE_CACHE.get(device)
    if pipeline is None:
        pipeline = DiarizationPipeline(use_auth_token=hf_token, device=device)
        _DIARIZE_CACHE[device] = pipeline

    diarize_segments = pipeline(audio)
    return assign_word_speakers(diarize_segments, aligned)


def get_video_transcript_whisperx(video_path: Path) -> str:
    """Transcribe locally with WhisperX; formatted output + cache match AssemblyAI."""
    # Imported here (not at module top) purely for clarity — video_utils is
    # fully loaded by the time its dispatcher calls into this module.
    from .video_utils import cache_transcript_data, format_transcript_for_analysis

    config = get_config()
    whisperx = _import_whisperx()
    device = _resolve_device(config.whisperx_device)
    # float16 needs GPU support; int8 is the sensible CPU default.
    compute_type = config.whisperx_compute_type or (
        "float16" if device == "cuda" else "int8"
    )

    # Serialize the whole GPU-heavy path — see the lock comment at the top.
    with _WHISPERX_LOCK:
        logger.info(
            "Starting WhisperX transcription (model=%s, device=%s, compute_type=%s)",
            config.whisperx_model,
            device,
            compute_type,
        )

        # whisperx.load_audio decodes any container to 16 kHz mono via ffmpeg.
        audio = whisperx.load_audio(str(video_path))

        model = _get_asr_model(whisperx, config.whisperx_model, device, compute_type)
        result = model.transcribe(audio, batch_size=8)
        language = result.get("language")

        align_model, align_metadata = _get_align_model(whisperx, language, device)
        aligned = whisperx.align(
            result["segments"],
            align_model,
            align_metadata,
            audio,
            device,
            return_char_alignments=False,
        )

        if config.whisperx_diarize:
            if config.hf_token:
                try:
                    aligned = _apply_diarization(
                        aligned, audio, device, config.hf_token
                    )
                except Exception:
                    logger.warning(
                        "WhisperX diarization failed; continuing without speaker labels",
                        exc_info=True,
                    )
            else:
                logger.warning(
                    "WHISPERX_DIARIZE is enabled but HF_TOKEN is not set; "
                    "skipping speaker diarization"
                )

    transcript = _build_transcript(aligned.get("segments") or [])
    formatted_lines = format_transcript_for_analysis(transcript)
    cache_transcript_data(video_path, transcript)

    formatted = "\n".join(formatted_lines)
    logger.info(
        "WhisperX transcript formatted: %s segments, %s chars",
        len(formatted_lines),
        len(formatted),
    )
    return formatted
