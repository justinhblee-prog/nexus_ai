import os, time, sqlite3, threading, logging, hmac, hashlib, secrets, re
from datetime import date, datetime, timezone, timedelta
from uuid import UUID
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from types import SimpleNamespace
from hosted_auth import (
    HostedAuthConfigurationError, HostedAuthError, extract_bearer_token,
    is_hosted_auth_enabled, public_auth_config, verify_access_token,
)
# Vercel's hosted ASGI runtime does not render local media or run the local
# analytics/radar workers. Avoid importing MoviePy, Google client libraries,
# and local schedulers on every serverless cold start.
if is_hosted_auth_enabled():
    trend_radar = SimpleNamespace(
        DB_PATH=os.getenv("NEXUS_TREND_RADAR_DB_PATH", "data/studio_data.db")
    )
else:
    import video_maker, trend_radar, youtube_analytics, yt_uploader
from audit_log import safe_record_event as record_event, list_events, get_ops_metrics
from video_qa import validate_video
from script_templates import split_manual_script
from review_workflow import claim_upload, upload_result_stage
from supabase_rest import SupabaseRestClient, SupabaseRestError
from supabase_admin import SupabaseAdminRestClient, SupabaseAdminError
from hosted_trend_store import read_shared_trends
from social_platforms import get_social_platform_catalog
from youtube_oauth import GoogleOAuthConfig, GoogleOAuthError, create_oauth_state, create_pkce_pair
from tiktok_oauth import TikTokOAuthConfig, TikTokOAuthError, TikTokOAuthReauthRequired
from token_vault import encrypt_refresh_token, decrypt_refresh_token, TokenVaultError

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("nexus.api")


class OAuthCallbackLogFilter(logging.Filter):
    """Redact authorization code and state query strings from access logs."""
    def filter(self, record):
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            target = args[2]
            if isinstance(target, str) and target.startswith(("/api/hosted/youtube/callback", "/api/hosted/tiktok/callback")):
                redacted = list(args)
                redacted[2] = record.args[2].split("?", 1)[0] + "?[REDACTED]"
                record.args = tuple(redacted)
        return True


logging.getLogger("uvicorn.access").addFilter(OAuthCallbackLogFilter())

app = FastAPI(title="NEXUS STUDIO PRO API")
# Browser sessions are signed server-side and stored in HttpOnly cookies.
API_PASSWORD = os.getenv('NEXUS_API_PASSWORD', '')
SESSION_SECRET = os.getenv('NEXUS_SESSION_SECRET', '')
SESSION_COOKIE_NAME = 'nexus_session'
SESSION_TTL_SECONDS = 12 * 60 * 60

def auth_is_configured() -> bool:
    return len(API_PASSWORD) >= 12 and len(SESSION_SECRET) >= 32


def auth_is_required() -> bool:
    """Authentication is opt-in for loopback-only local deployments."""
    configured = os.getenv("NEXUS_AUTH_ENABLED", "false")
    return configured.strip().lower() in ("1", "true", "yes", "on")

def create_session_cookie(now: int | None = None) -> str:
    if not auth_is_configured():
        raise RuntimeError('API session secrets are not configured')
    issued = int(time.time() if now is None else now)
    payload = f'{issued + SESSION_TTL_SECONDS}.{secrets.token_urlsafe(18)}'
    signature = hmac.new(SESSION_SECRET.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'{payload}.{signature}'

def verify_session_cookie(cookie: str | None, now: int | None = None) -> bool:
    if not auth_is_configured() or not cookie:
        return False
    try:
        expires_text, nonce, signature = cookie.split('.', 2)
        expires = int(expires_text)
        current = int(time.time() if now is None else now)
        if expires <= current or expires > current + SESSION_TTL_SECONDS + 60 or not nonce:
            return False
        payload = f'{expires_text}.{nonce}'
        expected = hmac.new(SESSION_SECRET.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (TypeError, ValueError):
        return False

# The compose file binds host ports to loopback; CORS is limited to local UI origins.
LOCAL_UI_ORIGINS = {
    # Container-internal defaults (8502/8503) and isolated host-published ports.
    "http://127.0.0.1:8502", "http://localhost:8502",
    "http://127.0.0.1:8503", "http://localhost:8503",
    "http://127.0.0.1:28502", "http://localhost:28502",
    "http://127.0.0.1:28503", "http://localhost:28503",
}
HOSTED_UI_ORIGINS = {
    item.strip().rstrip("/")
    for item in os.getenv("NEXUS_CORS_ALLOWED_ORIGINS", "").split(",")
    if item.strip()
}
ALLOWED_UI_ORIGINS = LOCAL_UI_ORIGINS | HOSTED_UI_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ALLOWED_UI_ORIGINS),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

@app.middleware("http")
async def enforce_local_origin_and_session(request, call_next):
    origin = request.headers.get("origin")
    request_origin = f"{request.url.scheme}://{request.url.netloc}"
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in ALLOWED_UI_ORIGINS and origin != request_origin:
        return JSONResponse(status_code=403, content={"detail": "Cross-origin mutation rejected"})
    path = request.url.path
    if is_hosted_auth_enabled():
        if path in {"/api/hosted/auth-config", "/api/session/status"} and request.method == "GET":
            return await call_next(request)
        if path in {"/api/hosted/youtube/callback", "/api/hosted/tiktok/callback"} and request.method == "GET":
            return await call_next(request)
        if path.startswith("/api/hosted/"):
            try:
                token = extract_bearer_token(request.headers.get("authorization"))
                request.state.hosted_user = verify_access_token(token)
                request.state.hosted_access_token = token
                tombstone_client = SupabaseRestClient(token)
                request.state.account_deletion_tombstoned = bool(
                    tombstone_client.rpc("is_account_deletion_tombstoned", {})
                )
                if request.state.account_deletion_tombstoned:
                    # Only the existing deletion request may be retried, and only
                    # to finish session revocation; no other API remains available.
                    if not (path == "/api/hosted/account/deletion/request" and request.method == "POST"):
                        return JSONResponse(status_code=401, content={"detail": "This account is no longer active"})
            except SupabaseRestError:
                return JSONResponse(status_code=503, content={"detail": "Account status could not be verified safely"})
            except HostedAuthConfigurationError as exc:
                return JSONResponse(status_code=503, content={"detail": str(exc)})
            except HostedAuthError:
                return JSONResponse(status_code=401, content={"detail": "Valid Supabase bearer token required"})
            return await call_next(request)
        if path.startswith("/api/") or path.startswith("/output/"):
            return JSONResponse(
                status_code=503,
                content={"detail": "Hosted tenant-scoped API is not enabled for this route yet"},
            )
    public_paths = {
        "/api/session/status", "/api/session/login", "/api/session/logout",
        "/api/hosted/auth-config",
    }
    protected = (path.startswith("/api/") and path not in public_paths) or path.startswith("/output/")
    if protected and auth_is_required():
        if not auth_is_configured():
            return JSONResponse(status_code=503, content={"detail": "Set NEXUS_API_PASSWORD and NEXUS_SESSION_SECRET to enable API authentication."})
        if not verify_session_cookie(request.cookies.get(SESSION_COOKIE_NAME)):
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})
    return await call_next(request)

@app.get("/signup")
def signup_page():
    """Serve the hosted account registration and login experience."""
    return FileResponse("signup.html", media_type="text/html; charset=utf-8")


@app.get("/api/hosted/auth-config")
def hosted_auth_configuration():
    """Expose only the Supabase URL and publishable key required by browser auth."""
    try:
        return public_auth_config()
    except HostedAuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/hosted/session")
def hosted_session(request: Request):
    """Return the identity verified by the hosted-auth middleware."""
    user = getattr(request.state, "hosted_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Valid Supabase bearer token required")
    return {"authenticated": True, "user": user}


class HostedAccountDeletionReq(BaseModel):
    confirmation: str = Field(pattern="^DELETE MY ACCOUNT$")

    class Config:
        extra = "forbid"


class WorkspaceMemberRoleUpdateReq(BaseModel):
    role: str = Field(pattern="^(admin|editor|viewer)$")

    class Config:
        extra = "forbid"


class WorkspaceOwnershipTransferReq(BaseModel):
    new_owner_id: UUID

    class Config:
        extra = "forbid"


class HostedTopicQueueCreateReq(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    source: str = Field(default="manual", pattern="^(manual|trend_radar)$", max_length=40)
    region: str = Field(default="", max_length=12)
    source_name: str = Field(default="", max_length=120)
    source_url: str | None = Field(default=None, max_length=2048)

    class Config:
        extra = "forbid"


class HostedJobCreateReq(BaseModel):
    channel_id: UUID
    topic: str = Field(min_length=1, max_length=300)
    title: str = Field(default="", max_length=200)
    script: str = Field(default="", max_length=12000)

    class Config:
        extra = "forbid"


def _hosted_rest_client(request: Request) -> SupabaseRestClient:
    token = getattr(request.state, "hosted_access_token", None)
    user = getattr(request.state, "hosted_user", None)
    if not token or not user:
        raise HTTPException(status_code=401, detail="Valid Supabase bearer token required")
    try:
        return SupabaseRestClient(token)
    except HostedAuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _hosted_rest_error(exc: SupabaseRestError):
    status = exc.status_code if 400 <= exc.status_code < 500 else 502
    raise HTTPException(status_code=status, detail=exc.public_message) from exc


def _validate_workspace_id(workspace_id: str):
    if not re.fullmatch(r"wsp_[0-9a-fA-F-]{36}", workspace_id or ""):
        raise HTTPException(status_code=404, detail="Workspace not found")


@app.get("/api/hosted/workspaces")
def hosted_workspaces(request: Request):
    client = _hosted_rest_client(request)
    try:
        items = client.select("workspaces", {
            "select": "workspace_id,workspace_name,owner_id,created_at",
            "order": "created_at.asc",
        }) or []
        memberships = client.select("workspace_members", {
            "select": "workspace_id,role",
            "user_id": f"eq.{request.state.hosted_user['user_id']}",
        }) or []
        roles = {item["workspace_id"]: item["role"] for item in memberships}
        for item in items:
            item["member_role"] = roles.get(item["workspace_id"])
        return {"items": items}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.patch("/api/hosted/workspaces/{workspace_id}/members/{member_id}/role")
def hosted_update_workspace_member_role(
    workspace_id: str,
    member_id: UUID,
    req: WorkspaceMemberRoleUpdateReq,
    request: Request,
):
    """Allow only the current owner to promote or change a non-owner member role."""
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user_id = request.state.hosted_user["user_id"]
    if str(member_id) == str(user_id):
        raise HTTPException(status_code=400, detail="The current owner role cannot be changed here")
    try:
        own_membership = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        }) or []
        if not own_membership or own_membership[0].get("role") != "owner":
            raise HTTPException(status_code=403, detail="Workspace owner permission required")
        target = client.select("workspace_members", {
            "select": "user_id",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{member_id}",
            "limit": "1",
        }) or []
        if not target:
            raise HTTPException(status_code=404, detail="Workspace member not found")
        updated = client.update("workspace_members", {
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{member_id}",
        }, {"role": req.role}) or []
        return {"updated": bool(updated), "user_id": str(member_id), "role": req.role}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.post("/api/hosted/workspaces/{workspace_id}/transfer-ownership")
def hosted_transfer_workspace_ownership(
    workspace_id: str,
    req: WorkspaceOwnershipTransferReq,
    request: Request,
):
    """Transfer ownership to an existing admin before the current owner deletes their account."""
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    try:
        client.rpc("transfer_workspace_ownership", {
            "p_workspace_id": workspace_id,
            "p_new_owner_id": str(req.new_owner_id),
        })
        return {"transferred": True, "workspace_id": workspace_id}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.get("/api/hosted/workspaces/{workspace_id}/members")
def hosted_workspace_members(workspace_id: str, request: Request):
    """List workspace members only for the verified workspace owner."""
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user_id = request.state.hosted_user["user_id"]
    try:
        own_membership = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        }) or []
        if not own_membership or own_membership[0].get("role") != "owner":
            raise HTTPException(status_code=403, detail="Workspace owner permission required")
        items = client.select("workspace_members", {
            "select": "user_id,role,created_at",
            "workspace_id": f"eq.{workspace_id}",
            "order": "created_at.asc",
        }) or []
        return {"items": items}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


def has_recent_password_reauthentication(user, now=None, max_age_seconds=600):
    current = time.time() if now is None else now
    entries = user.get("amr") if isinstance(user, dict) else None
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("method") != "password":
            continue
        timestamp = entry.get("timestamp")
        if (
            isinstance(timestamp, (int, float))
            and not isinstance(timestamp, bool)
            and current - max_age_seconds <= timestamp <= current + 30
        ):
            return True
    return False


