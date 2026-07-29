"""
Video encoder selection: libx264 (software, default) or VAAPI hardware encode.

Enabled with VIDEO_ENCODER=vaapi (plus optional VAAPI_DEVICE, default
/dev/dri/renderD128). Call sites keep building their ffmpeg commands for
libx264 exactly as before; `adapt_command_for_vaapi()` rewrites such a command
for h264_vaapi in one place. Centralising the rewrite guarantees byte-identical
libx264 commands when VAAPI is disabled, and leaves runners with the original
libx264 command as a ready-made fallback when a hardware encode fails.
"""

from typing import List, Optional

from .config import get_config

# Software-decoded frames must be converted to NV12 and uploaded to GPU
# surfaces before h264_vaapi can consume them.
VAAPI_UPLOAD_FILTER = "format=nv12,hwupload"
# Label used when we splice the upload stage onto a -filter_complex graph.
_HW_LABEL = "[vaapi_hw]"
# Inputs that get hardware decode. Only real video files: concat list files,
# lavfi sources, images and audio must keep software demux/decode.
_VIDEO_INPUT_EXTENSIONS = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi")


def vaapi_enabled() -> bool:
    return get_config().video_encoder == "vaapi"


def get_vaapi_device() -> str:
    return get_config().vaapi_device


def _insert_hwaccel_decode(args: List[str], device: str) -> List[str]:
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
    saw_demuxer = False  # a -f before the input means concat/lavfi/etc.
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-f":
            saw_demuxer = True
        if arg == "-i" and index + 1 < len(args):
            input_path = args[index + 1]
            if not saw_demuxer and input_path.lower().endswith(
                _VIDEO_INPUT_EXTENSIONS
            ):
                result += ["-hwaccel", "vaapi", "-hwaccel_device", device]
            saw_demuxer = False  # per-input options end at the input file
            result += [arg, input_path]
            index += 2
            continue
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

    # Rate control, inserted right after the codec flag. Bitrate-capped
    # profiles (export presets with -maxrate) map to VBR; CRF profiles map to
    # ICQ, VAAPI's constant-quality mode, reusing the CRF value since both are
    # roughly "lower is better quality" on comparable scales.
    rc_args: List[str] = []
    if "-b:v" in result or "-maxrate" in result:
        rc_args = ["-rc_mode", "VBR"]
        if "-b:v" not in result and "-maxrate" in result:
            # VBR needs a target bitrate; aim for the cap the preset defined.
            rc_args += ["-b:v", result[result.index("-maxrate") + 1]]
    elif crf is not None:
        rc_args = ["-rc_mode", "ICQ", "-global_quality", crf]
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

    # Hardware-decode each video-file input on the same device.
    device = get_vaapi_device()
    result = _insert_hwaccel_decode(result, device)

    # Global option creating the hardware device; goes right after `ffmpeg -y`.
    device_at = 2 if len(result) > 1 and result[1] == "-y" else 1
    result[device_at:device_at] = ["-vaapi_device", device]
    return result
