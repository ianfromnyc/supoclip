"""
Video encoder selection: libx264 (software, default) or VAAPI hardware encode.

Enabled with VIDEO_ENCODER=vaapi (plus optional VAAPI_DEVICE, default
/dev/dri/renderD128). Call sites keep building their ffmpeg commands for
libx264 exactly as before; `adapt_command_for_vaapi()` rewrites such a command
for h264_vaapi in one place. Centralising the rewrite guarantees byte-identical
libx264 commands when VAAPI is disabled, and leaves runners with the original
libx264 command as a ready-made fallback when a hardware encode fails.
"""

import logging
from typing import List, Optional

from .config import get_config

logger = logging.getLogger(__name__)

# Software-decoded frames must be converted to NV12 and uploaded to GPU
# surfaces before h264_vaapi can consume them.
VAAPI_UPLOAD_FILTER = "format=nv12,hwupload"
# Label used when we splice the upload stage onto a -filter_complex graph.
_HW_LABEL = "[vaapi_hw]"
# Name of the single hardware device shared by decode, filters and encode.
# One -init_hw_device that -hwaccel_device and -filter_hw_device both
# reference by name; passing raw paths instead would create duplicate device
# instances and make ffmpeg warn about ambiguous filter-device selection.
_HW_DEVICE_NAME = "supoclip_va"
# Inputs that get hardware decode. Only real video files: concat list files,
# lavfi sources, images and audio must keep software demux/decode.
_VIDEO_INPUT_EXTENSIONS = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi")


# Process-wide circuit breaker: once a VAAPI encode has failed, stop trying.
# Without it a broken/misconfigured GPU would make every single encode run
# twice (failed hardware attempt + software retry) for the whole task.
_vaapi_runtime_disabled = False


def vaapi_enabled() -> bool:
    return get_config().video_encoder == "vaapi"


def get_vaapi_device() -> str:
    return get_config().vaapi_device


def vaapi_available() -> bool:
    """VAAPI is configured and has not tripped the runtime circuit breaker."""
    return vaapi_enabled() and not _vaapi_runtime_disabled


def record_vaapi_failure(reason: str) -> None:
    """Disable VAAPI for the rest of this process after its first failure."""
    global _vaapi_runtime_disabled
    if _vaapi_runtime_disabled:
        return
    _vaapi_runtime_disabled = True
    logger.warning(
        "VAAPI encode on %s failed (%s); using libx264 for the rest of this process",
        get_vaapi_device(),
        reason,
    )


def _global_quality(crf: str) -> str:
    """Map a libx264 CRF to an ICQ/QVBR global_quality value.

    Both scales run 1-51, lower = better, and mid-range CRFs (18-23) track
    closely enough to reuse as-is. At the near-lossless end the iHD driver
    compresses noticeably harder than libx264 at the same number, so
    intermediate passes (CRF <= 16) get a 4-point boost to stay effectively
    lossless across the extra re-encode generation.
    """
    try:
        value = int(crf)
    except ValueError:
        return crf
    if value <= 16:
        value = max(1, value - 4)
    return str(value)


def _insert_hwaccel_decode(args: List[str]) -> List[str]:
    """Add VAAPI hardware decode in front of each video-file input.

    Deliberately decode-to-system-memory (no `-hwaccel_output_format vaapi`):
    the filter chains here (libass subtitle burn, pad, scale, concat, xfade)
    are CPU-only, so frames must land in system memory anyway. Plain -hwaccel
    gives GPU decode with an automatic download, the filters run unchanged and
    the trailing format=nv12,hwupload feeds the GPU encoder — the download/
    upload sandwich is the only workable shape for these graphs. ffmpeg's
    hwaccel is best-effort per stream, so unsupported codecs simply fall back
    to software decode.
    """
    result: List[str] = []
    # A pending -f means the NEXT file uses an explicit demuxer/muxer
    # (concat, lavfi, ...). The flag is scoped to that one file: it resets at
    # the input it precedes, and also at any bare output-file token so a
    # muxer -f can never suppress hwaccel on a later input.
    saw_demuxer = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-i" and index + 1 < len(args):
            input_path = args[index + 1]
            if not saw_demuxer and input_path.lower().endswith(
                _VIDEO_INPUT_EXTENSIONS
            ):
                result += ["-hwaccel", "vaapi", "-hwaccel_device", _HW_DEVICE_NAME]
            saw_demuxer = False
            result += [arg, input_path]
            index += 2
            continue
        if arg.startswith("-"):
            if arg == "-f":
                saw_demuxer = True
            result.append(arg)
            # Consume this option's value (values never start with "-" in the
            # commands we build), so any bare token seen below is a file.
            if index + 1 < len(args) and not args[index + 1].startswith("-"):
                result.append(args[index + 1])
                index += 2
                continue
            index += 1
            continue
        # Bare token not owned by an option: a file argument (e.g. the output).
        saw_demuxer = False
        result.append(arg)
        index += 1
    return result