def account_deletion_is_enabled():
    return (
        os.getenv("NEXUS_ACCOUNT_DELETION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        and os.getenv("NEXUS_ACCOUNT_DELETION_WORKER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        and is_hosted_auth_enabled()
    )


@app.get("/api/hosted/account/deletion/preflight")
def hosted_account_deletion_preflight(request: Request):
    """Report workspace and Storage blockers without starting destructive cleanup."""
    client = _hosted_rest_client(request)
    user_id = request.state.hosted_user["user_id"]
    try:
        memberships = client.select("workspace_members", {
            "select": "workspace_id,role",
            "user_id": f"eq.{user_id}",
            "order": "created_at.asc",
        }) or []
        owned_workspaces = client.select("workspaces", {
            "select": "workspace_id,workspace_name,owner_id",
            "owner_id": f"eq.{user_id}",
            "order": "created_at.asc",
        }) or []
        membership_by_workspace = {row["workspace_id"]: row for row in memberships}
        workspace_ids = list(dict.fromkeys(
            [row["workspace_id"] for row in memberships]
            + [row["workspace_id"] for row in owned_workspaces]
        ))
        blockers = []
        summaries = []
        shared_workspace_ids = set()
        if len(workspace_ids) > 100:
            return {
                "ownership_clear": False,
                "storage_clear": False,
                "preflight_clear": False,
                "workspaces": [],
                "owned_workspaces": [],
                "active_worker_lease_count": 0,
                "youtube_oauth": {},
                "storage": {},
                "blockers": [{"reason": "This account has more than 100 workspace memberships; support-assisted cleanup is required."}],
                "account_deletion_enabled": False,
                "account_deletion_worker_online": False,
                "account_deletion_reason": "Workspace inventory exceeds the safe automated deletion limit.",
            }
        for wid in workspace_ids:
            membership = membership_by_workspace.get(wid, {"role": "owner"})
            workspace_rows = client.select("workspaces", {
                "select": "workspace_id,workspace_name,owner_id",
                "workspace_id": f"eq.{wid}",
                "limit": "1",
            }) or []
            if not workspace_rows:
                continue
            workspace = workspace_rows[0]
            members = client.select("workspace_members", {
                "select": "user_id,role",
                "workspace_id": f"eq.{wid}",
            }) or []
            others = [member for member in members if member.get("user_id") != user_id]
            is_owner = workspace.get("owner_id") == user_id
            if is_owner and (
                wid not in membership_by_workspace
                or membership_by_workspace[wid].get("role") != "owner"
            ):
                blockers.append({
                    "workspace_id": wid,
                    "reason": "Workspace ownership and membership records do not match; resolve this before deletion.",
                })
            if not is_owner and membership.get("role") == "owner":
                blockers.append({
                    "workspace_id": wid,
                    "reason": "Workspace owner and membership records do not match; resolve this before deletion.",
                })
            if others or not is_owner:
                # Non-owners can only see their own membership row under RLS;
                # treat those workspaces as shared rather than guessing member count.
                shared_workspace_ids.add(wid)
            summary = {
                "workspace_id": wid,
                "workspace_name": workspace.get("workspace_name") or "My Workspace",
                "member_count": len(members) if is_owner else None,
                "role": membership.get("role"),
                "owned_by_current_user": is_owner,
                "transfer_ready": is_owner and any(member.get("role") == "admin" for member in others),
            }
            summaries.append(summary)
            if is_owner and others:
                if not summary["transfer_ready"]:
                    blockers.append({
                        "workspace_id": wid,
                        "reason": "Promote another workspace member to admin before transferring ownership.",
                    })
                else:
                    blockers.append({
                        "workspace_id": wid,
                        "reason": "Transfer workspace ownership to an existing admin before account deletion.",
                    })

        deletion_workspace_ids = [
            item["workspace_id"] for item in summaries
            if item["owned_by_current_user"] and item["member_count"] <= 1
        ]
        admin = SupabaseAdminRestClient()
        worker_online = account_deletion_is_enabled() and admin.is_account_deletion_worker_online()
        active_leases = admin.list_account_deletion_active_leases(deletion_workspace_ids)
        if active_leases:
            blockers.append({
                "reason": "Wait for active render or upload workers to finish before deleting a workspace.",
                "active_lease_count": len(active_leases),
                "latest_lease_expiry": max(item["lease_until"] for item in active_leases),
            })
        storage_objects = []
        offset = 0
        while True:
            page = admin.list_account_deletion_storage_objects(user_id, limit=1000, offset=offset, workspace_ids=deletion_workspace_ids)
            storage_objects.extend(page)
            if len(page) < 1000:
                break
            offset += len(page)
        personal_gallery_images = admin.list_account_personal_gallery_images(user_id)
        personal_gallery_keys = {
            key for item in personal_gallery_images
            for key in (item.get("storage_key"), item.get("thumbnail_key"))
            if key
        }
        connections = admin.list_social_connections_for_workspaces(deletion_workspace_ids)
        credential_cleanup_count = len(connections)
        provider_grants_to_revoke = 0
        shared_provider_grants_preserved = 0
        seen_provider_accounts = set()
        for connection in connections:
            if connection.get("status") != "connected":
                continue
            provider = connection.get("provider") or "youtube"
            provider_account_id = connection.get("provider_account_id")
            provider_key = (provider, provider_account_id)
            if not provider_account_id or provider_key in seen_provider_accounts:
                continue
            seen_provider_accounts.add(provider_key)
            if admin.has_active_connection_outside_workspaces(
                provider_account_id,
                deletion_workspace_ids,
                provider=provider,
            ):
                shared_provider_grants_preserved += 1
            else:
                provider_grants_to_revoke += 1
                if not admin.get_credential(str(connection.get("connection_id"))):
                    blockers.append({
                        "reason": f"A connected {provider} account has no stored refresh credential to revoke safely.",
                        "connection_id": connection.get("connection_id"),
                    })
        bucket_counts = {}
        shared_storage_count = 0
        unclassified_storage_count = 0
        user_owned_storage_count = 0
        buckets_by_name = {}
        allowed_storage_buckets = {"acs-assets", "acs-gallery", "acs-outputs", "nexus-shorts"}
        for obj in storage_objects:
            object_name = obj.get("name") or ""
            buckets_by_name.setdefault(object_name, set()).add(obj.get("bucket_id"))
            if obj.get("bucket_id") not in allowed_storage_buckets:
                blockers.append({
                    "reason": "An account Storage object uses an unsupported bucket and requires safe mapping.",
                    "bucket_id": obj.get("bucket_id") or "unknown",
                })
        if any(len(values) > 1 for values in buckets_by_name.values()):
            blockers.append({"reason": "Storage contains duplicate object paths across buckets; resolve the ambiguity before deletion."})
        for obj in storage_objects:
            bucket = obj.get("bucket_id") or "unknown"
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            if obj.get("owner") == user_id or obj.get("owner_id") == user_id:
                user_owned_storage_count += 1
            workspace_prefix = (obj.get("name") or "").split("/", 1)[0]
            if workspace_prefix in shared_workspace_ids:
                shared_storage_count += 1
            elif workspace_prefix not in deletion_workspace_ids and obj.get("name") not in personal_gallery_keys:
                unclassified_storage_count += 1
        if shared_storage_count:
            blockers.append({
                "reason": "Some Storage objects owned by this account belong to shared workspaces. Re-upload or safely transfer those files before deleting the account.",
                "storage_object_count": shared_storage_count,
            })
        if unclassified_storage_count:
            blockers.append({
                "reason": "Some account-owned Storage objects cannot be mapped safely to a workspace. Map or remove them before account deletion.",
                "storage_object_count": unclassified_storage_count,
            })
        return {
            "ownership_clear": not any(item.get("workspace_id") for item in blockers),
            "storage_clear": shared_storage_count == 0 and unclassified_storage_count == 0,
            "preflight_clear": not blockers,
            "workspaces": summaries,
            "owned_workspaces": [item for item in summaries if item["owned_by_current_user"]],
            "active_worker_lease_count": len(active_leases),
            "youtube_oauth": {
                "workspace_connections_to_clean": credential_cleanup_count,
                "provider_grants_to_revoke": provider_grants_to_revoke,
                "provider_grants_preserved_for_other_workspaces": shared_provider_grants_preserved,
            },
            "storage": {
                "cleanup_candidate_object_count": len(storage_objects),
                "account_owned_object_count": user_owned_storage_count,
                "personal_gallery_image_count": len(personal_gallery_images),
                "unclassified_object_blockers": unclassified_storage_count,
                "objects_by_bucket": bucket_counts,
                "shared_workspace_object_blockers": shared_storage_count,
            },
            "blockers": blockers,
            "account_deletion_enabled": worker_online,
            "account_deletion_worker_online": worker_online,
            "account_deletion_reason": None if worker_online else "The hosted account deletion API and a live cleanup worker must both be enabled after the reviewed migration is applied and free-tier service configuration is verified.",
        }
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)
    except SupabaseAdminError as exc:
        raise HTTPException(status_code=503, detail="Account deletion preflight could not verify Storage ownership safely") from exc

@app.post("/api/hosted/account/deletion/request")
def hosted_account_deletion_request(req: HostedAccountDeletionReq, request: Request):
    """Queue an explicitly confirmed deletion only after fresh authentication."""
    if not account_deletion_is_enabled():
        raise HTTPException(status_code=503, detail="Account deletion is not enabled for this deployment")
    user = request.state.hosted_user
    if not has_recent_password_reauthentication(user):
        raise HTTPException(status_code=403, detail="Fresh password sign-in is required before account deletion")

    user_id = user["user_id"]
    try:
        admin = SupabaseAdminRestClient()
        if getattr(request.state, "account_deletion_tombstoned", False):
            # A prior request already passed preflight and atomically created both
            # tombstone and queue row. Do not rerun preflight: active leases or
            # changed membership visibility must not strand session revocation.
            queued = admin.get_account_deletion_request(user_id)
            if not queued:
                raise SupabaseAdminError("Existing tombstone has no verifiable deletion request")
        else:
            preflight = hosted_account_deletion_preflight(request)
            if not preflight.get("account_deletion_enabled"):
                raise HTTPException(status_code=503, detail="The account deletion worker is not online; no deletion request was queued")
            if not preflight.get("preflight_clear"):
                raise HTTPException(status_code=409, detail={
                    "message": "Resolve account deletion blockers before confirming deletion",
                    "blockers": preflight.get("blockers", []),
                })
            queued = admin.enqueue_account_deletion(user_id, {
                "preflight_clear": True,
                "workspace_ids": [item["workspace_id"] for item in preflight.get("workspaces", [])],
                "requested_at": datetime.now(timezone.utc).isoformat(),
            })
            if not queued:
                raise SupabaseAdminError("Account deletion queue did not return a durable request")
        if not queued.get("sessions_revoked"):
            admin.revoke_user_sessions(request.state.hosted_access_token)
            if not admin.mark_account_deletion_sessions_revoked(user_id):
                raise SupabaseAdminError("Account deletion session revocation state could not be persisted")
        return {
            "status": queued.get("status", "pending"),
            "phase": queued.get("phase", "queued"),
            "message": "Deletion request is durably queued. Cleanup will run asynchronously and can be retried safely.",
        }
    except SupabaseAdminError as exc:
        raise HTTPException(
            status_code=503,
            detail="The deletion request is safely retained, but session revocation or queue verification needs retry. Submit the same confirmation again.",
        ) from exc


@app.get("/api/hosted/workspaces/{workspace_id}/channels")
def hosted_workspace_channels(workspace_id: str, request: Request):
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    try:
        items = client.select("shorts_channels", {
            "select": "channel_id,platform,provider_channel_id,display_name,persona,is_active,created_at,updated_at",
            "workspace_id": f"eq.{workspace_id}",
            "order": "created_at.desc",
        })
        return {"items": items or []}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.get("/api/hosted/workspaces/{workspace_id}/jobs")
def hosted_workspace_jobs(
    workspace_id: str,
    request: Request,
    limit: int = 50,
    offset: int = 0,
):
    _validate_workspace_id(workspace_id)
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(status_code=422, detail="Invalid jobs pagination")
    client = _hosted_rest_client(request)
    try:
        # Fetch one extra row to determine whether another page exists without
        # requiring a separate count query or exposing rows outside this tenant.
        rows = client.select("shorts_jobs", {
            "select": "job_id,channel_id,topic,title,script,stage,approval_status,privacy_status,output_storage_key,created_at,updated_at",
            "workspace_id": f"eq.{workspace_id}",
            "order": "created_at.desc,job_id.desc",
            "limit": str(limit + 1),
            "offset": str(offset),
        }) or []
        has_more = len(rows) > limit
        items = rows[:limit]
        for item in items:
            item["has_preview"] = bool(item.pop("output_storage_key", None))
        return {
            "items": items,
            "has_more": has_more,
            "next_offset": offset + len(items) if has_more else None,
        }
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.get("/api/hosted/workspaces/{workspace_id}/topic-queue")
def hosted_topic_queue_list(workspace_id: str, request: Request):
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user_id = request.state.hosted_user["user_id"]
    try:
        items = client.select("shorts_topic_queue", {
            "select": "topic_id,topic,source,region,source_name,source_url,created_at",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user_id}",
            "order": "created_at.desc,topic_id.desc",
            "limit": "50",
        }) or []
        return {"items": items, "storage": "server"}
    except SupabaseRestError as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=503,
                detail="서버 저장형 주제 큐의 데이터베이스 마이그레이션이 아직 적용되지 않았습니다.",
            ) from exc
        _hosted_rest_error(exc)


