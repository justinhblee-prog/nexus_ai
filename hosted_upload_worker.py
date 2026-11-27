"""Opt-in YouTube upload worker.

Only explicitly approved jobs are eligible. Upload requests always specify private
visibility, verify the connected channel, and stop without public publishing.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time

from supabase_admin import SupabaseAdminError, SupabaseAdminRestClient
from token_vault import TokenVaultError, decrypt_refresh_token, validate_token_vault_config
from youtube_oauth import GoogleOAuthConfig, GoogleOAuthError


logger = logging.getLogger("nexus.hosted_upload_worker")
DEFAULT_LEASE_SECONDS = 600
DEFAULT_MAX_ATTEMPTS = 2
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _heartbeat_loop(admin, job_id, lease_token, stop_event, lost_event, lease_seconds):
    interval = max(20, lease_seconds // 3)
    while not stop_event.wait(interval):
        try:
            if not admin.heartbeat_shorts_upload_job(job_id, lease_token, lease_seconds):
                lost_event.set()
                return
        except Exception as exc:
            logger.warning("YouTube upload heartbeat failed (%s)", type(exc).__name__)
            lost_event.set()
            return


def process_one_upload(
    admin,
    worker_id,
    oauth_config_factory=None,
    decrypt_token=decrypt_refresh_token,
    lease_seconds=DEFAULT_LEASE_SECONDS,
    max_attempts=DEFAULT_MAX_ATTEMPTS,
    daily_limit=3,
):
    job = admin.claim_next_approved_shorts_job(worker_id, lease_seconds, max_attempts, daily_limit)
    if not job:
        return False
    job_id = str(job["job_id"])
    lease_token = str(job["lease_token"])
    stop_event = threading.Event()
    lost_event = threading.Event()

    try:
        if not admin.heartbeat_shorts_upload_job(job_id, lease_token, lease_seconds):
            raise RuntimeError("upload lease was not accepted")
    except Exception as exc:
        try:
            admin.finish_shorts_upload(job_id, lease_token, False, error=type(exc).__name__, max_attempts=max_attempts)
        except Exception:
            pass
        logger.warning("Approved job %s lost upload lease before transfer", job_id)
        return True

    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(admin, job_id, lease_token, stop_event, lost_event, lease_seconds),
        daemon=True,
    )
    heartbeat.start()
    try:
        video_id = job.get("provider_video_id")
        if not video_id:
            credential = admin.get_credential(str(job["connection_id"]))
            if not credential:
                raise SupabaseAdminError("YouTube refresh token is not available")
            refresh_token = decrypt_token(
                credential["encrypted_refresh_token_hex"],
                credential["encryption_key_version"],
            )
            config = (oauth_config_factory or GoogleOAuthConfig.from_env)()
            access_token = config.refresh_access_token(refresh_token)
            content = admin.download_storage_object(job["output_storage_key"])
            if not content or len(content) > MAX_UPLOAD_BYTES:
                raise RuntimeError("rendered media size is outside the upload limit")
            if lost_event.is_set():
                raise RuntimeError("upload lease was lost before transfer")
            uploaded = config.upload_private_video(
                access_token,
                content,
                job.get("title") or "NEXUS Shorts",
                job.get("script") or "",
                job["provider_channel_id"],
            )
            if uploaded["privacy_status"] != "private" or uploaded["channel_id"] != job["provider_channel_id"]:
                raise GoogleOAuthError("YouTube upload verification failed")
            video_id = uploaded["video_id"]
            recorded = admin.record_shorts_upload_video_id(
                job_id,
                lease_token,
                video_id,
                uploaded["channel_id"],
                uploaded["privacy_status"],
            )
            if recorded is not True:
                raise SupabaseAdminError("YouTube upload identity could not be recorded")
        if lost_event.is_set():
            raise RuntimeError("upload lease was lost before completion")
        result = admin.finish_shorts_upload(
            job_id, lease_token, True, video_id=video_id, max_attempts=max_attempts
        )
        if result not in ("published", {"finish_shorts_upload": "published"}):
            raise SupabaseAdminError("Private YouTube upload did not finalize")
        logger.info("Approved Shorts job %s uploaded privately to YouTube", job_id)
        return True
    except Exception as exc:
        try:
            admin.finish_shorts_upload(
                job_id, lease_token, False, error=type(exc).__name__, max_attempts=max_attempts
            )
        except Exception as finish_exc:
            logger.warning("Could not finalize YouTube upload failure for %s (%s)", job_id, type(finish_exc).__name__)
        logger.warning("YouTube upload for job %s failed (%s)", job_id, type(exc).__name__)
        return True
    finally:
        stop_event.set()
        heartbeat.join(timeout=2)


def run_worker():
    if os.getenv("NEXUS_HOSTED_UPLOAD_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.info("Hosted YouTube upload worker is disabled; no uploads will be attempted.")
        return
    try:
        admin = SupabaseAdminRestClient()
        GoogleOAuthConfig.from_env()
        validate_token_vault_config()
    except (SupabaseAdminError, GoogleOAuthError, TokenVaultError) as exc:
        logger.error("Hosted upload worker configuration is invalid (%s)", type(exc).__name__)
        return
    worker_id = os.getenv("NEXUS_HOSTED_UPLOAD_WORKER_ID", "").strip() or f"{socket.gethostname()}-upload-{os.getpid()}"
    try:
        poll_seconds = max(5, min(120, int(os.getenv("NEXUS_HOSTED_UPLOAD_POLL_SECONDS", "15"))))
        daily_limit = max(1, min(3, int(os.getenv("NEXUS_HOSTED_UPLOAD_DAILY_LIMIT", "3"))))
        max_attempts = max(1, min(3, int(os.getenv("NEXUS_HOSTED_UPLOAD_MAX_ATTEMPTS", "2"))))
    except ValueError:
        poll_seconds, daily_limit, max_attempts = 15, 3, 2
    logger.info("Hosted private YouTube upload worker started (daily cap=%s).", daily_limit)
    while True:
        try:
            claimed = process_one_upload(
                admin, worker_id, max_attempts=max_attempts, daily_limit=daily_limit
            )
            if not claimed:
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            logger.info("Hosted YouTube upload worker stopped.")
            return
        except Exception as exc:
            logger.warning("YouTube upload worker loop recovered from %s", type(exc).__name__)
            time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("NEXUS_LOG_LEVEL", "INFO").upper())
    run_worker()