def adapt_command_for_vaapi(command: List[str]) -> Optional[List[str]]:
    """Rewrite a libx264 ffmpeg command for h264_vaapi.

    Returns None when the command is not a recognised libx264 encode (e.g.
    ffprobe calls or audio-only extraction), in which case the caller should
    run the original command unchanged.
    """
    try:
        codec_index = command.index("libx264")
    except ValueError:
        return None
    if codec_index == 0 or command[codec_index - 1] != "-c:v":
        return None

    # Strip libx264-only options while remembering the rate-control intent.
    crf: Optional[str] = None
    result: List[str] = []
    skip_next = False
    for index, arg in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        next_arg = command[index + 1] if index + 1 < len(command) else None
        if arg == "-c:v" and next_arg == "libx264":
            result += ["-c:v", "h264_vaapi"]
            skip_next = True
        elif arg in ("-preset", "-x264-params"):
            # libx264-only tuning knobs; h264_vaapi rejects/ignores them.
            skip_next = True
        elif arg == "-crf":
            # Replaced below with the VAAPI equivalent rate control.
            crf = next_arg
            skip_next = True
        elif arg == "-pix_fmt" and next_arg == "yuv420p":
            # The NV12 hwupload already fixes the pixel format.
            skip_next = True
        else:
            result.append(arg)

    # Rate control, inserted right after the codec flag.
    rc_args: List[str] = []
    has_bitrate = "-b:v" in result or "-maxrate" in result
    if crf is not None and has_bitrate:
        # Quality-targeted encode with a peak cap (export presets: CRF plus
        # -maxrate/-bufsize). QVBR keeps the constant-quality target while the
        # retained cap args still bound the peaks; promoting the cap to a plain
        # VBR bitrate target was measured to inflate output roughly 2x. QVBR
        # refuses to open without a bitrate, so reuse the cap as -b:v.
        rc_args = ["-rc_mode", "QVBR", "-global_quality", _global_quality(crf)]
        if "-b:v" not in result and "-maxrate" in result:
            rc_args += ["-b:v", result[result.index("-maxrate") + 1]]
    elif has_bitrate:
        rc_args = ["-rc_mode", "VBR"]
        if "-b:v" not in result and "-maxrate" in result:
            # VBR needs a target bitrate; aim for the cap the profile defined.
            rc_args += ["-b:v", result[result.index("-maxrate") + 1]]
    elif crf is not None:
        # ICQ is VAAPI's constant-quality mode, the CRF analogue.
        rc_args = ["-rc_mode", "ICQ", "-global_quality", _global_quality(crf)]
    codec_pos = result.index("h264_vaapi") + 1
    result[codec_pos:codec_pos] = rc_args

    # Route frames to the GPU: append the upload stage to whatever video
    # filtering already exists (a second -vf would silently replace the first).
    if "-vf" in result:
        vf_index = result.index("-vf") + 1
        result[vf_index] = f"{result[vf_index]},{VAAPI_UPLOAD_FILTER}"
    elif "-filter_complex" in result:
        graph_index = result.index("-filter_complex") + 1
        try:
            # The first -map is the video stream at every call site.
            map_index = result.index("-map") + 1
        except ValueError:
            return None
        label = result[map_index]
        if not (label.startswith("[") and label.endswith("]")):
            return None
        result[graph_index] += f";{label}{VAAPI_UPLOAD_FILTER}{_HW_LABEL}"
        result[map_index] = _HW_LABEL
    else:
        # No filtering at all (plain trims/concats): add the upload as -vf.
        insert_at = result.index("-c:v")
        result[insert_at:insert_at] = ["-vf", VAAPI_UPLOAD_FILTER]

    # Hardware-decode each video-file input on the same shared device.
    result = _insert_hwaccel_decode(result)

    # Create the shared, named hardware device and point the software->GPU
    # filter boundary (hwupload) at it; goes right after `ffmpeg -y`.
    device_at = 2 if len(result) > 1 and result[1] == "-y" else 1
    result[device_at:device_at] = [
        "-init_hw_device",
        f"vaapi={_HW_DEVICE_NAME}:{get_vaapi_device()}",
        "-filter_hw_device",
        _HW_DEVICE_NAME,
    ]
    return result
