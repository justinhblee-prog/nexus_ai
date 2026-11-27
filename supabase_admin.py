"""Server-only Supabase admin REST adapter for OAuth private RPCs.

This module requires a legacy service_role JWT in server-side environment
configuration. It must never be imported by browser code or return the key.
"""
from __future__ import annotations

import base64
import json
import os
import re
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
    "claim_next_shorts_job",
    "heartbeat_shorts_job",
    "finish_shorts_job",
    "claim_next_approved_shorts_job",
    "heartbeat_shorts_upload_job",
    "record_shorts_upload_video_id",
    "finish_shorts_upload",
    "list_account_deletion_storage_objects",
    "list_account_deletion_active_leases",
    "mark_account_deletion_tombstone",
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

    def claim_next_approved_shorts_job(self, worker_id, lease_seconds=600, max_attempts=2, daily_limit=3):
        rows = self.rpc("claim_next_approved_shorts_job", {
            "p_worker_id": worker_id,
            "p_lease_seconds": lease_seconds,
            "p_max_attempts": max_attempts,
            "p_daily_limit": daily_limit,
        }) or []
        return rows[0] if rows else None

    def heartbeat_shorts_upload_job(self, job_id, lease_token, lease_seconds=600):
        return self.rpc("heartbeat_shorts_upload_job", {
            "p_job_id": job_id,
            "p_lease_token": lease_token,
            "p_lease_seconds": lease_seconds,
        })

    def record_shorts_upload_video_id(self, job_id, lease_token, video_id, channel_id, privacy_status):
        return self.rpc("record_shorts_upload_video_id", {
            "p_job_id": job_id,
            "p_lease_token": lease_token,
            "p_provider_video_id": video_id,
            "p_verified_channel_id": channel_id,
            "p_privacy_status": privacy_status,
        })

    def finish_shorts_upload(self, job_id, lease_token, success, video_id=None, error=None, max_attempts=2):
        return self.rpc("finish_shorts_upload", {
            "p_job_id": job_id,
            "p_lease_token": lease_token,
            "p_success": success,
            "p_provider_video_id": video_id,
            "p_error": error,
            "p_max_attempts": max_attempts,
        })

    def download_storage_object(self, storage_key):
        if not re.fullmatch(r"wsp_[0-9a-fA-F-]{36}/[0-9a-fA-F-]{36}/[0-9a-f]{32}\.mp4", storage_key):
            raise ValueError("Storage key is invalid")
        url_path = quote(storage_key, safe="/")
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
        }
        try:
            response = self.http_request(
                "GET",
                f"{self.base_url}/storage/v1/object/authenticated/nexus-shorts/{url_path}",
                headers=headers,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise SupabaseAdminError("Supabase private media download is temporarily unavailable") from exc
        if response.status_code != 200:
            raise SupabaseAdminError("Private render media could not be downloaded", response.status_code if 400 <= response.status_code < 500 else 502)
        return response.content

    def claim_next_shorts_job(self, worker_id, lease_seconds=600, max_attempts=3):
        rows = self.rpc("claim_next_shorts_job", {
            "p_worker_id": worker_id,
            "p_lease_seconds": lease_seconds,
            "p_max_attempts": max_attempts,
        }) or []
        return rows[0] if rows else None

    def heartbeat_shorts_job(self, job_id, lease_token, lease_seconds=600):
        return self.rpc("heartbeat_shorts_job", {
            "p_job_id": job_id,
            "p_lease_token": lease_token,
            "p_lease_seconds": lease_seconds,
        })

    def finish_shorts_job(
        self, job_id, lease_token, success, output_storage_key=None,
        title=None, script=None, error=None, max_attempts=3,
    ):
        return self.rpc("finish_shorts_job", {
            "p_job_id": job_id,
            "p_lease_token": lease_token,
            "p_success": success,
            "p_output_storage_key": output_storage_key,
            "p_title": title,
            "p_script": script,
            "p_error": error,
            "p_max_attempts": max_attempts,
        })

    def upload_storage_object(self, storage_key, content, content_type="video/mp4"):
        if not re.fullmatch(r"wsp_[0-9a-fA-F-]{36}/[0-9a-fA-F-]{36}/[0-9a-f]{32}\.mp4", storage_key):
            raise ValueError("Storage key is invalid")
        url_path = quote(storage_key, safe="/")
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        }
        try:
            response = self.http_request(
                "POST",
                f"{self.base_url}/storage/v1/object/nexus-shorts/{url_path}",
                data=content,
                headers=headers,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise SupabaseAdminError("Supabase media storage is temporarily unavailable") from exc
        if response.status_code not in (200, 201):
            raise SupabaseAdminError("Rendered media could not be stored", response.status_code if 400 <= response.status_code < 500 else 502)
        return storage_key

    def get_job_creator(self, job_id, workspace_id):
        rows = self._call(
            "GET",
            "shorts_jobs",
            params={
                "select": "created_by",
                "job_id": f"eq.{job_id}",
                "workspace_id": f"eq.{workspace_id}",
                "limit": "1",
            },
        ) or []
        return rows[0]["created_by"] if rows else None

    def delete_asset(self, storage_key):
        return self._call(
            "DELETE",
            "shorts_assets",
            params={"storage_key": f"eq.{storage_key}"},
            prefer="return=minimal",
        )

    def create_signed_url(self, storage_key, expires_in=300):
        if not re.fullmatch(r"wsp_[0-9a-fA-F-]{36}/[0-9a-fA-F-]{36}/[0-9a-f]{32}\.mp4", storage_key):
            raise ValueError("Storage key is invalid")
        path = quote(storage_key, safe="/")
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self.http_request(
                "POST",
                f"{self.base_url}/storage/v1/object/sign/nexus-shorts/{path}",
                json={"expiresIn": max(60, min(900, int(expires_in)))},
                headers=headers,
                timeout=8,
            )
        except requests.RequestException as exc:
            raise SupabaseAdminError("Supabase signed media service is temporarily unavailable") from exc
        if response.status_code not in (200, 201):
            raise SupabaseAdminError("Private media preview could not be created", response.status_code if 400 <= response.status_code < 500 else 502)
        try:
            signed = response.json().get("signedURL")
        except ValueError as exc:
            raise SupabaseAdminError("Supabase returned an invalid signed media URL") from exc
        if not isinstance(signed, str) or not signed:
            raise SupabaseAdminError("Supabase did not return a signed media URL")
        if signed.startswith("https://"):
            return signed
        return f"{self.base_url}/storage/v1" + (signed if signed.startswith("/") else "/" + signed)

    def delete_storage_object(self, storage_key):
        if not re.fullmatch(r"wsp_[0-9a-fA-F-]{36}/[0-9a-fA-F-]{36}/[0-9a-f]{32}\.mp4", storage_key):
            raise ValueError("Storage key is invalid")
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self.http_request(
                "DELETE",
                f"{self.base_url}/storage/v1/object/nexus-shorts",
                json={"prefixes": [storage_key]},
                headers=headers,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise SupabaseAdminError("Supabase media cleanup is temporarily unavailable") from exc
        if response.status_code not in (200, 204):
            raise SupabaseAdminError("Supabase media cleanup failed", response.status_code if 400 <= response.status_code < 500 else 502)
        return True


    def mark_account_deletion_tombstone(self, user_id):
        """Persist an identity tombstone before revoking sessions and deleting Auth."""
        value = str(user_id)
        if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value):
            raise ValueError("User ID is invalid")
        return self.rpc("mark_account_deletion_tombstone", {
            "p_user_id": value,
        })

    def list_account_deletion_storage_objects(self, user_id, limit=1000, offset=0):
        """List Storage objects owned by one verified account via a service-only RPC."""
        value = str(user_id)
        if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value):
            raise ValueError("User ID is invalid")
        rows = self.rpc("list_account_deletion_storage_objects", {
            "p_user_id": value,
            "p_limit": max(1, min(int(limit), 1000)),
            "p_offset": max(0, int(offset)),
        }) or []
        return rows

    def list_account_deletion_active_leases(self, workspace_ids):
        """List unexpired render/upload leases for workspaces scheduled for deletion."""
        ids = [str(value) for value in workspace_ids]
        if len(ids) > 100 or any(not re.fullmatch(r"wsp_[0-9a-fA-F-]{36}", value) for value in ids):
            raise ValueError("Workspace lease inventory request is invalid")
        return self.rpc("list_account_deletion_active_leases", {
            "p_workspace_ids": ids,
        }) or []

    def delete_storage_object_in_bucket(self, bucket_id, object_name):
        """Delete one exact object through the Storage API, never storage.objects SQL."""
        if bucket_id not in {"acs-assets", "acs-gallery", "acs-outputs", "nexus-shorts"}:
            raise ValueError("Storage bucket is not an approved NEXUS bucket")
        if (
            not isinstance(object_name, str)
            or not object_name
            or len(object_name) > 1024
            or object_name.startswith("/")
            or any(part in {"", ".", ".."} for part in object_name.split("/"))
            or chr(92) in object_name
        ):
            raise ValueError("Storage object path is invalid")
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self.http_request(
                "DELETE",
                f"{self.base_url}/storage/v1/object/{quote(bucket_id, safe='')}",
                json={"prefixes": [object_name]},
                headers=headers,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise SupabaseAdminError("Supabase account media cleanup is temporarily unavailable") from exc
        if response.status_code not in (200, 204):
            raise SupabaseAdminError("Supabase account media cleanup failed", response.status_code if 400 <= response.status_code < 500 else 502)
        return True

    def revoke_user_sessions(self, access_token):
        """Revoke all refresh sessions using the authenticated user's own token."""
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("A verified user access token is required")
        try:
            response = self.http_request(
                "POST",
                f"{self.base_url}/auth/v1/logout",
                params={"scope": "global"},
                headers={
                    "apikey": self.service_key,
                    "Authorization": f"Bearer {access_token.strip()}",
                },
                timeout=12,
            )
        except requests.RequestException as exc:
            raise SupabaseAdminError("Supabase session revocation is temporarily unavailable") from exc
        if response.status_code not in (200, 204):
            raise SupabaseAdminError("Supabase sessions could not be revoked", response.status_code if 400 <= response.status_code < 500 else 502)
        return True

    def delete_auth_user(self, user_id):
        """Delete a Supabase Auth user after all external cleanup is verified."""
        value = str(user_id)
        if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value):
            raise ValueError("User ID is invalid")
        try:
            response = self.http_request(
                "DELETE",
                f"{self.base_url}/auth/v1/admin/users/{quote(value, safe='')}",
                headers={
                    "apikey": self.service_key,
                    "Authorization": f"Bearer {self.service_key}",
                    "Accept": "application/json",
                },
                timeout=12,
            )
        except requests.RequestException as exc:
            raise SupabaseAdminError("Supabase Auth account deletion is temporarily unavailable") from exc
        if response.status_code not in (200, 204):
            raise SupabaseAdminError("Supabase Auth account deletion failed", response.status_code if 400 <= response.status_code < 500 else 502)
        return True

    def create_asset(self, payload):
        return self._call(
            "POST",
            "shorts_assets",
            payload=payload,
            prefer="return=representation",
        ) or []

    def list_youtube_connections_for_workspaces(self, workspace_ids):
        """List workspace-scoped YouTube connection metadata, never token material."""
        ids = [str(value) for value in workspace_ids]
        if len(ids) > 100 or any(not re.fullmatch(r"wsp_[0-9a-fA-F-]{36}", value) for value in ids):
            raise ValueError("Workspace connection inventory request is invalid")
        if not ids:
            return []
        return self._call(
            "GET",
            "youtube_connections",
            params={
                "select": "connection_id,workspace_id,provider,provider_account_id,status",
                "workspace_id": "in.(" + ",".join(ids) + ")",
                "provider": "eq.youtube",
                "order": "created_at.asc",
            },
        ) or []

    def has_active_connection_outside_workspaces(self, provider_account_id, workspace_ids):
        """Check whether a provider grant is still used outside workspaces being deleted."""
        ids = [str(value) for value in workspace_ids]
        if len(ids) > 100 or any(not re.fullmatch(r"wsp_[0-9a-fA-F-]{36}", value) for value in ids):
            raise ValueError("Workspace connection inventory request is invalid")
        if not provider_account_id:
            return False
        params = {
            "select": "connection_id",
            "provider": "eq.youtube",
            "provider_account_id": f"eq.{provider_account_id}",
            "status": "eq.connected",
            "limit": "1",
        }
        if ids:
            params["workspace_id"] = "not.in.(" + ",".join(ids) + ")"
        rows = self._call("GET", "youtube_connections", params=params) or []
        return bool(rows)

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
