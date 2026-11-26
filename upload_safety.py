"""Classify YouTube upload responses without assuming privacy succeeded."""


def classify_upload_response(response):
    if not isinstance(response, dict):
        return "invalid_response", None, None
    video_id = response.get("id")
    if not isinstance(video_id, str) or not video_id.strip():
        return "missing_video_id", None, None
    status = response.get("status")
    privacy = status.get("privacyStatus") if isinstance(status, dict) else None
    if privacy != "private":
        return "privacy_unverified", video_id, privacy
    return "private", video_id, privacy
