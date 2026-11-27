"""Deterministic ffprobe-based checks for generated vertical Shorts."""
import json
import os
import shutil
import subprocess


def validate_video(path, ffprobe_bin=None, timeout=30):
    result = {
        "ok": False,
        "path": path,
        "checks": {},
        "errors": [],
        "metadata": {},
    }
    if not isinstance(path, str) or not path.strip() or not os.path.isfile(path):
        result["errors"].append("video_file_missing")
        return result
    size = os.path.getsize(path)
    result["checks"]["file_nonempty"] = size > 1024
    result["metadata"]["size_bytes"] = size
    if size <= 1024:
        result["errors"].append("video_file_empty_or_too_small")
        return result

    binary = ffprobe_bin or shutil.which("ffprobe") or "ffprobe"
    command = [
        binary, "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height",
        "-of", "json", path,
    ]
    try:
        probe = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        result["errors"].append("ffprobe_not_installed")
        return result
    except subprocess.TimeoutExpired:
        result["errors"].append("ffprobe_timeout")
        return result
    if probe.returncode != 0:
        result["errors"].append("ffprobe_failed")
        return result
    try:
        data = json.loads(probe.stdout or "{}")
    except (TypeError, ValueError):
        result["errors"].append("ffprobe_invalid_json")
        return result

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    try:
        duration = float((data.get("format") or {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0

    checks = {
        "video_stream_present": bool(video),
        "audio_stream_present": bool(audio),
        "vertical_1080x1920": video.get("width") == 1080 and video.get("height") == 1920,
        "h264_video": video.get("codec_name") == "h264",
        "aac_audio": audio.get("codec_name") == "aac",
        "duration_in_shorts_range": 1.0 <= duration <= 180.0,
    }
    result["checks"].update(checks)
    result["metadata"].update({
        "duration_seconds": duration,
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
    })
    result["errors"].extend(name for name, passed in checks.items() if not passed)
    result["ok"] = not result["errors"]
    return result