@app.post("/api/hosted/workspaces/{workspace_id}/topic-queue")
def hosted_topic_queue_add(
    workspace_id: str, req: HostedTopicQueueCreateReq, request: Request
):
    _validate_workspace_id(workspace_id)
    topic = " ".join(req.topic.split())
    if not topic:
        raise HTTPException(status_code=422, detail="Topic is required")
    source_url = req.source_url.strip() if req.source_url else None
    if source_url and not source_url.startswith("https://"):
        raise HTTPException(status_code=422, detail="Only HTTPS source URLs are accepted")
    user_id = request.state.hosted_user["user_id"]
    client = _hosted_rest_client(request)
    try:
        rows = client.insert("shorts_topic_queue", {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "topic": topic,
            "source": req.source.strip() or "manual",
            "region": req.region.strip(),
            "source_name": req.source_name.strip(),
            "source_url": source_url,
        }) or []
        if not rows:
            raise HTTPException(status_code=403, detail="Workspace topic queue write was denied")
        return {"item": rows[0], "storage": "server"}
    except SupabaseRestError as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=503,
                detail="서버 저장형 주제 큐의 데이터베이스 마이그레이션이 아직 적용되지 않았습니다.",
            ) from exc
        if exc.status_code == 409:
            raise HTTPException(status_code=409, detail="이미 저장된 주제입니다.") from exc
        _hosted_rest_error(exc)


@app.delete("/api/hosted/workspaces/{workspace_id}/topic-queue/{topic_id}")
def hosted_topic_queue_delete(workspace_id: str, topic_id: UUID, request: Request):
    _validate_workspace_id(workspace_id)
    user_id = request.state.hosted_user["user_id"]
    client = _hosted_rest_client(request)
    try:
        client.delete("shorts_topic_queue", {
            "topic_id": f"eq.{topic_id}",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user_id}",
        })
        return {"deleted": True}
    except SupabaseRestError as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=503,
                detail="서버 저장형 주제 큐의 데이터베이스 마이그레이션이 아직 적용되지 않았습니다.",
            ) from exc
        _hosted_rest_error(exc)


@app.get("/api/hosted/workspaces/{workspace_id}/overview")
def hosted_workspace_overview(workspace_id: str, request: Request):
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    try:
        workspace_filter = {"workspace_id": f"eq.{workspace_id}"}
        return {
            "workspace_id": workspace_id,
            # Exact counts are evaluated under the caller's JWT/RLS.
            # HEAD avoids downloading job rows and removes the previous 1,000-row cap.
            "channel_count": client.count("shorts_channels", workspace_filter),
            "active_channel_count": client.count(
                "shorts_channels", {**workspace_filter, "is_active": "eq.true"}
            ),
            "job_count": client.count("shorts_jobs", workspace_filter),
            "queued_count": client.count(
                "shorts_jobs", {**workspace_filter, "stage": "eq.queued"}
            ),
            "review_pending_count": client.count(
                "shorts_jobs", {**workspace_filter, "approval_status": "eq.pending"}
            ),
            "published_count": client.count(
                "shorts_jobs", {**workspace_filter, "stage": "eq.published"}
            ),
        }
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.get("/api/hosted/workspaces/{workspace_id}/trends")
def hosted_workspace_trends(workspace_id: str, request: Request):
    """Read shared public trend signals from Supabase after tenant membership verification."""
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    try:
        memberships = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{request.state.hosted_user['user_id']}",
            "limit": "1",
        }) or []
        if not memberships:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return read_shared_trends(client, limit=30)
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.get("/api/hosted/workspaces/{workspace_id}/analytics")
def hosted_workspace_analytics(workspace_id: str, request: Request, refresh: bool = False):
    """Return real YouTube Analytics metrics for connections owned by this workspace."""
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user = request.state.hosted_user
    try:
        memberships = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user['user_id']}",
            "limit": "1",
        }) or []
        if not memberships:
            raise HTTPException(status_code=404, detail="Workspace not found")

        connections = client.select("youtube_connections", {
            "select": "connection_id,display_name,status,scopes",
            "workspace_id": f"eq.{workspace_id}",
            "provider": "eq.youtube",
            "status": "eq.connected",
            "order": "created_at.asc",
        }) or []
        channels = client.select("shorts_channels", {
            "select": "channel_id,provider_channel_id,display_name,connection_id,is_active",
            "workspace_id": f"eq.{workspace_id}",
            "platform": "eq.youtube",
            "is_active": "eq.true",
            "order": "created_at.asc",
        }) or []

        today = date.today()
        end_date = today - timedelta(days=2)
        start_date = end_date - timedelta(days=27)
        start_text, end_text = start_date.isoformat(), end_date.isoformat()
        if not connections:
            return {
                "status": "not_connected", "period_days": 28,
                "period_start": start_text, "period_end": end_text,
                "views": None, "watch_minutes": None, "average_view_duration_seconds": None,
                "likes": None, "comments": None, "shares": None,
                "subscribers_gained": None, "subscribers_lost": None,
                "engagement_rate": None, "source": None, "updated_at": None,
                "channels": [], "note": "YouTube 계정을 연결하면 실제 Analytics 지표가 표시됩니다.",
            }

        admin = SupabaseAdminRestClient()
        config = GoogleOAuthConfig.from_env()
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        channel_results = []
        totals = {key: 0.0 for key in (
            "views", "watch_minutes", "likes", "comments", "shares",
            "subscribers_gained", "subscribers_lost",
        )}
        weighted_duration = 0.0
        total_views = 0.0
        subscribers = []
        for connection in connections:
            connection_id = str(connection["connection_id"])
            scopes = set(connection.get("scopes") or [])
            required_scopes = {
                "https://www.googleapis.com/auth/yt-analytics.readonly",
                "https://www.googleapis.com/auth/youtube.readonly",
            }
            if not required_scopes.issubset(scopes):
                channel_results.append({
                    "connection_id": connection_id,
                    "display_name": connection.get("display_name") or "YouTube",
                    "status": "scope_required",
                })
                continue
            credential = admin.get_credential(connection_id)
            if not credential:
                channel_results.append({
                    "connection_id": connection_id,
                    "display_name": connection.get("display_name") or "YouTube",
                    "status": "reauth_required",
                })
                continue
            refresh_token = decrypt_refresh_token(
                credential["encrypted_refresh_token_hex"],
                credential["encryption_key_version"],
            )
            credentials = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=config.client_id,
                client_secret=config.client_secret,
                scopes=sorted(required_scopes),
            )
            try:
                credentials.refresh(GoogleRequest())
                analytics = build("youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False)
                youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
                report = analytics.reports().query(
                    ids="channel==MINE",
                    startDate=start_text,
                    endDate=end_text,
                    metrics="views,estimatedMinutesWatched,averageViewDuration,likes,comments,shares,subscribersGained,subscribersLost",
                ).execute()
                headers = [item.get("name") for item in report.get("columnHeaders", [])]
                row = (report.get("rows") or [[]])[0]
                values = dict(zip(headers, row))
                stats_response = youtube.channels().list(part="statistics", mine=True).execute()
                stats_items = stats_response.get("items") or []
                stats = (stats_items[0].get("statistics") or {}) if stats_items else {}
                metric = {
                    "views": int(float(values.get("views") or 0)),
                    "watch_minutes": float(values.get("estimatedMinutesWatched") or 0),
                    "average_view_duration_seconds": float(values.get("averageViewDuration") or 0),
                    "likes": int(float(values.get("likes") or 0)),
                    "comments": int(float(values.get("comments") or 0)),
                    "shares": int(float(values.get("shares") or 0)),
                    "subscribers_gained": int(float(values.get("subscribersGained") or 0)),
                    "subscribers_lost": int(float(values.get("subscribersLost") or 0)),
                    "subscriber_count": None if stats.get("hiddenSubscriberCount", False) else int(stats.get("subscriberCount") or 0),
                }
                for key in totals:
                    totals[key] += metric[key]
                weighted_duration += metric["average_view_duration_seconds"] * metric["views"]
                total_views += metric["views"]
                if metric["subscriber_count"] is not None:
                    subscribers.append(metric["subscriber_count"])
                channel_results.append({
                    "connection_id": connection_id,
                    "display_name": connection.get("display_name") or "YouTube",
                    "status": "connected",
                    **metric,
                })
            except Exception as exc:
                logger.warning("Hosted YouTube Analytics query failed (%s)", type(exc).__name__)
                channel_results.append({
                    "connection_id": connection_id,
                    "display_name": connection.get("display_name") or "YouTube",
                    "status": "error",
                    "error_type": type(exc).__name__,
                })

        connected_count = sum(1 for item in channel_results if item["status"] == "connected")
        failed_count = len(channel_results) - connected_count
        if not connected_count:
            status = "scope_required" if any(x["status"] == "scope_required" for x in channel_results) else "error"
            return {
                "status": status, "period_days": 28,
                "period_start": start_text, "period_end": end_text,
                "views": None, "watch_minutes": None, "average_view_duration_seconds": None,
                "likes": None, "comments": None, "shares": None,
                "subscribers_gained": None, "subscribers_lost": None,
                "engagement_rate": None, "subscriber_count": None,
                "source": None, "updated_at": None, "channels": channel_results,
                "note": "Analytics 권한을 확인하거나 YouTube 계정을 다시 연결해 주세요. 실제 수치는 추정하지 않습니다.",
            }
        engagement = (totals["likes"] + totals["comments"] + totals["shares"]) / total_views * 100 if total_views else 0.0
        return {
            "status": "partial" if failed_count else "connected",
            "period_days": 28,
            "period_start": start_text,
            "period_end": end_text,
            **totals,
            "average_view_duration_seconds": weighted_duration / total_views if total_views else 0.0,
            "subscriber_count": sum(subscribers) if subscribers else None,
            "engagement_rate": engagement,
            "source": "YouTube Analytics API",
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "channels": channel_results,
            "note": "실제 YouTube Analytics API의 최근 완료된 28일 데이터입니다. 예상치나 샘플 수치는 포함하지 않습니다.",
        }
    except HTTPException:
        raise
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)
    except (GoogleOAuthError, SupabaseAdminError, TokenVaultError) as exc:
        logger.warning("Hosted Analytics setup failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="YouTube Analytics를 안전하게 조회할 수 없습니다.") from exc


@app.post("/api/hosted/workspaces/{workspace_id}/jobs")
def hosted_create_job(workspace_id: str, req: HostedJobCreateReq, request: Request):
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user = request.state.hosted_user
    payload = {
        "workspace_id": workspace_id,
        "channel_id": str(req.channel_id),
        "created_by": user["user_id"],
        "topic": req.topic.strip(),
        "title": req.title.strip(),
        "script": req.script.strip(),
    }
    if not payload["topic"]:
        raise HTTPException(status_code=422, detail="Topic is required")
    try:
        rows = client.insert("shorts_jobs", payload) or []
        if not rows:
            raise HTTPException(status_code=403, detail="Workspace job creation was denied")
        return {"job": rows[0]}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.get("/api/hosted/workspaces/{workspace_id}/social/platforms")
def hosted_social_platforms(workspace_id: str, request: Request):
    """Return the provider catalogue and per-workspace connection counts."""
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user_id = request.state.hosted_user["user_id"]
    try:
        memberships = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        }) or []
        if not memberships:
            raise HTTPException(status_code=404, detail="Workspace not found")
        connections = client.select("youtube_connections", {
            "select": "provider,status",
            "workspace_id": f"eq.{workspace_id}",
        }) or []
        counts = {}
        for connection in connections:
            if connection.get("status") == "connected":
                provider = connection.get("provider")
                counts[provider] = counts.get(provider, 0) + 1
        items = get_social_platform_catalog()
        for item in items:
            item["connected_account_count"] = counts.get(item["id"], 0)
        return {"items": items}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.get("/api/hosted/workspaces/{workspace_id}/social/connections")
def hosted_social_connections(workspace_id: str, request: Request):
    """List all provider connections in the active workspace, not just YouTube."""
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user_id = request.state.hosted_user["user_id"]
    try:
        memberships = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        }) or []
        if not memberships:
            raise HTTPException(status_code=404, detail="Workspace not found")
        items = client.select("youtube_connections", {
            "select": "connection_id,provider,provider_account_id,display_name,status,scopes,created_at,updated_at,disconnected_at",
            "workspace_id": f"eq.{workspace_id}",
            "order": "created_at.desc",
        })
        return {"items": items or []}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.get("/api/hosted/workspaces/{workspace_id}/youtube/connections")
