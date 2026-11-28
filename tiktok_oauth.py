"""Server-side TikTok Login Kit OAuth v2 adapter for NEXUS social accounts."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import urlencode, urlparse

import requests


TIKTOK_SCOPES = ("user.info.basic",)


class TikTokOAuthError(RuntimeError):
    pass


class TikTokOAuthReauthRequired(TikTokOAuthError):
    pass


@dataclass(frozen=True)
class TikTokOAuthConfig:
    client_key: str
    client_secret: str
    redirect_uri: str
    app_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None):
        values = os.environ if env is None else env
        client_key = values.get("NEXUS_TIKTOK_CLIENT_KEY", "").strip()
        client_secret = values.get("NEXUS_TIKTOK_CLIENT_SECRET", "").strip()
        redirect_uri = values.get("NEXUS_TIKTOK_OAUTH_REDIRECT_URI", "").strip()
        app_url = values.get("NEXUS_HOSTED_APP_URL", "").strip().rstrip("/")
        if not client_key or not client_secret:
            raise TikTokOAuthError("TikTok Login Kit credentials are missing")
        if not redirect_uri.startswith("https://") or not app_url.startswith("https://"):
            raise TikTokOAuthError("TikTok OAuth callback and hosted app URLs must use HTTPS")
        parsed_redirect = urlparse(redirect_uri)
        if parsed_redirect.path != "/api/hosted/tiktok/callback" or parsed_redirect.query or parsed_redirect.fragment:
            raise TikTokOAuthError("TikTok redirect URI must be the exact NEXUS callback endpoint")
        parsed_app = urlparse(app_url)
        if parsed_app.path or parsed_app.query or parsed_app.fragment:
            raise TikTokOAuthError("NEXUS_HOSTED_APP_URL must be an origin without a path")
        return cls(client_key, client_secret, redirect_uri, app_url)

    def authorization_url(self, state: str) -> str:
        params = {
            "client_key": self.client_key,
            "response_type": "code",
            "scope": ",".join(TIKTOK_SCOPES),
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(params)

    @staticmethod
    def _json_response(response, action: str) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise TikTokOAuthError(f"TikTok returned an invalid {action} response") from exc
        if not isinstance(payload, dict):
            raise TikTokOAuthError(f"TikTok returned an invalid {action} response")
        return payload

    def exchange_code(self, code: str, http_post: Callable = requests.post) -> dict:
        if not isinstance(code, str) or not code.strip():
            raise TikTokOAuthError("TikTok authorization code is missing")
        try:
            response = http_post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={
                    "client_key": self.client_key,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise TikTokOAuthError("TikTok token service is temporarily unavailable") from exc
        payload = self._json_response(response, "token")
        if response.status_code != 200 or payload.get("error"):
            if payload.get("error") == "invalid_grant":
                raise TikTokOAuthReauthRequired("TikTok authorization code is expired or already used")
            raise TikTokOAuthError("TikTok rejected the OAuth authorization code")
        if not payload.get("access_token") or not payload.get("refresh_token") or not payload.get("open_id"):
            raise TikTokOAuthError("TikTok token response is missing required credentials")
        return payload

    def fetch_account(self, access_token: str, http_get: Callable = requests.get) -> dict:
        try:
            response = http_get(
                "https://open.tiktokapis.com/v2/user/info/",
                params={"fields": "open_id,display_name,avatar_url"},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise TikTokOAuthError("TikTok user profile service is temporarily unavailable") from exc
        payload = self._json_response(response, "profile")
        error = payload.get("error") or {}
        user = (payload.get("data") or {}).get("user") or {}
        if response.status_code != 200 or (error and error.get("code") not in (None, "ok")):
            raise TikTokOAuthError("TikTok account identity could not be verified")
        if not user.get("open_id"):
            raise TikTokOAuthError("TikTok account subject is missing")
        return {
            "account_id": user["open_id"],
            "display_name": user.get("display_name") or "TikTok account",
            "avatar_url": user.get("avatar_url") or "",
        }

    def refresh_access_token(self, refresh_token: str, http_post: Callable = requests.post) -> dict:
        try:
            response = http_post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data={
                    "client_key": self.client_key,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise TikTokOAuthError("TikTok token refresh service is temporarily unavailable") from exc
        payload = self._json_response(response, "refresh")
        if response.status_code != 200 or payload.get("error"):
            if payload.get("error") == "invalid_grant":
                raise TikTokOAuthReauthRequired("TikTok refresh token requires reauthorization")
            raise TikTokOAuthError("TikTok rejected the stored refresh token")
        if not payload.get("access_token"):
            raise TikTokOAuthError("TikTok did not return a refreshed access token")
        return payload

    def revoke_access_token(self, access_token: str, http_post: Callable = requests.post) -> None:
        try:
            response = http_post(
                "https://open.tiktokapis.com/v2/oauth/revoke/",
                data={
                    "client_key": self.client_key,
                    "client_secret": self.client_secret,
                    "token": access_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
                timeout=10,
            )
        except requests.RequestException as exc:
            raise TikTokOAuthError("TikTok token revocation service is temporarily unavailable") from exc
        if response.status_code != 200:
            raise TikTokOAuthError("TikTok did not confirm token revocation")
