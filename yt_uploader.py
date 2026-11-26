import os, pickle
from urllib.parse import urlparse, parse_qs
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["://".join(["https", "/".join([".".join(["www", "googleapis", "com"]), "auth", "youtube.upload"])])]
SECRET_PATH = "tokens/client_secret.json"

def get_auth_url(channel_name):
    if not os.path.exists(SECRET_PATH):
        return None, f"파일을 찾을 수 없습니다: {os.path.abspath(SECRET_PATH)}"
    flow = InstalledAppFlow.from_client_secrets_file(SECRET_PATH, SCOPES, redirect_uri="http://localhost")
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    return flow, auth_url

def save_auth_code(channel_name, flow, redirected_url):
    os.makedirs("tokens", exist_ok=True)
    raw = redirected_url.strip()
    if "code=" in raw:
        parsed = parse_qs(urlparse(raw).query)
        code = parsed.get("code", [""]).pop(0)
    else:
        code = raw
    flow.fetch_token(code=code)
    with open(f"tokens/yt_token_{channel_name}.pickle", "wb") as f:
        pickle.dump(flow.credentials, f)

def upload_to_youtube(channel_name, video_path, title, description="AI 자동 생성 숏폼 #Shorts"):
    token_file = f"tokens/yt_token_{channel_name}.pickle"
    if not os.path.exists(token_file):
        return False, "NEED_AUTH"
    with open(token_file, "rb") as f:
        creds = pickle.load(f)
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title[:100], "description": description, "tags": ["Shorts", "AI"], "categoryId": "22"},
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    vid = res.get("id")
    return True, f"업로드 성공! 영상 ID: {vid} 👉 스튜디오 바로가기: https://youtube.com{vid}/edit"

