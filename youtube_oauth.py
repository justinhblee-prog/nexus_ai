"""Google Web OAuth helpers for YouTube channel linking."""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import urlencode, urlparse

import requests


YOUTUBE_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)


class GoogleOAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    app_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None):
        values = os.environ if env is None else env
        client_id = values.get("NEXUS_GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = values.get("NEXUS_GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        redirect_uri = values.get("NEXUS_GOOGLE_OAUTH_REDIRECT_URI", "").strip()
        app_url = values.get("NEXUS_HOSTED_APP_URL", "").strip().rstrip("/")
        if not client_id or not client_secret:
            raise GoogleOAuthError("Google Web OAuth client configuration is missing")
        if not redirect_uri.startswith("https://") or not app_url.startswith("https://"):
            raise GoogleOAuthError("Google OAuth callback and hosted app URLs must use HTTPS")
        parsed_redirect = urlparse(redirect_uri)
        if parsed_redirect.path != "/api/hosted/youtube/callback" or parsed_redirect.query or parsed_redirect.fragment:
            raise GoogleOAuthError("Google OAuth redirect URI must be the exact NEXUS callback endpoint")
        parsed_app = urlparse(app_url)
        if parsed_app.path or parsed_app.query or parsed_app.fragment:
            raise GoogleOAuthError("NEXUS_HOSTED_APP_URL must be an origin without a path")
        return cls(client_id, client_secret, redirect_uri, app_url)

    def authorization_url(self, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(YOUTUBE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

    def exchange_code(self, code: str, code_verifier: str, http_post: Callable = requests.post) -> dict:
        try:
            response = http_post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "code_verifier": code_verifier,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=10,
            )
        except requests.RequestException as exc:
            raise GoogleOAuthError("Google token service is temporarily unavailable") from exc
        if response.status_code != 200:
            raise GoogleOAuthError("Google rejected the OAuth authorization code")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleOAuthError("Google returned an invalid token response") from exc
        if not payload.get("access_token"):
            raise GoogleOAuthError("Google did not return an access token")
        return payload

    def fetch_account(self, access_token: str, http_get: Callable = requests.get) -> dict:
        try:
            response = http_get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise GoogleOAuthError("Google account identity service is temporarily unavailable") from exc
        if response.status_code != 200:
            raise GoogleOAuthError("Google account identity could not be verified")
        try:
            account = response.json()
        except ValueError as exc:
            raise GoogleOAuthError("Google returned an invalid account response") from exc
        if not account.get("sub"):
            raise GoogleOAuthError("Google account subject is missing")
        return {"account_id": account["sub"], "email": account.get("email", ""), "name": account.get("name", "")}

    def fetch_channels(self, access_token: str, http_get: Callable = requests.get) -> list[dict]:
        try:
            response = http_get(
                "https://youtube.googleapis.com/youtube/v3/channels",
                params={"part": "id,snippet", "mine": "true", "maxResults": "50"},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise GoogleOAuthError("YouTube channel service is temporarily unavailable") from exc
        if response.status_code != 200:
            raise GoogleOAuthError("YouTube channel identity could not be verified")
        try:
            items = response.json().get("items", [])
        except ValueError as exc:
            raise GoogleOAuthError("YouTube returned an invalid channel response") from exc
        channels = []
        for item in items:
            channel_id = item.get("id")
            title = (item.get("snippet") or {}).get("title")
            if channel_id and title:
                channels.append({"channel_id": channel_id, "title": title})
        if not channels:
            raise GoogleOAuthError("No YouTube channel is available for this Google account")
        return channels

    def revoke_refresh_token(self, refresh_token: str, http_post: Callable = requests.post):
        try:
            response = http_post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": refresh_token},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise GoogleOAuthError("Google token revocation service is temporarily unavailable") from exc
        if response.status_code != 200:
            raise GoogleOAuthError("Google did not confirm token revocation")


def create_pkce_pair():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def create_oauth_state():
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    return state, state_hash
