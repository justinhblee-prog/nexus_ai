"""Resumable, tenant-safe Supabase account deletion worker.

The worker is disabled by default. It processes only service-queued requests
whose user refresh sessions were revoked, and it never deletes shared workspace
content. Any uncertain ownership or incomplete cleanup blocks/retries the job.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from collections import defaultdict

from supabase_admin import SupabaseAdminError, SupabaseAdminRestClient
from token_vault import TokenVaultError, decrypt_refresh_token
from youtube_oauth import GoogleOAuthConfig, GoogleOAuthError


logger = logging.getLogger("nexus.account_deletion_worker")


class AccountDeletionBlocked(RuntimeError):
    def __init__(self, phase: str, code: str):
        super().__init__(code)
        self.phase = phase
        self.code = code


class AccountDeletionRetry(RuntimeError):
    def __init__(self, phase: str, code: str):
        super().__init__(code)
        self.phase = phase
        self.code = code


def _workspace_plan(admin, user_id):
    memberships = admin.list_account_user_memberships(user_id)
    owned = admin.list_account_owned_workspaces(user_id)
    membership_ids = list(dict.fromkeys(row["workspace_id"] for row in memberships))
    owned_by_id = {row["workspace_id"]: row for row in owned}
    all_ids = list(dict.fromkeys(membership_ids + list(owned_by_id)))
    if len(all_ids) > 100:
        raise AccountDeletionBlocked("workspace_inventory", "workspace_limit_exceeded")

    deleting = []
    shared = []
    for workspace_id in all_ids:
        members = admin.list_account_workspace_members(workspace_id)
        current_membership = next((row for row in members if row.get("user_id") == user_id), None)
        is_owner = workspace_id in owned_by_id
        if not is_owner and current_membership and current_membership.get("role") == "owner":
            raise AccountDeletionBlocked("workspace_inventory", "owner_record_mismatch")
        if is_owner:
            if not current_membership or current_membership.get("role") != "owner":
                raise AccountDeletionBlocked("workspace_inventory", "owner_membership_inconsistent")
            others = [row for row in members if row.get("user_id") != user_id]
            if others:
                raise AccountDeletionBlocked("workspace_transfer", "workspace_ownership_transfer_required")
            deleting.append(workspace_id)
        else:
            if not current_membership:
                raise AccountDeletionBlocked("workspace_inventory", "membership_inconsistent")
            shared.append(workspace_id)
    return deleting, shared


def _inventory_storage(admin, user_id, deleting, shared):
    objects = []
    offset = 0
    while True:
        page = admin.list_account_deletion_storage_objects(
            user_id, limit=1000, offset=offset, workspace_ids=deleting
        )
        objects.extend(page)
        if len(page) < 1000:
            break
        offset += len(page)

    gallery = admin.list_account_personal_gallery_images(user_id)
    gallery_keys = {
        key for row in gallery
        for key in (row.get("storage_key"), row.get("thumbnail_key"))
        if key
    }
    buckets_by_name = defaultdict(set)
    for item in objects:
        buckets_by_name[item.get("name") or ""].add(item.get("bucket_id"))
    if any(len(values) > 1 for values in buckets_by_name.values()):
        raise AccountDeletionBlocked("storage_inventory", "ambiguous_storage_object_bucket")
    for item in objects:
        name = item.get("name") or ""
        prefix = name.split("/", 1)[0]
        if prefix in shared:
            raise AccountDeletionBlocked("storage_inventory", "shared_workspace_storage_found")
        if prefix not in deleting and name not in gallery_keys:
            raise AccountDeletionBlocked("storage_inventory", "unclassified_storage_object_found")
        if not item.get("bucket_id") or not name:
            raise AccountDeletionBlocked("storage_inventory", "storage_object_identity_incomplete")
        if item["bucket_id"] not in {"acs-assets", "acs-gallery", "acs-outputs", "nexus-shorts"}:
            raise AccountDeletionBlocked("storage_inventory", "unsupported_storage_bucket")
    return objects


def _cleanup_oauth(admin, deleting, oauth_config_factory, decrypt_token):
    if not deleting:
        return
    connections = admin.list_youtube_connections_for_workspaces(deleting)
    grouped = defaultdict(list)
    for connection in connections:
        provider_account_id = connection.get("provider_account_id")
        if not provider_account_id:
            raise AccountDeletionBlocked("oauth_cleanup", "provider_account_identity_missing")
        grouped[provider_account_id].append(connection)

    oauth_config = None
    for provider_account_id, group in grouped.items():
        active = [row for row in group if row.get("status") == "connected"]
        if active and not admin.has_active_connection_outside_workspaces(provider_account_id, deleting):
            credentials = []
            for connection in active:
                credential = admin.get_credential(str(connection["connection_id"]))
                if credential:
                    credentials.append((connection, credential))
            if not credentials:
                raise AccountDeletionBlocked("oauth_cleanup", "connected_oauth_credential_missing")
            if oauth_config is None:
                oauth_config = oauth_config_factory()
            # One valid refresh token revokes this Google grant. Every credential
            # in the deleted workspaces is then removed, including duplicates.
            credential = credentials[0][1]
            refresh_token = decrypt_token(
                credential["encrypted_refresh_token_hex"],
                credential["encryption_key_version"],
            )
            oauth_config.revoke_refresh_token(refresh_token)
        for connection in group:
            admin.delete_credential(str(connection["connection_id"]))


def process_one_account_deletion(
    admin,
    worker_id,
    oauth_config_factory=None,
    decrypt_token=decrypt_refresh_token,
    lease_seconds=900,
    retry_seconds=120,
):
    request = admin.claim_next_account_deletion_request(worker_id, lease_seconds)
    if not request:
        return False
    user_id = str(request["user_id"])
    phase = "workspace_inventory"
    stop_heartbeat = threading.Event()
    lease_lost = threading.Event()

    def heartbeat_loop():
        while not stop_heartbeat.wait(60):
            try:
                if not admin.heartbeat_account_deletion_request(user_id, worker_id, lease_seconds):
                    lease_lost.set()
                    return
            except Exception:
                lease_lost.set()
                return

    heartbeat = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat.start()

    def ensure_lease():
        if lease_lost.is_set():
            raise AccountDeletionRetry("worker_lease", "worker_lease_lost")

    try:
        if not request.get("sessions_revoked"):
            raise AccountDeletionRetry("session_revocation", "sessions_not_revoked")

        deleting, shared = _workspace_plan(admin, user_id)
        ensure_lease()
        phase = "worker_lease_check"
        leases = admin.list_account_deletion_active_leases(deleting)
        if leases:
            raise AccountDeletionRetry("worker_lease_check", "active_worker_leases")

        ensure_lease()
        phase = "storage_inventory"
        objects = _inventory_storage(admin, user_id, deleting, shared)

        ensure_lease()
        phase = "oauth_cleanup"
        _cleanup_oauth(
            admin,
            deleting,
            oauth_config_factory or GoogleOAuthConfig.from_env,
            decrypt_token,
        )

        ensure_lease()
        phase = "storage_cleanup"
        for item in objects:
            ensure_lease()
            admin.delete_storage_object_in_bucket(item["bucket_id"], item["name"])

        ensure_lease()
        phase = "workspace_cleanup"
        admin.delete_account_workspace_generation_jobs(deleting)
        admin.anonymize_account_authorship(user_id, deleting)
        admin.delete_account_personal_rows(user_id)
        for workspace_id in deleting:
            ensure_lease()
            admin.delete_account_workspace(workspace_id)
        for workspace_id in shared:
            ensure_lease()
            admin.delete_account_workspace_membership(user_id, workspace_id)

        phase = "identity_cleanup"
        admin.delete_account_profile(user_id)
        counts = admin.account_user_reference_counts(user_id)
        private_counts = admin.count_account_private_user_rows(user_id)
        if any(int(value or 0) for value in counts.values()):
            raise AccountDeletionRetry("identity_verification", "user_references_remain")
        if any(int(value or 0) for value in private_counts.values()):
            raise AccountDeletionRetry("identity_verification", "private_user_references_remain")

        remaining_storage = admin.list_account_deletion_storage_objects(user_id, limit=1000, offset=0)
        if remaining_storage:
            raise AccountDeletionRetry("storage_verification", "storage_objects_remain")

        ensure_lease()
        phase = "auth_deletion"
        admin.delete_auth_user(user_id)

        phase = "final_verification"
        final_counts = admin.account_user_reference_counts(user_id)
        final_private_counts = admin.count_account_private_user_rows(user_id)
        final_storage = admin.list_account_deletion_storage_objects(user_id, limit=1000, offset=0)
        if any(int(value or 0) for value in final_counts.values()):
            raise AccountDeletionRetry("final_verification", "user_references_remain")
        if any(int(value or 0) for value in final_private_counts.values()) or final_storage:
            raise AccountDeletionRetry("final_verification", "private_or_storage_references_remain")

        if not admin.update_account_deletion_request(
            user_id, worker_id, "completed", "complete", None, retry_seconds
        ):
            raise SupabaseAdminError("Account deletion queue lease was lost before completion")
        logger.info("Account deletion completed for anonymized user reference %s", user_id)
        return True
    except AccountDeletionBlocked as exc:
        admin.update_account_deletion_request(
            user_id, worker_id, "blocked", exc.phase, exc.code, 86400
        )
        logger.warning("Account deletion blocked at %s (%s)", exc.phase, exc.code)
        return True
    except AccountDeletionRetry as exc:
        admin.update_account_deletion_request(
            user_id, worker_id, "retry", exc.phase, exc.code, retry_seconds
        )
        logger.warning("Account deletion will retry at %s (%s)", exc.phase, exc.code)
        return True
    except (SupabaseAdminError, GoogleOAuthError, TokenVaultError) as exc:
        code = type(exc).__name__.lower()
        try:
            admin.update_account_deletion_request(
                user_id, worker_id, "retry", phase, code, retry_seconds
            )
        except Exception:
            logger.exception("Could not persist retry state for account deletion")
        logger.warning("Account deletion failed safely at %s (%s)", phase, type(exc).__name__)
        return True
    except Exception as exc:
        try:
            admin.update_account_deletion_request(
                user_id, worker_id, "retry", phase, "unexpected_worker_error", retry_seconds
            )
        except Exception:
            logger.exception("Could not persist unexpected account deletion retry")
        logger.warning("Account deletion recovered from unexpected error (%s)", type(exc).__name__)
        return True
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=2)


def run_worker():
    if os.getenv("NEXUS_ACCOUNT_DELETION_WORKER_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.info("Account deletion worker is disabled; no account cleanup will run.")
        return
    try:
        admin = SupabaseAdminRestClient()
    except SupabaseAdminError as exc:
        logger.error("Account deletion worker configuration is invalid (%s)", type(exc).__name__)
        return
    worker_id = os.getenv("NEXUS_ACCOUNT_DELETION_WORKER_ID", "").strip() or f"{socket.gethostname()}-account-delete-{os.getpid()}"
    try:
        poll_seconds = max(5, min(120, int(os.getenv("NEXUS_ACCOUNT_DELETION_POLL_SECONDS", "20"))))
    except ValueError:
        poll_seconds = 20
    logger.info("NEXUS account deletion worker started.")
    while True:
        try:
            claimed = process_one_account_deletion(admin, worker_id)
            if not claimed:
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            logger.info("NEXUS account deletion worker stopped.")
            return
        except Exception as exc:
            logger.warning("Account deletion worker loop recovered from %s", type(exc).__name__)
            time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("NEXUS_LOG_LEVEL", "INFO").upper())
    run_worker()
