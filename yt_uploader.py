import os
from urllib.parse import urlparse, parse_qs

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from upload_safety import classify_upload_response
from oauth_config import SCOPES, UPLOAD_SCOPES, ANALYTICS_SCOPES, get_channel_token_path

SECRET_PATH = "tokens/client_secret.json"


def _token_path(channel_name):
    return get_channel_token_path(channel_name)


def get_channel_token_status(channel_name):
    token_file = _token_path(channel_name)
    if not os.path.exists(token_file):
        return {"exists": False, "upload": False, "analytics": False, "expired": False, "error": None}
    try:
        creds = Credentials.from_authorized_user_file(token_file)
        return {
            "exists": True,
            "upload": creds.has_scopes(UPLOAD_SCOPES),
            "analytics": creds.has_scopes(ANALYTICS_SCOPES),
            "expired": bool(creds.expired),
            "error": None,
        }
    except Exception as exc:
        return {"exists": True, "upload": False, "analytics": False, "expired": False, "error": type(exc).__name__}


def get_auth_url(channel_name):
    if not os.path.exists(SECRET_PATH):
        return None, f"파일을 찾을 수 없습니다: {os.path.abspath(SECRET_PATH)}"
    flow = InstalledAppFlow.from_client_secrets_file(SECRET_PATH, SCOPES, redirect_uri="http://localhost")
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline", include_granted_scopes="true")
    return flow, auth_url


def save_auth_code(channel_name, flow, redirected_url):
    os.makedirs("tokens", exist_ok=True)
    raw = redirected_url.strip()
    if "code=" in raw:
        parsed = parse_qs(urlparse(raw).query)
        code = parsed.get("code", [""])[0]
    else:
        code = raw
    if not code:
        raise ValueError("Google OAuth authorization code is missing")
    flow.fetch_token(code=code)
    with open(_token_path(channel_name), "w", encoding="utf-8") as token_file:
        token_file.write(flow.credentials.to_json())


def upload_to_youtube(channel_name, video_path, title, description="AI 자동 생성 숏폼 #Shorts"):
    token_file = _token_path(channel_name)
    if not os.path.exists(token_file):
        return False, "NEED_AUTH"
    if not os.path.isfile(video_path):
        return False, f"VIDEO_NOT_FOUND: {video_path}"

    upload_started = False
    try:
        creds = Credentials.from_authorized_user_file(token_file)
        if not creds.has_scopes(UPLOAD_SCOPES):
            return False, "NEED_AUTH"
        if creds.expired:
            if not creds.refresh_token:
                return False, "NEED_AUTH"
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            with open(token_file, "w", encoding="utf-8") as token_file_handle:
                token_file_handle.write(creds.to_json())
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": ["Shorts", "AI"],
                "categoryId": "22",
            },
            "status": {
                # Uploads remain private; a separate human action is required to publish.
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        upload_started = True
        response = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
        outcome, video_id, privacy_status = classify_upload_response(response)
        if outcome == "private":
            return True, f"비공개 업로드 성공! 영상 ID: {video_id} 👉 https://www.youtube.com/watch?v={video_id}"
        return False, f"UPLOAD_CREATED_PRIVACY_UNVERIFIED:{video_id or 'unknown'}:{privacy_status or outcome}"
    except Exception as exc:
        if upload_started:
            return False, f"UPLOAD_RESULT_UNCERTAIN:{type(exc).__name__}"
        return False, f"YOUTUBE_UPLOAD_FAILED: {type(exc).__name__}: {exc}"
