"""Minimal Supabase PostgREST client that always uses the verified end-user JWT.

No service-role or secret key is loaded by this module. Database RLS remains the
source of truth for workspace access and role permissions.
"""
from __future__ import annotations

import os
import re
from typing import Mapping
from urllib.parse import quote

import requests

from hosted_auth import public_auth_config


class SupabaseRestError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.public_message = message


_ALLOWED_RPCS = {"transfer_workspace_ownership", "is_account_deletion_tombstoned"}


_ALLOWED_TABLES = {
    "workspaces",
    "workspace_members",
    "youtube_connections",
    "shorts_channels",
    "shorts_jobs",
    "shorts_job_events",
    "shorts_analytics_snapshots",
    "shorts_assets",
}


class SupabaseRestClient:
    def __init__(
        self,
        access_token: str,
        env: Mapping[str, str] | None = None,
        http_request=None,
    ):
        if not access_token or not access_token.strip():
            raise ValueError("A verified user access token is required")
        values = os.environ if env is None else env
        config = public_auth_config(values)
        self.base_url = config["supabase_url"].rstrip("/")
        self.publishable_key = config["publishable_key"]
        self.access_token = access_token.strip()
        self.http_request = http_request or requests.request

    def _request(self, method: str, table: str, params=None, payload=None):
        if table not in _ALLOWED_TABLES:
            raise ValueError("Unsupported Supabase table")
        url = f"{self.base_url}/rest/v1/{quote(table, safe='')}"
        headers = {
            "apikey": self.publishable_key,
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
            headers["Prefer"] = "return=representation"
        try:
            response = self.http_request(
                method,
                url,
                params=params,
                json=payload,
                headers=headers,
                timeout=8,
            )
        except requests.RequestException as exc:
            raise SupabaseRestError(502, "Supabase data service is temporarily unavailable") from exc

        if response.status_code == 204:
            return None
        if not 200 <= response.status_code < 300:
            if response.status_code in (401, 403):
                message = "Workspace access denied by Supabase RLS"
            elif response.status_code == 404:
                message = "Requested workspace data was not found"
            elif response.status_code == 409:
                message = "Workspace data conflicts with an existing record"
            elif 400 <= response.status_code < 500:
                message = "Supabase rejected the workspace data request"
            else:
                message = "Supabase data service is temporarily unavailable"
            raise SupabaseRestError(response.status_code, message)
        try:
            return response.json()
        except ValueError:
            return None

    def select(self, table: str, params: dict):
        return self._request("GET", table, params=params)

    def count(self, table: str, params: dict) -> int:
        """Return an exact RLS-filtered row count without downloading row data."""
        if table not in _ALLOWED_TABLES:
            raise ValueError("Unsupported Supabase table")
        url = f"{self.base_url}/rest/v1/{quote(table, safe='')}"
        headers = {
            "apikey": self.publishable_key,
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Prefer": "count=exact",
            "Range-Unit": "items",
            "Range": "0-0",
        }
        try:
            response = self.http_request(
                "HEAD",
                url,
                params=params,
                headers=headers,
                timeout=8,
            )
        except requests.RequestException as exc:
            raise SupabaseRestError(502, "Supabase data service is temporarily unavailable") from exc
        if not 200 <= response.status_code < 300:
            if response.status_code in (401, 403):
                message = "Workspace access denied by Supabase RLS"
            elif response.status_code == 404:
                message = "Requested workspace data was not found"
            elif 400 <= response.status_code < 500:
                message = "Supabase rejected the workspace data request"
            else:
                message = "Supabase data service is temporarily unavailable"
            raise SupabaseRestError(response.status_code, message)
        content_range = response.headers.get("Content-Range") or response.headers.get("content-range") or ""
        match = re.fullmatch(r"(?:\d+-\d+|\*)/(\d+|\*)", content_range.strip())
        if not match or match.group(1) == "*":
            raise SupabaseRestError(502, "Supabase did not return an exact row count")
        return int(match.group(1))

    def insert(self, table: str, payload: dict):
        return self._request("POST", table, payload=payload)

    def update(self, table: str, params: dict, payload: dict):
        return self._request("PATCH", table, params=params, payload=payload)


    def rpc(self, name: str, payload: dict):
        if name not in _ALLOWED_RPCS:
            raise ValueError("Unsupported Supabase RPC")
        url = f"{self.base_url}/rest/v1/rpc/{quote(name, safe='')}"
        headers = {
            "apikey": self.publishable_key,
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            response = self.http_request(
                "POST",
                url,
                json=payload,
                headers=headers,
                timeout=8,
            )
        except requests.RequestException as exc:
            raise SupabaseRestError(502, "Supabase data service is temporarily unavailable") from exc
        if response.status_code == 204:
            return None
        if not 200 <= response.status_code < 300:
            if response.status_code in (401, 403):
                message = "Workspace access denied by Supabase RLS"
            elif response.status_code == 404:
                message = "Requested workspace operation was not found"
            elif response.status_code == 409:
                message = "Workspace operation conflicts with current membership"
            elif 400 <= response.status_code < 500:
                message = "Supabase rejected the workspace operation"
            else:
                message = "Supabase data service is temporarily unavailable"
            raise SupabaseRestError(response.status_code, message)
        try:
            return response.json()
        except ValueError:
            return None
