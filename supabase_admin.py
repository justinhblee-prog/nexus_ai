"""Server-only Supabase admin REST adapter for OAuth private RPCs.

This module requires a legacy service_role JWT in server-side environment
configuration. It must never be imported by browser code or return the key.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Mapping
from urllib.parse import quote

import requests


class SupabaseAdminError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


_ALLOWED_RPCS = {
    "store_youtube_oauth_state",
    "consume_youtube_oauth_state",
    "upsert_youtube_oauth_credential",
    "get_youtube_oauth_credential",
    "delete_youtube_oauth_credential",
}


def _is_service_role_jwt(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 3:
        return False
    try:
        payload = parts[1] + ("=" * (-len(parts[1]) % 4))
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return isinstance(claims, dict) and claims.get("role") == "service_role"
    except Exception:
        return False


class SupabaseAdminRestClient:
    def __init__(self, env: Mapping[str, str] | None = None, http_request=None):
        values = os.environ if env is None else env
        self.base_url = values.get("NEXUS_SUPABASE_URL", "").strip().rstrip("/")
        self.service_key = values.get("NEXUS_SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not self.base_url.startswith("https://") or not self.service_key:
            raise SupabaseAdminError("Server-side Supabase admin configuration is missing", 503)
        if not _is_service_role_jwt(self.service_key):
            raise SupabaseAdminError("NEXUS_SUPABASE_SERVICE_ROLE_KEY must be a service_role JWT", 503)
        self.http_request = http_request or requests.request

    def _call(self, method: str, path: str, params=None, payload=None, prefer=None):
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        try:
            response = self.http_request(
                method,
                f"{self.base_url}/rest/v1/{path}",
                params=params,
                json=payload,
                headers=headers,
                timeout=8,
            )
        except requests.RequestException as exc:
            raise SupabaseAdminError("Supabase admin service is temporarily unavailable") from exc
        if response.status_code == 204:
            return None
        if not 200 <= response.status_code < 300:
            raise SupabaseAdminError("Supabase admin operation failed", response.status_code if 400 <= response.status_code < 500 else 502)
        try:
            return response.json()
        except ValueError:
            return None

    def rpc(self, name: str, payload: dict):
        if name not in _ALLOWED_RPCS:
            raise ValueError("Unsupported Supabase admin RPC")
        return self._call("POST", f"rpc/{quote(name, safe='')}", payload=payload)

    def store_oauth_state(self, state_hash, user_id, workspace_id, redirect_uri, return_uri, code_verifier, expires_at):
        return self.rpc("store_youtube_oauth_state", {
            "p_state_hash": state_hash,
            "p_user_id": user_id,
            "p_workspace_id": workspace_id,
            "p_provider": "youtube",
            "p_redirect_uri": redirect_uri,
            "p_return_uri": return_uri,
            "p_code_verifier": code_verifier,
            "p_expires_at": expires_at,
        })

    def consume_oauth_state(self, state_hash):
        rows = self.rpc("consume_youtube_oauth_state", {"p_state_hash": state_hash}) or []
        return rows[0] if rows else None

    def upsert_connection(self, payload):
        return self._call(
            "POST",
            "youtube_connections",
            params={"on_conflict": "workspace_id,provider,provider_account_id"},
            payload=payload,
            prefer="resolution=merge-duplicates,return=representation",
        ) or []

    def upsert_channel(self, payload):
        return self._call(
            "POST",
            "shorts_channels",
            params={"on_conflict": "workspace_id,platform,provider_channel_id"},
            payload=payload,
            prefer="resolution=merge-duplicates,return=representation",
        ) or []

    def update_channels(self, workspace_id, connection_id, payload):
        return self._call(
            "PATCH",
            "shorts_channels",
            params={"workspace_id": f"eq.{workspace_id}", "connection_id": f"eq.{connection_id}"},
            payload=payload,
            prefer="return=representation",
        ) or []

    def has_other_active_connections(self, provider_account_id, connection_id):
        rows = self._call(
            "GET",
            "youtube_connections",
            params={
                "select": "connection_id",
                "provider": "eq.youtube",
                "provider_account_id": f"eq.{provider_account_id}",
                "status": "eq.connected",
                "connection_id": f"neq.{connection_id}",
                "limit": "1",
            },
        ) or []
        return bool(rows)

    def update_connection(self, connection_id, workspace_id, payload):
        return self._call(
            "PATCH",
            "youtube_connections",
            params={"connection_id": f"eq.{connection_id}", "workspace_id": f"eq.{workspace_id}"},
            payload=payload,
            prefer="return=representation",
        ) or []

    def upsert_credential(self, connection_id, workspace_id, ciphertext_hex, key_version, scopes, expires_at):
        return self.rpc("upsert_youtube_oauth_credential", {
            "p_connection_id": connection_id,
            "p_workspace_id": workspace_id,
            "p_encrypted_refresh_token": "\\x" + ciphertext_hex,
            "p_encryption_key_version": key_version,
            "p_scopes": scopes,
            "p_token_expires_at": expires_at,
        })

    def get_credential(self, connection_id):
        rows = self.rpc("get_youtube_oauth_credential", {"p_connection_id": connection_id}) or []
        if not rows:
            return None
        row = rows[0]
        value = row.get("encrypted_refresh_token", "")
        if isinstance(value, str) and value.startswith("\\x"):
            row["encrypted_refresh_token_hex"] = value[2:]
        elif isinstance(value, str):
            row["encrypted_refresh_token_hex"] = value
        else:
            row["encrypted_refresh_token_hex"] = bytes(value).hex()
        row.pop("encrypted_refresh_token", None)
        return row

    def delete_credential(self, connection_id):
        return self.rpc("delete_youtube_oauth_credential", {"p_connection_id": connection_id})
