"""Tenant-aware Shorts render worker.

The worker is opt-in and uses only the server-side service_role client. It renders
with the free local fallback (no OpenAI/DALL-E API calls), stores media privately,
and stops at human review; it never uploads to YouTube.
"""
from __future__ import annotations

import hashlib
import logging
import os
import socket
import threading
import time
import uuid

from supabase_admin import SupabaseAdminError, SupabaseAdminRestClient
from video_qa import validate_video


logger = logging.getLogger("nexus.hosted_worker")
MAX_RENDER_BYTES = 100 * 1024 * 1024
DEFAULT_LEASE_SECONDS = 600
DEFAULT_MAX_ATTEMPTS = 3


class RenderQualityError(RuntimeError):
    pass


class LeaseLostError(RuntimeError):
    pass


def _heartbeat_loop(admin, job_id, lease_token, stop_event, lost_event, lease_seconds):
    interval = max(20, lease_seconds // 3)
    while not stop_event.wait(interval):
        try:
            if not admin.heartbeat_shorts_job(job_id, lease_token, lease_seconds):
                lost_event.set()
                return
        except Exception as exc:
            logger.warning("Hosted worker heartbeat failed (%s)", type(exc).__name__)
            lost_event.set()
            return


def process_one_job(
    admin,
    worker_id,
    renderer=None,
    validator=None,
    lease_seconds=DEFAULT_LEASE_SECONDS,
    max_attempts=DEFAULT_MAX_ATTEMPTS,
):
    if renderer is None:
        # Import the full media stack only in the actual worker process.
        from video_maker import render_pro_short
        renderer = render_pro_short
    validator = validator or validate_video
    job = admin.claim_next_shorts_job(worker_id, lease_seconds, max_attempts)
    if not job:
        return False

    job_id = str(job["job_id"])
    workspace_id = str(job["workspace_id"])
    lease_token = str(job["lease_token"])
    stop_event = threading.Event()
    lost_event = threading.Event()
    try:
        if not admin.heartbeat_shorts_job(job_id, lease_token, lease_seconds):
            raise LeaseLostError("worker lease was not accepted")
    except Exception as exc:
        try:
            admin.finish_shorts_job(job_id, lease_token, False, error=type(exc).__name__, max_attempts=max_attempts)
        except Exception:
            pass
        logger.warning("Hosted Shorts job %s lost its lease before rendering", job_id)
        return True
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(admin, job_id, lease_token, stop_event, lost_event, lease_seconds),
        daemon=True,
    )
    heartbeat.start()

    video_path = None
    storage_key = None
    uploaded = False
    asset_created = False
    try:
        # Empty key is deliberate: hosted free tier must not trigger paid OpenAI/DALL-E calls.
        video_path, title, script = renderer(
            job.get("channel_name") or "NEXUS",
            job.get("persona") or "전문가 톤",
            job["topic"],
            openai_key="",
            script_override=job.get("script") or None,
            title_override=job.get("title") or None,
        )
        if lost_event.is_set():
            raise LeaseLostError("worker lease was lost during rendering")
        qa = validator(video_path)
        if not qa.get("ok"):
            raise RenderQualityError(",".join(qa.get("errors") or ["video_quality_failed"]))
        size_bytes = os.path.getsize(video_path)
        if size_bytes <= 1024 or size_bytes > MAX_RENDER_BYTES:
            raise RenderQualityError("rendered_video_size_out_of_range")
        with open(video_path, "rb") as handle:
            content = handle.read()
        if lost_event.is_set():
            raise LeaseLostError("worker lease was lost before media upload")

        storage_key = f"{workspace_id}/{job_id}/{uuid.uuid4().hex}.mp4"
        admin.upload_storage_object(storage_key, content, "video/mp4")
        uploaded = True
        creator_id = admin.get_job_creator(job_id, workspace_id)
        if not creator_id:
            raise SupabaseAdminError("Shorts job owner could not be resolved")
        asset_rows = admin.create_asset({
            "workspace_id": workspace_id,
            "created_by": creator_id,
            "asset_kind": "rendered_video",
            "storage_key": storage_key,
            "media_type": "video/mp4",
            "size_bytes": size_bytes,
            "checksum_sha256": hashlib.sha256(content).hexdigest(),
        })
        if not asset_rows:
            raise SupabaseAdminError("Rendered media metadata could not be saved")
        asset_created = True
        if lost_event.is_set():
            raise LeaseLostError("worker lease was lost before render completion")
        result = admin.finish_shorts_job(
            job_id,
            lease_token,
            True,
            output_storage_key=storage_key,
            title=str(title)[:200],
            script=str(script)[:12000],
            max_attempts=max_attempts,
        )
        if result not in ("review_pending", {"finish_shorts_job": "review_pending"}):
            raise SupabaseAdminError("Rendered job did not enter human review")
        logger.info("Hosted Shorts job %s rendered and queued for human review", job_id)
        return True
    except Exception as exc:
        if asset_created and storage_key:
            try:
                admin.delete_asset(storage_key)
            except Exception:
                logger.warning("Could not remove orphan asset for job %s", job_id)
        if uploaded and storage_key:
            try:
                admin.delete_storage_object(storage_key)
            except Exception:
                logger.warning("Could not remove orphan media for job %s", job_id)
        try:
            admin.finish_shorts_job(
                job_id,
                lease_token,
                False,
                error=type(exc).__name__,
                max_attempts=max_attempts,
            )
        except Exception as finish_exc:
            logger.warning("Could not finalize failed job %s (%s)", job_id, type(finish_exc).__name__)
        logger.warning("Hosted Shorts job %s failed (%s)", job_id, type(exc).__name__)
        return True
    finally:
        stop_event.set()
        heartbeat.join(timeout=2)
        if video_path and os.path.isfile(video_path):
            try:
                os.remove(video_path)
            except OSError:
                logger.warning("Could not remove local render artifact for job %s", job_id)


def run_worker():
    if os.getenv("NEXUS_HOSTED_WORKER_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.info("Hosted Shorts worker is disabled; no jobs will be claimed.")
        return
    admin = SupabaseAdminRestClient()
    worker_id = os.getenv("NEXUS_HOSTED_WORKER_ID", "").strip() or f"{socket.gethostname()}-{os.getpid()}"
    try:
        poll_seconds = max(1, min(60, int(os.getenv("NEXUS_HOSTED_WORKER_POLL_SECONDS", "5"))))
    except ValueError:
        poll_seconds = 5
    logger.info("Hosted Shorts render worker started.")
    while True:
        try:
            claimed = process_one_job(admin, worker_id)
            if not claimed:
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            logger.info("Hosted Shorts render worker stopped.")
            return
        except Exception as exc:
            logger.warning("Hosted worker loop recovered from %s", type(exc).__name__)
            time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("NEXUS_LOG_LEVEL", "INFO").upper())
    run_worker()