def hosted_youtube_connections(workspace_id: str, request: Request):
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    try:
        items = client.select("youtube_connections", {
            "select": "connection_id,provider,provider_account_id,display_name,status,scopes,created_at,updated_at,disconnected_at",
            "workspace_id": f"eq.{workspace_id}",
            "order": "created_at.desc",
        })
        return {"items": items or []}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


@app.post("/api/hosted/workspaces/{workspace_id}/youtube/connect")
def hosted_youtube_connect(workspace_id: str, request: Request):
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user = request.state.hosted_user
    try:
        memberships = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user['user_id']}",
        }) or []
        if not any(item.get("role") in {"owner", "admin"} for item in memberships):
            raise HTTPException(status_code=403, detail="Workspace owner or admin permission required")
        config = GoogleOAuthConfig.from_env()
        state, state_hash = create_oauth_state()
        verifier, challenge = create_pkce_pair()
        return_uri = f"{config.app_url}/signup"
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        admin = SupabaseAdminRestClient()
        admin.store_oauth_state(
            state_hash, user["user_id"], workspace_id, config.redirect_uri,
            return_uri, verifier, expires_at,
        )
        return {"authorization_url": config.authorization_url(state, challenge)}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)
    except (GoogleOAuthError, SupabaseAdminError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/hosted/workspaces/{workspace_id}/tiktok/connect")
def hosted_tiktok_connect(workspace_id: str, request: Request):
    """Start a server-side TikTok Login Kit flow for an owner/admin."""
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user = request.state.hosted_user
    try:
        memberships = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user['user_id']}",
            "limit": "1",
        }) or []
        if not any(item.get("role") in {"owner", "admin"} for item in memberships):
            raise HTTPException(status_code=403, detail="Workspace owner or admin permission required")
        config = TikTokOAuthConfig.from_env()
        state, state_hash = create_oauth_state()
        verifier, _challenge = create_pkce_pair()
        return_uri = f"{config.app_url}/signup"
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        SupabaseAdminRestClient().store_oauth_state(
            state_hash, user["user_id"], workspace_id, config.redirect_uri,
            return_uri, verifier, expires_at, provider="tiktok",
        )
        return {"authorization_url": config.authorization_url(state)}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)
    except (TikTokOAuthError, SupabaseAdminError) as exc:
        raise HTTPException(status_code=503, detail="TikTok OAuth is not configured") from exc


