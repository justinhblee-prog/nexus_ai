"""Least-privilege OAuth scopes and safe per-channel token paths."""

UPLOAD_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
]
ANALYTICS_SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]
SCOPES = UPLOAD_SCOPES + ANALYTICS_SCOPES


def get_channel_token_path(channel_name):
    safe_name = "".join(ch for ch in str(channel_name) if ch.isalnum() or ch in ("-", "_"))
    if not safe_name:
        raise ValueError("Invalid channel name")
    return f"tokens/yt_token_{safe_name}.json"