@app.get("/api/hosted/tiktok/callback")
def hosted_tiktok_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if not state:
        raise HTTPException(status_code=400, detail="OAuth state is required")
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    try:
        admin = SupabaseAdminRestClient()
        state_data = admin.consume_oauth_state(state_hash)
        if not state_data or state_data.get("provider") != "tiktok":
            raise HTTPException(status_code=400, detail="TikTok OAuth state is invalid, expired, or already consumed")
        config = TikTokOAuthConfig.from_env()
        expected_return_uri = f"{config.app_url}/signup"
        if state_data.get("redirect_uri") != config.redirect_uri or state_data.get("return_uri") != expected_return_uri:
            raise HTTPException(status_code=400, detail="TikTok OAuth redirect configuration mismatch")
        if error:
            logger.info("TikTok OAuth was not completed (%s)", str(error)[:64])
            return RedirectResponse(f"{expected_return_uri}?tiktok=denied", status_code=303)
        if not code:
            raise HTTPException(status_code=400, detail="TikTok authorization code is missing")

        memberships = admin.list_account_user_memberships(state_data["user_id"])
        if not any(
            row.get("workspace_id") == state_data["workspace_id"]
            and row.get("role") in {"owner", "admin"}
            for row in memberships
        ):
            raise HTTPException(status_code=403, detail="Workspace owner or admin permission is no longer available")

        token_data = config.exchange_code(code)
        account = config.fetch_account(token_data["access_token"])
        if account["account_id"] != token_data.get("open_id"):
            raise TikTokOAuthError("TikTok account identity did not match the token subject")
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise TikTokOAuthError("TikTok did not return a refresh token")
        encrypted = encrypt_refresh_token(refresh_token)
        scopes = [scope.strip() for scope in (token_data.get("scope") or "").split(",") if scope.strip()]
        refresh_expires_in = max(60, int(token_data.get("refresh_expires_in") or 15552000))
        token_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=refresh_expires_in)
        ).isoformat()

        memberships = admin.list_account_user_memberships(state_data["user_id"])
        if not any(
            row.get("workspace_id") == state_data["workspace_id"]
            and row.get("role") in {"owner", "admin"}
            for row in memberships
        ):
            raise HTTPException(status_code=403, detail="Workspace owner or admin permission is no longer available")

        connections = admin.upsert_connection({
            "workspace_id": state_data["workspace_id"],
            "provider": "tiktok",
            "provider_account_id": account["account_id"],
            "display_name": account.get("display_name") or "TikTok account",
            "status": "connected",
            "scopes": scopes,
            "connected_by": state_data["user_id"],
            "disconnected_at": None,
        })
        if not connections:
            raise SupabaseAdminError("TikTok connection metadata could not be saved")
        connection_id = connections[0]["connection_id"]
        try:
            admin.upsert_credential(
                connection_id, state_data["workspace_id"], encrypted["ciphertext_hex"],
                encrypted["key_version"], scopes, token_expires_at,
            )
            admin.upsert_channel({
                "workspace_id": state_data["workspace_id"],
                "connection_id": connection_id,
                "platform": "tiktok",
                "provider_channel_id": account["account_id"],
                "display_name": account.get("display_name") or "TikTok account",
                "created_by": state_data["user_id"],
            })
        except SupabaseAdminError:
            admin.update_connection(connection_id, state_data["workspace_id"], {
                "status": "reauth_required",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            raise
        return RedirectResponse(f"{expected_return_uri}?tiktok=connected", status_code=303)
    except HTTPException:
        raise
    except (TikTokOAuthError, SupabaseAdminError, TokenVaultError, ValueError) as exc:
        logger.warning("TikTok OAuth callback failed (%s)", type(exc).__name__)
        try:
            config = TikTokOAuthConfig.from_env()
            return RedirectResponse(f"{config.app_url}/signup?tiktok=error", status_code=303)
        except TikTokOAuthError:
            raise HTTPException(status_code=503, detail="TikTok OAuth is not configured") from exc


@app.post("/api/hosted/workspaces/{workspace_id}/tiktok/{connection_id}/disconnect")
def hosted_tiktok_disconnect(workspace_id: str, connection_id: UUID, request: Request):
    """Revoke a TikTok grant safely, preserving rotated refresh tokens for retries."""
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user = request.state.hosted_user
    try:
        memberships = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user['user_id']}",
            "limit": "1",
        }) or []
        if not any(item.get("role") in {"owner", "admin"} for item in memberships):
            raise HTTPException(status_code=403, detail="Workspace owner or admin permission required")
        connections = client.select("youtube_connections", {
            "select": "connection_id,status,provider,provider_account_id",
            "workspace_id": f"eq.{workspace_id}",
            "connection_id": f"eq.{connection_id}",
            "provider": "eq.tiktok",
        }) or []
        if not connections:
            raise HTTPException(status_code=404, detail="TikTok connection not found")
        admin = SupabaseAdminRestClient()
        connection_key = str(connection_id)
        credential = admin.get_credential(connection_key)
        revocation_state = admin.get_youtube_disconnect_state(connection_key)
        if credential:
            shared_grant = admin.has_other_active_connections(
                connections[0]["provider_account_id"], connection_key, provider="tiktok"
            )
            if shared_grant:
                saved = admin.set_youtube_disconnect_state(connection_key, "preserved")
                if saved != "preserved":
                    raise SupabaseAdminError("Shared TikTok grant preservation state was not persisted")
            elif revocation_state not in {"revoked", "preserved", "not_required"}:
                started = admin.set_youtube_disconnect_state(connection_key, "revocation_started")
                if started != "revocation_started":
                    raise SupabaseAdminError("TikTok token revocation intent was not durably recorded")
                refresh_token = decrypt_refresh_token(
                    credential["encrypted_refresh_token_hex"],
                    credential["encryption_key_version"],
                )
                config = TikTokOAuthConfig.from_env()
                token_data = config.refresh_access_token(refresh_token)
                rotated_refresh = token_data.get("refresh_token") or refresh_token
                encrypted = encrypt_refresh_token(rotated_refresh)
                refresh_expires_in = max(60, int(token_data.get("refresh_expires_in") or 15552000))
                admin.upsert_credential(
                    connection_key, workspace_id, encrypted["ciphertext_hex"],
                    encrypted["key_version"], token_data.get("scope", "").split(","),
                    (datetime.now(timezone.utc) + timedelta(seconds=refresh_expires_in)).isoformat(),
                )
                config.revoke_access_token(token_data["access_token"])
                completed = admin.set_youtube_disconnect_state(connection_key, "revoked")
                if completed != "revoked":
                    raise SupabaseAdminError("TikTok token revocation result was not durably recorded")
        elif revocation_state == "revocation_started":
            raise SupabaseAdminError("TikTok token revocation outcome is uncertain; credential retained for safe retry")
        elif revocation_state is None:
            saved = admin.set_youtube_disconnect_state(connection_key, "not_required")
            if saved != "not_required":
                raise SupabaseAdminError("No-token disconnect state was not durably recorded")
        updated = admin.update_connection(connection_key, workspace_id, {
            "status": "disconnected",
            "disconnected_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        if not updated:
            raise SupabaseAdminError("TikTok connection could not be updated")
        admin.update_channels(workspace_id, connection_key, {
            "is_active": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        admin.delete_credential(connection_key)
        return {"status": "disconnected", "connection_id": connection_key}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)
    except (TikTokOAuthError, SupabaseAdminError, TokenVaultError) as exc:
        raise HTTPException(status_code=502, detail="TikTok disconnection could not be completed safely") from exc


@app.get("/api/hosted/youtube/callback")
def hosted_youtube_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if not state:
        raise HTTPException(status_code=400, detail="OAuth state is required")
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    try:
        admin = SupabaseAdminRestClient()
        state_data = admin.consume_oauth_state(state_hash)
        if not state_data:
            raise HTTPException(status_code=400, detail="OAuth state is invalid, expired, or already consumed")
        config = GoogleOAuthConfig.from_env()
        expected_return_uri = f"{config.app_url}/signup"
        if state_data.get("redirect_uri") != config.redirect_uri or state_data.get("return_uri") != expected_return_uri:
            raise HTTPException(status_code=400, detail="OAuth redirect configuration mismatch")
        if error:
            return RedirectResponse(f"{expected_return_uri}?youtube=denied", status_code=303)
        if not code:
            raise HTTPException(status_code=400, detail="OAuth authorization code is missing")

        # OAuth may take several minutes. Re-check the initiating user's current
        # workspace role after the public callback returns; a previously valid
        # one-time state must not preserve admin rights after membership removal
        # or role downgrade.
        memberships = admin.list_account_user_memberships(state_data["user_id"])
        if not any(
            row.get("workspace_id") == state_data["workspace_id"]
            and row.get("role") in {"owner", "admin"}
            for row in memberships
        ):
            raise HTTPException(status_code=403, detail="Workspace owner or admin permission is no longer available")

        token_data = config.exchange_code(code, state_data["code_verifier"])
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            return RedirectResponse(f"{expected_return_uri}?youtube=reauth_required", status_code=303)
        account = config.fetch_account(token_data["access_token"])
        channels = config.fetch_channels(token_data["access_token"])
        encrypted = encrypt_refresh_token(refresh_token)
        scopes = (token_data.get("scope") or "").split()
        expires_in = max(60, int(token_data.get("expires_in") or 3600))
        token_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
        # Re-check immediately before privileged persistence as the Google round
        # trip may have outlived the initiator's workspace-admin membership.
        memberships = admin.list_account_user_memberships(state_data["user_id"])
        if not any(
            row.get("workspace_id") == state_data["workspace_id"]
            and row.get("role") in {"owner", "admin"}
            for row in memberships
        ):
            raise HTTPException(status_code=403, detail="Workspace owner or admin permission is no longer available")

        connections = admin.upsert_connection({
            "workspace_id": state_data["workspace_id"],
            "provider": "youtube",
            "provider_account_id": account["account_id"],
            "display_name": account.get("email") or account.get("name") or "Google account",
            "status": "connected",
            "scopes": scopes,
            "connected_by": state_data["user_id"],
            "disconnected_at": None,
        })
        if not connections:
            raise SupabaseAdminError("YouTube connection metadata could not be saved")
        connection_id = connections[0]["connection_id"]
        try:
            admin.upsert_credential(
                connection_id, state_data["workspace_id"], encrypted["ciphertext_hex"],
                encrypted["key_version"], scopes, token_expires_at,
            )
            for channel in channels:
                admin.upsert_channel({
                    "workspace_id": state_data["workspace_id"],
                    "connection_id": connection_id,
                    "platform": "youtube",
                    "provider_channel_id": channel["channel_id"],
                    "display_name": channel["title"],
                    "created_by": state_data["user_id"],
                })
        except SupabaseAdminError:
            admin.update_connection(connection_id, state_data["workspace_id"], {
                "status": "reauth_required",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            raise
        return RedirectResponse(f"{expected_return_uri}?youtube=connected", status_code=303)
    except HTTPException:
        raise
    except (GoogleOAuthError, SupabaseAdminError, TokenVaultError, ValueError) as exc:
        logger.warning("YouTube OAuth callback failed (%s)", type(exc).__name__)
        try:
            config = GoogleOAuthConfig.from_env()
            return RedirectResponse(f"{config.app_url}/signup?youtube=error", status_code=303)
        except GoogleOAuthError:
            raise HTTPException(status_code=503, detail="YouTube OAuth is not configured") from exc


@app.post("/api/hosted/workspaces/{workspace_id}/youtube/{connection_id}/disconnect")
def hosted_youtube_disconnect(workspace_id: str, connection_id: UUID, request: Request):
    _validate_workspace_id(workspace_id)
    client = _hosted_rest_client(request)
    user = request.state.hosted_user
    try:
        memberships = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{workspace_id}",
            "user_id": f"eq.{user['user_id']}",
        }) or []
        if not any(item.get("role") in {"owner", "admin"} for item in memberships):
            raise HTTPException(status_code=403, detail="Workspace owner or admin permission required")
        connections = client.select("youtube_connections", {
            "select": "connection_id,status,provider_account_id",
            "workspace_id": f"eq.{workspace_id}",
            "connection_id": f"eq.{connection_id}",
        }) or []
        if not connections:
            raise HTTPException(status_code=404, detail="YouTube connection not found")
        admin = SupabaseAdminRestClient()
        connection_key = str(connection_id)
        credential = admin.get_credential(connection_key)
        revocation_state = admin.get_youtube_disconnect_state(connection_key)
        if credential:
            shared_grant = admin.has_other_active_connections(
                connections[0]["provider_account_id"], connection_key
            )
            target_state = "preserved" if shared_grant else revocation_state
            if shared_grant:
                saved = admin.set_youtube_disconnect_state(connection_key, "preserved")
                if saved != "preserved":
                    raise SupabaseAdminError("Shared Google grant preservation state was not persisted")
            elif target_state not in {"revoked", "preserved", "not_required"}:
                started = admin.set_youtube_disconnect_state(connection_key, "revocation_started")
                if started != "revocation_started":
                    raise SupabaseAdminError("Google token revocation intent was not durably recorded")
                refresh_token = decrypt_refresh_token(
                    credential["encrypted_refresh_token_hex"],
                    credential["encryption_key_version"],
                )
                GoogleOAuthConfig.from_env().revoke_refresh_token(refresh_token)
                completed = admin.set_youtube_disconnect_state(connection_key, "revoked")
                if completed != "revoked":
                    raise SupabaseAdminError("Google token revocation result was not durably recorded")
        elif revocation_state == "revocation_started":
            raise SupabaseAdminError("Google token revocation outcome is uncertain; credential retained for safe retry")
        elif revocation_state is None:
            saved = admin.set_youtube_disconnect_state(connection_key, "not_required")
            if saved != "not_required":
                raise SupabaseAdminError("No-token disconnect state was not durably recorded")
        updated = admin.update_connection(str(connection_id), workspace_id, {
            "status": "disconnected",
            "disconnected_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        if not updated:
            raise SupabaseAdminError("YouTube connection could not be updated")
        admin.update_channels(workspace_id, str(connection_id), {
            "is_active": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        admin.delete_credential(str(connection_id))
        return {"status": "disconnected", "connection_id": str(connection_id)}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)
    except (GoogleOAuthError, SupabaseAdminError, TokenVaultError) as exc:
        raise HTTPException(status_code=502, detail="YouTube disconnection could not be completed safely") from exc


@app.get("/api/hosted/jobs/{job_id}/preview")
def hosted_job_preview(job_id: UUID, request: Request):
    client = _hosted_rest_client(request)
    try:
        rows = client.select("shorts_jobs", {
            "select": "job_id,workspace_id,output_storage_key",
            "job_id": f"eq.{job_id}",
            "limit": "1",
        }) or []
        if not rows or not rows[0].get("output_storage_key"):
            raise HTTPException(status_code=404, detail="Rendered preview is not available")
        signed_url = SupabaseAdminRestClient().create_signed_url(rows[0]["output_storage_key"], 300)
        return {"signed_url": signed_url, "expires_in": 300}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)
    except SupabaseAdminError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/hosted/jobs/{job_id}/approve")
def hosted_approve_job(job_id: UUID, request: Request):
    """Approve only a review-pending job in a workspace the caller administers."""
    client = _hosted_rest_client(request)
    user = request.state.hosted_user
    try:
        jobs = client.select("shorts_jobs", {
            "select": "job_id,workspace_id,stage,approval_status",
            "job_id": f"eq.{job_id}",
            "limit": "1",
        }) or []
        if not jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        job = jobs[0]
        if job.get("stage") != "review_pending" or job.get("approval_status") != "pending":
            raise HTTPException(status_code=409, detail="Only jobs awaiting final review can be approved")
        memberships = client.select("workspace_members", {
            "select": "role",
            "workspace_id": f"eq.{job['workspace_id']}",
            "user_id": f"eq.{user['user_id']}",
            "limit": "1",
        }) or []
        if not memberships or memberships[0].get("role") not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Workspace owner or admin permission required")
        payload = {
            "approval_status": "approved",
            "approved_by": user["user_id"],
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        rows = client.update("shorts_jobs", {
            "job_id": f"eq.{job_id}",
            "stage": "eq.review_pending",
            "approval_status": "eq.pending",
        }, payload) or []
        if not rows:
            raise HTTPException(status_code=409, detail="Job state changed before approval; refresh and review again")
        return {"job": rows[0]}
    except SupabaseRestError as exc:
        _hosted_rest_error(exc)


# Local filesystem output is used only by the desktop/loopback studio.
# Hosted Vercel requests use Supabase Storage and must not write to the read-only bundle.
if not is_hosted_auth_enabled():
    os.makedirs("export", exist_ok=True)
    os.makedirs("output", exist_ok=True)
    app.mount("/output", StaticFiles(directory="output"), name="output")

RADAR_INTERVAL_SEC = 300
AUTO_PRODUCE_ENABLED = True

def get_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect("data/studio_data.db", check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def init_app_db():
    """Create the core application tables without overwriting existing user data."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL DEFAULT 'YouTube',
            yt_id TEXT NOT NULL DEFAULT '',
            persona TEXT NOT NULL DEFAULT '전문가 톤',
            subs INTEGER NOT NULL DEFAULT 0,
            views INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS pipeline_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_name TEXT NOT NULL,
            title TEXT NOT NULL,
            script TEXT NOT NULL DEFAULT '',
            video_path TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL DEFAULT '최종컨펌 대기',
            youtube_video_id TEXT,
            privacy_status TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_created
            ON pipeline_jobs(id DESC);

        CREATE TABLE IF NOT EXISTS topic_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            channel_name TEXT,
            topic TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'api',
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at INTEGER NOT NULL,
            lease_until INTEGER,
            lease_token TEXT,
            title_override TEXT,
            script_override TEXT,
            target_job_id INTEGER,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_topic_queue_claim
            ON topic_queue(status, available_at, lease_until, id);
        CREATE TABLE IF NOT EXISTS scheduler_runs (
            schedule_key TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            lease_until INTEGER,
            lease_token TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auto_produced_topics (
            topic TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        );
    """)
    queue_columns = {row["name"] for row in db.execute("PRAGMA table_info(topic_queue)")}
    if "lease_token" not in queue_columns:
        db.execute("ALTER TABLE topic_queue ADD COLUMN lease_token TEXT")
    if "title_override" not in queue_columns:
        db.execute("ALTER TABLE topic_queue ADD COLUMN title_override TEXT")
    if "script_override" not in queue_columns:
        db.execute("ALTER TABLE topic_queue ADD COLUMN script_override TEXT")
    if "target_job_id" not in queue_columns:
        db.execute("ALTER TABLE topic_queue ADD COLUMN target_job_id INTEGER")
    scheduler_columns = {row["name"] for row in db.execute("PRAGMA table_info(scheduler_runs)")}
    if "lease_token" not in scheduler_columns:
        db.execute("ALTER TABLE scheduler_runs ADD COLUMN lease_token TEXT")
    pipeline_columns = {row["name"] for row in db.execute("PRAGMA table_info(pipeline_jobs)")}
    if "youtube_video_id" not in pipeline_columns:
        db.execute("ALTER TABLE pipeline_jobs ADD COLUMN youtube_video_id TEXT")
    if "privacy_status" not in pipeline_columns:
        db.execute("ALTER TABLE pipeline_jobs ADD COLUMN privacy_status TEXT")
    db.executescript("INSERT OR IGNORE INTO channels (name, platform, yt_id, persona) VALUES\n        ('Brain Glitch', 'YouTube', '', '심리 전문가 톤'),\n        ('Silent Signals', 'YouTube', '', '인간관계 전문가 톤'),\n        ('Unseen Truth', 'YouTube', '', '팩트체크 전문가 톤'),\n        ('Dark Files Global', 'YouTube', '', '미스터리 다큐 톤'),\n        ('99% Missed', 'YouTube', '', '생활 정보 전문가 톤'),\n        ('Money Glitch', 'YouTube', '', '경제 분석가 톤'),\n        ('Secret Vault 24', 'YouTube', '', '자산·습관 전문가 톤'),\n        ('Future Leak', 'YouTube', '', 'AI·기술 분석가 톤'),\n        ('30Sec Shift', 'YouTube', '', '건강 정보 전문가 톤'),\n        ('Why Nobody Tells', 'YouTube', '', '지식 큐레이터 톤');")
    db.commit()
    db.close()

def get_oa_key():
    db = get_db()
    try:
        r = db.execute("SELECT value FROM settings WHERE key='oa'").fetchone()
        return r["value"] if r else ""
    finally:
        db.close()

def run_make_video(ch_name: str, persona: str, topic: str, queue_id: int | None = None,
                   lease_token: str | None = None, script_override: str | None = None,
                   title_override: str | None = None, target_job_id: int | None = None):
    if not topic or not topic.strip():
        raise ValueError("topic must not be empty")
    if target_job_id is not None and queue_id is None:
        raise ValueError("target_job_id requires a claimed queue item")
    started = time.monotonic()
    record_event("render.started", entity_type="render", payload={"channel": ch_name, "topic_length": len(topic)})
    try:
        if script_override is None:
            mp4, title, script = video_maker.render_pro_short(ch_name, persona, topic, get_oa_key())
        else:
            mp4, title, script = video_maker.render_pro_short(
                ch_name, persona, topic, get_oa_key(),
                script_override=script_override, title_override=title_override,
            )
        qa = validate_video(mp4)
        record_event("qa.passed" if qa["ok"] else "qa.failed", entity_type="render",
                     payload={"channel": ch_name, "checks": qa["checks"], "errors": qa["errors"]})
        if not qa["ok"]:
            raise RuntimeError("Video QA failed: " + ", ".join(qa["errors"]))
        db = get_db()
        try:
            if queue_id is not None:
                if not lease_token:
                    raise RuntimeError("Queue lease token is required to commit a queued render")
                db.execute("BEGIN IMMEDIATE")
                lease = db.execute(
                    """SELECT topic, source, target_job_id FROM topic_queue
                       WHERE id=? AND status='running' AND lease_token=? AND lease_until>?""",
                    (queue_id, lease_token, int(time.time())),
                ).fetchone()
                if not lease:
                    db.rollback()
                    raise RuntimeError("Queue lease was lost before the render result could be committed")
            if target_job_id is not None:
                if lease["target_job_id"] != target_job_id:
                    db.rollback()
                    raise RuntimeError("Regeneration target does not match the claimed queue item")
                updated = db.execute(
                    """UPDATE pipeline_jobs SET title=?, script=?, video_path=?, stage='최종컨펌 대기',
                       youtube_video_id=NULL, privacy_status=NULL
                       WHERE id=? AND channel_name=? AND stage='재제작 대기'""",
                    (title, script, mp4, target_job_id, ch_name),
                )
                if updated.rowcount != 1:
                    db.rollback()
                    raise RuntimeError("Regeneration target is no longer awaiting a replacement render")
                job_id = target_job_id
            else:
                if queue_id is not None and lease["target_job_id"] is not None:
                    db.rollback()
                    raise RuntimeError("Queued regeneration target was not supplied to the renderer")
                cur = db.execute("INSERT INTO pipeline_jobs (channel_name, title, script, video_path, stage, created_at) VALUES (?,?,?,?,?,?)",
                                 (ch_name, title, script, mp4, "최종컨펌 대기", datetime.now().strftime("%Y-%m-%d %H:%M")))
                job_id = cur.lastrowid
            if queue_id is not None:
                finished = db.execute(
                    """UPDATE topic_queue SET status='completed', lease_until=NULL, lease_token=NULL,
                       last_error=NULL, updated_at=?
                       WHERE id=? AND status='running' AND lease_token=? AND lease_until>?""",
                    (datetime.now().isoformat(timespec="seconds"), queue_id, lease_token, int(time.time())),
                )
                if finished.rowcount != 1:
                    db.rollback()
                    raise RuntimeError("Queue lease ownership changed before render commit")
                if lease["source"] == "daily_radar":
                    db.execute(
                        "INSERT OR IGNORE INTO auto_produced_topics (topic, created_at) VALUES (?, ?)",
                        (lease["topic"], datetime.now().isoformat(timespec="seconds")),
                    )
            db.commit()
        finally:
            db.close()
        record_event("render.completed", entity_type="pipeline_job", entity_id=job_id,
                     payload={"channel": ch_name, "elapsed_seconds": round(time.monotonic() - started, 3)})
        if queue_id is not None:
            record_event("queue.completed", entity_type="topic_queue", entity_id=queue_id,
                         payload={"status": "completed", "pipeline_job_id": job_id})
        return job_id
    except Exception as exc:
        record_event("render.failed", entity_type="render",
                     payload={"channel": ch_name, "error_type": type(exc).__name__,
                              "elapsed_seconds": round(time.monotonic() - started, 3)})
        raise

def auto_produce_top_trends(count=3):
    """Queue fresh daily source-ranked picks durably; the queue worker performs the renders."""
    daily_scan = trend_radar.get_scan_status("daily")
    if not daily_scan or daily_scan.get("status") == "failed":
        return 0
    fresh_sources = sorted(
        name for name, details in (daily_scan.get("source_summary") or {}).items()
        if details.get("status") == "success"
    )
    if not fresh_sources:
        return 0
    radar_db = trend_radar.init_radar_db()
    radar_db.row_factory = sqlite3.Row
    try:
        channels = {row["name"]: row["persona"] for row in radar_db.execute("SELECT name, persona FROM channels")}
    finally:
        radar_db.close()

    db = get_db()
    try:
        produced = {row[0] for row in db.execute("SELECT topic FROM auto_produced_topics")}
        queued = {row[0] for row in db.execute(
            "SELECT topic FROM topic_queue WHERE source='daily_radar' AND status IN ('pending','running')"
        )}
    finally:
        db.close()

    # Source-local rank is comparable only within its own feed. Rotate by rank and region
    # rather than inventing a cross-source "viral" score or global top-ten.
    radar_db = trend_radar.init_radar_db()
    radar_db.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in fresh_sources)
        top_rows = [dict(row) for row in radar_db.execute(
            f"""SELECT * FROM trend_recommendations
                WHERE period_type='daily' AND source_name IN ({placeholders})
                ORDER BY source_rank ASC,
                  CASE region WHEN 'KR' THEN 0 WHEN 'US' THEN 1 WHEN 'JP' THEN 2 ELSE 3 END,
                  source_name ASC""",
            fresh_sources,
        ).fetchall()]
    finally:
        radar_db.close()

    date_key = datetime.now().strftime("%Y-%m-%d")
    queued_count = 0
    for trend in top_rows:
        if queued_count >= count:
            break
        topic = trend["topic"]
        channel = trend["matched_channel"]
        if topic in produced or topic in queued:
            continue
        if channel not in channels:
            logger.warning("Skipping trend with unknown channel: %s", channel)
            continue
        added = enqueue_topic(
            f"{channel} | {topic}",
            source="daily_radar",
            idempotency_key=f"daily-radar:{date_key}:{topic}",
        )
        if added:
            queued.add(topic)
            queued_count += 1
    return queued_count


def enqueue_topic(topic_line: str, source: str = "api", idempotency_key: str | None = None):
    """Persist one topic per channel so retries cannot duplicate earlier channel renders."""
    import uuid
    raw = topic_line.strip()
    if not raw:
        return 0
    channel_name = None
    topic = raw
    if "|" in raw:
        channel_name, topic = [part.strip() for part in raw.split("|", 1)]
        if not channel_name or not topic:
            raise ValueError("queue lines must be 'channel | topic' or 'topic'")
    db = get_db()
    try:
        # Serialize the active-topic check and insert to prevent concurrent double-enqueue.
        db.execute("BEGIN IMMEDIATE")
        if channel_name is None:
            channels = [row["name"] for row in db.execute("SELECT name FROM channels ORDER BY id")]
            if not channels:
                raise RuntimeError("No channels are configured")
        else:
            channels = [channel_name]
        now = int(time.time())
        stamp = datetime.now().isoformat(timespec="seconds")
        added = 0
        for name in channels:
            # Repeated UI clicks must not create concurrent copies of the same channel/topic.
            active = db.execute(
                """SELECT 1 FROM topic_queue
                   WHERE channel_name=? AND topic=? AND status IN ('pending', 'running')
                   LIMIT 1""",
                (name, topic),
            ).fetchone()
            if active:
                continue
            key = f"{idempotency_key or uuid.uuid4().hex}:{name}"
            cur = db.execute(
                """INSERT OR IGNORE INTO topic_queue
                   (idempotency_key, channel_name, topic, source, status, attempts,
                    available_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)""",
                (key, name, topic, source, now, stamp, stamp),
            )
            added += max(0, cur.rowcount)
        db.commit()
        if added:
            record_event("queue.enqueued", entity_type="topic_queue",
                         payload={"source": source, "channel_count": added})
        return added
    finally:
        db.close()

def claim_next_topic(lease_seconds: int = 900):
    """Atomically claim one pending or expired lease so concurrent workers cannot double-run it."""
    now = int(time.time())
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE pipeline_jobs SET stage='재제작 실패'
               WHERE stage='재제작 대기' AND id IN (
                   SELECT target_job_id FROM topic_queue
                   WHERE status='running' AND lease_until < ? AND attempts >= 3
                     AND target_job_id IS NOT NULL
               )""",
            (now,),
        )
        db.execute(
            """UPDATE topic_queue SET status='failed', lease_until=NULL, lease_token=NULL,
               last_error=COALESCE(last_error, 'Worker lease expired after maximum attempts'),
               updated_at=?
               WHERE status='running' AND lease_until < ? AND attempts >= 3""",
            (datetime.now().isoformat(timespec="seconds"), now),
        )
        row = db.execute(
            """SELECT * FROM topic_queue
               WHERE available_at <= ? AND attempts < 3
                 AND (status='pending' OR (status='running' AND lease_until < ?))
               ORDER BY id LIMIT 1""",
            (now, now),
        ).fetchone()
        if not row:
            db.commit()
            return None
        lease_token = secrets.token_urlsafe(24)
        db.execute(
            """UPDATE topic_queue SET status='running', attempts=attempts+1,
               lease_until=?, lease_token=?, updated_at=? WHERE id=?""",
            (now + lease_seconds, lease_token, datetime.now().isoformat(timespec="seconds"), row["id"]),
        )
        claimed = dict(row)
        claimed["attempts"] += 1
        claimed["lease_token"] = lease_token
        db.commit()
        record_event("queue.claimed", entity_type="topic_queue", entity_id=claimed["id"],
                     payload={"channel": claimed["channel_name"], "attempt": claimed["attempts"]})
        return claimed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def renew_topic_lease(queue_id: int, lease_token: str, lease_seconds: int = 900) -> bool:
    """Extend a running job only when the caller still owns an unexpired fencing token."""
    if not lease_token or lease_seconds < 1:
        return False
    db = get_db()
    try:
        now = int(time.time())
        cur = db.execute(
            """UPDATE topic_queue SET lease_until=?, updated_at=?
               WHERE id=? AND status='running' AND lease_token=? AND lease_until>?""",
            (now + lease_seconds, datetime.now().isoformat(timespec="seconds"),
             queue_id, lease_token, now),
        )
        db.commit()
        return cur.rowcount == 1
    finally:
        db.close()


def _topic_lease_heartbeat(queue_id: int, lease_token: str, stop_event: threading.Event,
                           lease_seconds: int = 900):
    interval = max(1, lease_seconds // 3)
    while not stop_event.wait(interval):
        try:
            if not renew_topic_lease(queue_id, lease_token, lease_seconds):
                logger.warning("Queue lease ownership lost for item %s", queue_id)
                return
        except Exception:
            logger.exception("Could not renew queue lease for item %s", queue_id)


def finish_topic(queue_id: int, lease_token: str, error: str | None = None, max_attempts: int = 3):
    """Finish only the current lease owner; stale workers cannot overwrite a newer attempt."""
    if not lease_token:
        return False
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT attempts, topic, source, target_job_id FROM topic_queue WHERE id=? AND status='running' AND lease_token=? AND lease_until>?",
            (queue_id, lease_token, int(time.time())),
        ).fetchone()
        if not row:
            db.rollback()
            return False
        now = int(time.time())
        stamp = datetime.now().isoformat(timespec="seconds")
        if error is None:
            db.execute(
                "UPDATE topic_queue SET status='completed', lease_until=NULL, lease_token=NULL, last_error=NULL, updated_at=? WHERE id=? AND lease_token=?",
                (stamp, queue_id, lease_token),
            )
        elif row["attempts"] >= max_attempts:
            db.execute(
                "UPDATE topic_queue SET status='failed', lease_until=NULL, lease_token=NULL, last_error=?, updated_at=? WHERE id=? AND lease_token=?",
                (error[:2000], stamp, queue_id, lease_token),
            )
            if row["target_job_id"] is not None:
                db.execute(
                    "UPDATE pipeline_jobs SET stage='재제작 실패' WHERE id=? AND stage='재제작 대기'",
                    (row["target_job_id"],),
                )
        else:
            delay = min(3600, 30 * (2 ** max(0, row["attempts"] - 1)))
            db.execute(
                """UPDATE topic_queue SET status='pending', lease_until=NULL, lease_token=NULL,
                   available_at=?, last_error=?, updated_at=? WHERE id=? AND lease_token=?""",
                (now + delay, error[:2000], stamp, queue_id, lease_token),
            )
        if error is None and row["source"] == "daily_radar":
            db.execute(
                "INSERT OR IGNORE INTO auto_produced_topics (topic, created_at) VALUES (?, ?)",
                (row["topic"], stamp),
            )
        db.commit()
        if error is None:
            event_type = "queue.completed"
            payload = {"status": "completed"}
        elif row["attempts"] >= max_attempts:
            event_type = "queue.failed"
            payload = {"status": "failed", "error_type": "processing_error"}
        else:
            event_type = "queue.retry_scheduled"
            payload = {"status": "pending", "attempt": row["attempts"]}
        record_event(event_type, entity_type="topic_queue", entity_id=queue_id, payload=payload)
        if error is not None and row["attempts"] >= max_attempts and row["target_job_id"] is not None:
            record_event("review.regeneration_failed", entity_type="pipeline_job",
                         entity_id=row["target_job_id"],
                         payload={"queue_id": queue_id, "error_type": "render_error"})
        return True
    finally:
        db.close()

def import_legacy_topics_file():
    """Import the legacy OneDrive topics.txt without losing content on worker crashes."""
    path = "topics.txt"
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        snapshot = handle.read()
    lines = [line.strip() for line in snapshot.splitlines() if line.strip()]
    if not lines:
        return
    import hashlib
    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        stamp = datetime.now().isoformat(timespec="seconds")
        channels = [row["name"] for row in db.execute("SELECT name FROM channels ORDER BY id")]
        added = 0
        for index, line in enumerate(lines):
            key = hashlib.sha256(f"{digest}:{index}:{line}".encode("utf-8")).hexdigest()
            channel_name, topic = (line.split("|", 1) if "|" in line else (None, line))
            channel_name = channel_name.strip() if channel_name else None
            topic = topic.strip()
            targets = [channel_name] if channel_name else channels
            for target in targets:
                if topic and target:
                    cursor = db.execute(
                        """INSERT OR IGNORE INTO topic_queue
                           (idempotency_key, channel_name, topic, source, status, attempts,
                            available_at, created_at, updated_at)
                           VALUES (?, ?, ?, 'topics.txt', 'pending', 0, ?, ?, ?)""",
                        (f"{key}:{target}", target, topic, int(time.time()), stamp, stamp),
                    )
                    added += max(0, cursor.rowcount)
        db.commit()
        if added:
            record_event("queue.enqueued", entity_type="topic_queue",
                         payload={"source": "topics.txt", "channel_count": added})
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    # Clear only if no external edit occurred after the snapshot was read.
    with open(path, "r", encoding="utf-8") as handle:
        current = handle.read()
    if current == snapshot:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")

def configured_queue_worker_count():
    """Bound local render concurrency to protect CPU/memory while allowing parallel jobs."""
    try:
        requested = int(os.getenv("NEXUS_QUEUE_WORKERS", "1"))
    except (TypeError, ValueError):
        requested = 1
    return max(1, min(requested, 4))


def watch_legacy_topics_loop():
    """Keep the legacy OneDrive text-file bridge single-writer and separate from render workers."""
    while True:
        try:
            import_legacy_topics_file()
        except Exception:
            logger.exception("Legacy topics bridge failed")
        time.sleep(5)


def watch_topics_loop(worker_id: int = 1):
    """One durable queue consumer; SQLite leases fence competing worker threads/instances."""
    logger.info("Queue worker %s started", worker_id)
    while True:
        item = None
        try:
            item = claim_next_topic()
            if item:
                db = get_db()
                try:
                    channel = db.execute("SELECT * FROM channels WHERE name=?", (item["channel_name"],)).fetchone()
                    if not channel:
                        raise ValueError(f"Unknown channel: {item['channel_name']}")
                    heartbeat_stop = threading.Event()
                    heartbeat = threading.Thread(
                        target=_topic_lease_heartbeat,
                        args=(item["id"], item["lease_token"], heartbeat_stop),
                        daemon=True,
                    )
                    heartbeat.start()
                    try:
                        run_make_video(channel["name"], channel["persona"], item["topic"],
                           queue_id=item["id"], lease_token=item["lease_token"],
                           script_override=item.get("script_override"),
                           title_override=item.get("title_override"),
                           target_job_id=item.get("target_job_id"))
                    finally:
                        heartbeat_stop.set()
                        heartbeat.join(timeout=2)
                finally:
                    db.close()
        except Exception as exc:
            logger.exception("Topic queue worker %s failed", worker_id)
            if "item" in locals() and item:
                try:
                    finish_topic(item["id"], item["lease_token"], str(exc))
                except Exception:
                    logger.exception("Could not update failed queue item")
        time.sleep(2)


def claim_daily_schedule(schedule_key: str, lease_seconds: int = 21600, max_attempts: int = 3):
    """Persistently claim one daily production run and return its fencing token."""
    now = int(time.time())
    stamp = datetime.now().isoformat(timespec="seconds")
    lease_token = secrets.token_urlsafe(24)
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM scheduler_runs WHERE schedule_key=?", (schedule_key,)).fetchone()
        if row and row["status"] == "completed":
            db.commit()
            return None
        if row and row["status"] == "running" and row["lease_until"] and row["lease_until"] > now:
            db.commit()
            return None
        if row and row["attempts"] >= max_attempts:
            db.execute(
                "UPDATE scheduler_runs SET status='failed', lease_until=NULL, lease_token=NULL, updated_at=? WHERE schedule_key=?",
                (stamp, schedule_key),
            )
            db.commit()
            return None
        if row:
            db.execute(
                """UPDATE scheduler_runs SET status='running', attempts=attempts+1,
                   lease_until=?, lease_token=?, last_error=NULL, updated_at=? WHERE schedule_key=?""",
                (now + lease_seconds, lease_token, stamp, schedule_key),
            )
        else:
            db.execute(
                """INSERT INTO scheduler_runs
                   (schedule_key, status, attempts, lease_until, lease_token, created_at, updated_at)
                   VALUES (?, 'running', 1, ?, ?, ?, ?)""",
                (schedule_key, now + lease_seconds, lease_token, stamp, stamp),
            )
        db.commit()
        record_event("scheduler.started", entity_type="scheduler_run", entity_id=schedule_key,
                     payload={"attempt": (row["attempts"] + 1) if row else 1})
        return lease_token
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def finish_daily_schedule(schedule_key: str, lease_token: str, error: str | None = None):
    """Finish only the currently leased scheduler attempt."""
    if not lease_token:
        return False
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT attempts FROM scheduler_runs WHERE schedule_key=? AND status='running' AND lease_token=? AND lease_until>?",
            (schedule_key, lease_token, int(time.time())),
        ).fetchone()
        if not row:
            db.rollback()
            return False
        stamp = datetime.now().isoformat(timespec="seconds")
        if error is None:
            db.execute(
                "UPDATE scheduler_runs SET status='completed', lease_until=NULL, lease_token=NULL, last_error=NULL, updated_at=? WHERE schedule_key=? AND lease_token=?",
                (stamp, schedule_key, lease_token),
            )
        else:
            db.execute(
                "UPDATE scheduler_runs SET status='failed', lease_until=NULL, lease_token=NULL, last_error=?, updated_at=? WHERE schedule_key=? AND lease_token=?",
                (error[:2000], stamp, schedule_key, lease_token),
            )
        db.commit()
        record_event("scheduler.failed" if error else "scheduler.completed",
                     entity_type="scheduler_run", entity_id=schedule_key,
                     payload={"error_type": "scheduler_error"} if error else {"status": "completed"})
        return True
    finally:
        db.close()

def auto_radar_and_scheduler_loop():
    time.sleep(5)
    while True:
        try:
            trend_radar.scan_global_trends("daily")
            trend_radar.scan_global_trends("weekly")
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            schedule_token = claim_daily_schedule(today_str) if AUTO_PRODUCE_ENABLED and now.hour >= 8 else None
            if schedule_token:
                try:
                    auto_produce_top_trends(count=3)
                    finish_daily_schedule(today_str, schedule_token)
                except Exception as exc:
                    finish_daily_schedule(today_str, schedule_token, str(exc))
                    raise
        except Exception:
            logger.exception("Radar scheduler failed")
        time.sleep(RADAR_INTERVAL_SEC)

@app.on_event("startup")
def startup_event():
    if is_hosted_auth_enabled():
        logger.warning("Hosted auth is enabled; local SQLite initialization, queue workers, and radar scheduler are disabled.")
        return
    init_app_db()
    radar_db = trend_radar.init_radar_db()
    radar_db.close()
    threading.Thread(
        target=watch_legacy_topics_loop, daemon=True, name="nexus-legacy-topics-bridge"
    ).start()
    worker_count = configured_queue_worker_count()
    for worker_id in range(1, worker_count + 1):
        threading.Thread(
            target=watch_topics_loop, args=(worker_id,), daemon=True,
            name=f"nexus-queue-worker-{worker_id}",
        ).start()
    logger.info("Started %s durable queue worker(s)", worker_count)
    threading.Thread(
        target=auto_radar_and_scheduler_loop, daemon=True, name="nexus-radar-scheduler"
    ).start()

class LoginReq(BaseModel):
    password: str

class CreateReq(BaseModel):
    channel_name: str
    topic: str

class QueueReq(BaseModel):
    topics_text: str

class BulkDelReq(BaseModel):
    job_ids: list[int]

class UpdateJobReq(BaseModel):
    title: str
    script: str

class RejectReq(BaseModel):
    note: str = ""

@app.get("/")
def serve_home():
    # Hosted SaaS users enter through the Supabase-authenticated workspace UI.
    # The legacy single-operator dashboard remains available only in local mode.
    if is_hosted_auth_enabled():
        if os.path.exists("workspace.html"):
            return FileResponse("workspace.html", media_type="text/html; charset=utf-8")
        return RedirectResponse(url="/signup", status_code=307)
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"status": "OK"}

@app.get("/api/session/status")
def session_status(request: Request):
    required = auth_is_required()
    authenticated = (not required) or verify_session_cookie(request.cookies.get(SESSION_COOKIE_NAME))
    return {"configured": auth_is_configured(), "authenticated": authenticated, "required": required}

def session_cookie_is_secure(request: Request) -> bool:
    """Use Secure cookies automatically on HTTPS while preserving local HTTP development."""
    configured = os.getenv("NEXUS_COOKIE_SECURE", "auto").strip().lower()
    if configured == "auto":
        return request.url.scheme == "https"
    return configured in ("1", "true", "yes", "on")


@app.post("/api/session/login")
def session_login(req: LoginReq, request: Request):
    if not auth_is_configured():
        raise HTTPException(status_code=503, detail="서버 설정에 NEXUS_API_PASSWORD(12자 이상)와 NEXUS_SESSION_SECRET(32자 이상)을 지정해야 합니다.")
    if not hmac.compare_digest(req.password, API_PASSWORD):
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")
    response = JSONResponse({"ok": True})
    response.set_cookie(key=SESSION_COOKIE_NAME, value=create_session_cookie(), max_age=SESSION_TTL_SECONDS, httponly=True, secure=session_cookie_is_secure(request), samesite="strict", path="/")
    return response

@app.post("/api/session/logout")
def session_logout(request: Request):
    response = JSONResponse({"ok": True})
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", httponly=True, secure=session_cookie_is_secure(request), samesite="strict")
    return response
@app.get("/api/events")
def get_events(limit: int = 50, event_type: str | None = None):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    return {"items": list_events(limit=limit, event_type=event_type)}

@app.get("/api/analytics/summary")
def analytics_summary(refresh: bool = False):
    db = get_db()
    try:
        total_jobs = db.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[0]
        channel_names = [row[0] for row in db.execute("SELECT name FROM channels ORDER BY name").fetchall()]
        by_stage = {
            row[0]: row[1] for row in db.execute(
                "SELECT stage, COUNT(*) FROM pipeline_jobs GROUP BY stage"
            ).fetchall()
        }
        by_channel = [
            dict(row) for row in db.execute(
                """SELECT channel_name, COUNT(*) AS jobs_total,
                          SUM(CASE WHEN stage='최종컨펌 대기' THEN 1 ELSE 0 END) AS review_pending,
                          SUM(CASE WHEN stage='업로드 완료(비공개)' THEN 1 ELSE 0 END) AS uploaded_private,
                          SUM(CASE WHEN youtube_video_id IS NOT NULL AND youtube_video_id != '' THEN 1 ELSE 0 END) AS provider_video_ids
                   FROM pipeline_jobs GROUP BY channel_name ORDER BY jobs_total DESC, channel_name"""
            ).fetchall()
        ]
        publishing = {
            "private_uploads": by_stage.get("업로드 완료(비공개)", 0),
            "upload_in_progress": by_stage.get("업로드 진행 중", 0),
            "privacy_unverified": by_stage.get("업로드 상태 확인 필요", 0),
            "regeneration_pending": by_stage.get("재제작 대기", 0),
            "regeneration_failed": by_stage.get("재제작 실패", 0),
        }
    finally:
        db.close()
    daily_scan = trend_radar.get_scan_status("daily")
    weekly_scan = trend_radar.get_scan_status("weekly")
    source_health = trend_radar.get_source_health()
    platform_metrics = youtube_analytics.get_platform_metrics(channel_names, force_refresh=refresh)
    return {
        "production": {"jobs_total": total_jobs, "by_stage": by_stage, "by_channel": by_channel},
        "publishing": publishing,
        "discovery": {
            "daily_scan": daily_scan,
            "weekly_scan": weekly_scan,
            "source_health": source_health,
            "global_ranking_available": False,
        },
        "platform_metrics": platform_metrics,
    }


@app.get("/api/ops/metrics")
def ops_metrics():
    return get_ops_metrics()

@app.get("/api/overview")
def overview():
    db = get_db()
    try:
        chs = [dict(r) for r in db.execute("SELECT * FROM channels").fetchall()]
        jobs = [dict(r) for r in db.execute("SELECT * FROM pipeline_jobs ORDER BY id DESC").fetchall()]
    finally:
        db.close()
    queue_db = get_db()
    try:
        pending = queue_db.execute(
            "SELECT channel_name, topic FROM topic_queue WHERE status IN ('pending','running') ORDER BY id"
        ).fetchall()
    finally:
        queue_db.close()
    q_txt = "\\n".join(
        (f"{row['channel_name']} | " if row["channel_name"] else "") + row["topic"]
        for row in pending
    )
    return {"channels": chs, "jobs": jobs, "topics_text": q_txt, "auto_produce": AUTO_PRODUCE_ENABLED,
            "queue_pending": len(pending)}

@app.get("/api/radar/{period}")
def get_radar(period: str = "daily"):
    if period not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="period must be daily or weekly")
    conn = trend_radar.init_radar_db()
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT * FROM trend_recommendations WHERE period_type=?
               ORDER BY region, source_name, source_rank""",
            (period,),
        ).fetchall()]
    finally:
        conn.close()
    scan = trend_radar.get_scan_status(period)
    source_health = trend_radar.get_source_health()
    source_summary = (scan or {}).get("source_summary") or {}
    for row in rows:
        source_state = source_summary.get(row.get("source_name"), {})
        row["source_status"] = source_state.get("status", "unknown")
        row["source_error"] = source_state.get("error")
        row["source_is_stale"] = row["source_status"] != "success"
    data_status = "not_scanned" if not scan else (
        "fresh" if scan["status"] == "success" else ("partial" if scan["status"] == "partial" else "stale")
    )
    return {
        "period": period,
        "items": rows,
        "scan": scan,
        "source_health": source_health,
        "data_status": data_status,
        "global_ranking_available": False,
        "ranking_note": "Source-local order only; cross-source popularity is not comparable.",
    }

@app.post("/api/radar/scan/{period}")
def run_radar_scan(period: str = "daily"):
    if period not in ("daily", "weekly"):
        raise HTTPException(status_code=400, detail="period must be daily or weekly")
    items = trend_radar.scan_global_trends(period)
    scan = trend_radar.get_scan_status(period)
    return {
        "ok": bool(scan and scan["status"] in ("success", "partial")),
        "fetched_count": len(items),
        "scan": scan,
        "msg": f"Discovery scan finished: {len(items)} source-attributed items",
    }

@app.post("/api/radar/auto-produce-now")
def trigger_auto_produce(bg: BackgroundTasks):
    bg.add_task(auto_produce_top_trends, 3)
    return {"ok": True, "msg": "지역별 원천 순위 후보 최대 3건을 제작 큐에 등록합니다."}

@app.post("/api/radar/toggle-auto/{enabled}")
def toggle_auto_produce(enabled: int):
    global AUTO_PRODUCE_ENABLED
    AUTO_PRODUCE_ENABLED = bool(enabled)
    return {"ok": True, "enabled": AUTO_PRODUCE_ENABLED, "msg": "자동 제작 설정 변경 완료"}

@app.post("/api/radar/interval/{minutes}")
def set_radar_interval(minutes: int):
    global RADAR_INTERVAL_SEC
    if minutes < 1 or minutes > 1440:
        raise HTTPException(status_code=400, detail="minutes must be between 1 and 1440")
    RADAR_INTERVAL_SEC = minutes * 60
    return {"ok": True, "msg": f"자동 수집 주기가 {minutes}분으로 변경되었습니다."}

@app.post("/api/create")
def create_single(req: CreateReq):
    if not req.channel_name.strip() or not req.topic.strip():
        raise HTTPException(status_code=400, detail="channel_name and topic are required")
    db = get_db()
    try:
        ch = db.execute("SELECT * FROM channels WHERE name=?", (req.channel_name,)).fetchone()
    finally:
        db.close()
    if not ch:
        raise HTTPException(status_code=404, detail="Unknown channel")
    queued = enqueue_topic(f"{req.channel_name} | {req.topic}", source="api_create")
    return {"ok": True, "queued": queued, "msg": f"[{req.channel_name}] 제작 요청을 내구성 큐에 등록했습니다."}

@app.post("/api/create-all")
def create_all():
    db = get_db()
    try:
        channels = db.execute("SELECT * FROM channels").fetchall()
    finally:
        db.close()
    queued = 0
    for ch in channels:
        queued += enqueue_topic(
            f"{ch['name']} | 오늘의 글로벌 핵심 트렌드",
            source="api_create_all",
        )
    return {"ok": True, "queued": queued, "msg": f"전 채널 제작 요청 {queued}건을 내구성 큐에 등록했습니다."}

@app.post("/api/queue")
def save_queue(req: QueueReq):
    topics_text = req.topics_text or ""
    if len(topics_text) > 20000:
        raise HTTPException(status_code=413, detail="Queue payload exceeds 20,000 characters")
    lines = [line.strip() for line in topics_text.splitlines() if line.strip()]
    if len(lines) > 100:
        raise HTTPException(status_code=400, detail="A single queue request may contain at most 100 topics")
    db = get_db()
    try:
        known_channels = {row["name"] for row in db.execute("SELECT name FROM channels")}
    finally:
        db.close()
    for line in lines:
        if "|" in line:
            channel_name, topic = [part.strip() for part in line.split("|", 1)]
            if not channel_name or not topic:
                raise HTTPException(status_code=400, detail="Queue lines must be 'channel | topic' or 'topic'")
            if channel_name not in known_channels:
                raise HTTPException(status_code=400, detail=f"Unknown channel: {channel_name}")
        if len(line) > 2000:
            raise HTTPException(status_code=400, detail="Each topic must be 2,000 characters or fewer")
    try:
        added = sum(enqueue_topic(line, source="api") for line in lines)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "queued": added, "msg": f"{added}건을 채널별 내구성 제작 큐에 등록했습니다."}

def _upload_result_metadata(ok: bool, message: str):
    """Extract only the provider-confirmed video ID and privacy state from the upload adapter result."""
    if ok:
        marker = "영상 ID: "
        video_id = message.split(marker, 1)[1].split()[0] if marker in message else None
        return video_id, "private" if video_id else "unknown"
    if message.startswith("UPLOAD_CREATED_PRIVACY_UNVERIFIED:"):
        parts = message.split(":", 2)
        video_id = parts[1] if len(parts) > 1 and parts[1] != "unknown" else None
        reported_privacy = parts[2] if len(parts) > 2 else "unknown"
        privacy = reported_privacy if reported_privacy in ("private", "public", "unlisted", "unknown") else "unknown"
        return video_id, privacy
    if message.startswith("UPLOAD_RESULT_UNCERTAIN:"):
        return None, "unknown"
    return None, None


@app.post("/api/approve/{job_id}")
def approve_job(job_id: int):
    db = get_db()
    try:
        jb = db.execute("SELECT * FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        db.close()
    if not jb:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    if jb["stage"] != "최종컨펌 대기":
        raise HTTPException(status_code=409, detail="이미 처리됐거나 업로드 상태 확인이 필요한 작업입니다.")
    output_root = os.path.realpath("output")
    video_path = os.path.realpath(jb["video_path"])
    try:
        inside_output = os.path.commonpath([output_root, video_path]) == output_root
    except ValueError:
        inside_output = False
    if not inside_output or not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail="output 폴더 안의 실제 영상 파일만 업로드할 수 있습니다.")
    qa = validate_video(video_path)
    if not qa.get("ok"):
        record_event("upload.blocked_qa", entity_type="pipeline_job", entity_id=job_id,
                     payload={"errors": qa.get("errors", [])})
        raise HTTPException(status_code=409, detail="업로드 직전 영상 품질검사에 실패했습니다.")
    db = get_db()
    try:
        if not claim_upload(db, job_id):
            raise HTTPException(status_code=409, detail="다른 요청에서 이미 검수 또는 업로드를 처리하고 있습니다.")
        db.commit()
    finally:
        db.close()
    record_event("review.approved", entity_type="pipeline_job", entity_id=job_id,
                 payload={"channel": jb["channel_name"], "approval_source": "api"})
    ok, msg = yt_uploader.upload_to_youtube(jb["channel_name"], video_path, jb["title"], jb["script"])
    privacy_unverified = msg.startswith("UPLOAD_CREATED_PRIVACY_UNVERIFIED:") or msg.startswith("UPLOAD_RESULT_UNCERTAIN:")
    video_id, privacy_status = _upload_result_metadata(ok, msg)
    if ok and (not video_id or privacy_status != "private"):
        ok = False
        privacy_unverified = True
        privacy_status = privacy_status or "unknown"
        msg = f"UPLOAD_CREATED_PRIVACY_UNVERIFIED:{video_id or 'unknown'}:{privacy_status}"
    event_type = "upload.completed" if ok else ("upload.privacy_unverified" if privacy_unverified else "upload.failed")
    record_event(event_type, entity_type="pipeline_job", entity_id=job_id,
                 payload={"channel": jb["channel_name"], "video_id": video_id,
                          "privacy_status": privacy_status})
    db = get_db()
    try:
        db.execute(
            "UPDATE pipeline_jobs SET stage=?, youtube_video_id=?, privacy_status=? WHERE id=?",
            (upload_result_stage(ok, privacy_unverified), video_id, privacy_status, job_id),
        )
        db.commit()
    finally:
        db.close()
    return {"ok": ok, "msg": msg, "video_id": video_id, "privacy_status": privacy_status}

@app.post("/api/reject/{job_id}")
def reject_job(job_id: int, req: RejectReq):
    note = (req.note or "").strip()
    if len(note) > 2000:
        raise HTTPException(status_code=400, detail="반려 사유는 2000자 이하여야 합니다.")
    db = get_db()
    try:
        job = db.execute("SELECT stage, channel_name FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        if job["stage"] != "최종컨펌 대기":
            raise HTTPException(status_code=409, detail="검수 대기 상태의 작업만 반려할 수 있습니다.")
        cur = db.execute("UPDATE pipeline_jobs SET stage='반려(수정 필요)' WHERE id=? AND stage='최종컨펌 대기'", (job_id,))
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="다른 요청에서 이미 검수 또는 업로드를 처리하고 있습니다.")
        db.commit()
    finally:
        db.close()
    record_event("review.rejected", entity_type="pipeline_job", entity_id=job_id,
                 payload={"channel": job["channel_name"], "note": note, "source": "browser_studio"})
    return {"ok": True, "msg": "반려 및 수정 요청이 기록되었습니다."}

def enqueue_job_regeneration(job_id: int, title: str, script: str):
    """Atomically move an editable review job to regeneration and enqueue its exact revision."""
    sentences = split_manual_script(script)
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        job = db.execute(
            "SELECT stage, channel_name FROM pipeline_jobs WHERE id=?", (job_id,)
        ).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        allowed_stages = ("최종컨펌 대기", "반려(수정 필요)", "재제작 실패")
        if job["stage"] not in allowed_stages:
            raise HTTPException(status_code=409, detail="검수 대기, 반려 또는 재제작 실패 상태의 작업만 수정할 수 있습니다.")
        cur = db.execute(
            "UPDATE pipeline_jobs SET stage='재제작 대기' WHERE id=? AND stage=?",
            (job_id, job["stage"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="작업 상태가 변경되어 재제작을 등록하지 못했습니다.")
        stamp = datetime.now().isoformat(timespec="seconds")
        queue_key = f"review-edit:{job_id}:{secrets.token_urlsafe(12)}"
        queued = db.execute(
            """INSERT INTO topic_queue
               (idempotency_key, channel_name, topic, source, status, attempts, available_at,
                title_override, script_override, target_job_id, created_at, updated_at)
               VALUES (?, ?, ?, 'review_regeneration', 'pending', 0, ?, ?, ?, ?, ?, ?)""",
            (queue_key, job["channel_name"], title, int(time.time()), title, script,
             job_id, stamp, stamp),
        )
        queue_id = queued.lastrowid
        db.commit()
        record_event("review.regeneration_queued", entity_type="pipeline_job", entity_id=job_id,
                     payload={"channel": job["channel_name"], "queue_id": queue_id,
                              "sentence_count": len(sentences)})
        return queue_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.put("/api/jobs/{job_id}")
def update_job(job_id: int, req: UpdateJobReq):
    title = (req.title or "").strip()
    script = (req.script or "").strip()
    title = " ".join(title.split())
    if not title or len(title) > 100:
        raise HTTPException(status_code=400, detail="title must contain 1 to 100 characters")
    if len(script) > 20000:
        raise HTTPException(status_code=400, detail="script exceeds the 20,000 character limit")
    try:
        queue_id = enqueue_job_regeneration(job_id, title, script)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "queued": True, "queue_id": queue_id,
            "msg": "수정한 대본으로 재제작을 등록했습니다. 새 영상의 품질검수 후 다시 최종 승인을 요청합니다."}

@app.post("/api/jobs/bulk-delete")
def bulk_delete_jobs(req: BulkDelReq):
    job_ids = sorted(set(req.job_ids or []))
    if not job_ids:
        return {"ok": False, "deleted": 0, "skipped": 0, "msg": "선택된 항목이 없습니다."}
    if len(job_ids) > 100 or any(job_id < 1 for job_id in job_ids):
        raise HTTPException(status_code=400, detail="Select at most 100 valid job IDs")
    db = get_db()
    try:
        placeholders = ",".join("?" for _ in job_ids)
        cur = db.execute(
            f"DELETE FROM pipeline_jobs WHERE id IN ({placeholders}) AND stage NOT IN ('업로드 진행 중','재제작 대기')",
            job_ids,
        )
        db.commit()
        deleted = cur.rowcount
        skipped = len(job_ids) - deleted
        return {"ok": True, "deleted": deleted, "skipped": skipped,
                "msg": f"{deleted}건 삭제, 진행 중인 작업 {skipped}건은 보호했습니다."}
    finally:
        db.close()

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    db = get_db()
    try:
        job = db.execute("SELECT stage FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        if job["stage"] in ("업로드 진행 중", "재제작 대기"):
            raise HTTPException(status_code=409, detail="업로드 또는 재제작이 진행 중인 작업은 삭제할 수 없습니다.")
        cur = db.execute("DELETE FROM pipeline_jobs WHERE id=? AND stage NOT IN ('업로드 진행 중','재제작 대기')", (job_id,))
        db.commit()
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="작업 상태가 변경되어 삭제하지 못했습니다.")
        return {"ok": True, "msg": "삭제 완료"}
    finally:
        db.close()
