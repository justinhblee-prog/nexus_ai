"""Opt-in collector that publishes source-attributed public trends to Supabase."""
from __future__ import annotations

import logging
import os
import sqlite3
import time

import trend_radar
from supabase_admin import SupabaseAdminError, SupabaseAdminRestClient

logger = logging.getLogger("nexus.hosted_trend_worker")
BATCH_SIZE = 50


def _chunks(items, size=BATCH_SIZE):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def persist_period(admin, period_type: str, db_path: str | None = None) -> int:
    if period_type not in ("daily", "weekly"):
        raise ValueError("period_type must be daily or weekly")
    path = db_path or trend_radar.DB_PATH
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in conn.execute(
            """SELECT region, rank_no, topic, source_name, source_url,
                      source_score, source_score_label, growth_pct, viral_score,
                      ai_reason, created_at
               FROM trend_recommendations WHERE period_type=?
               ORDER BY rank_no, region, source_name, created_at DESC LIMIT 500""",
            (period_type,),
        ).fetchall()]
        scan_row = conn.execute(
            """SELECT status, started_at, completed_at, item_count,
                      successful_sources, failed_sources, source_summary_json
               FROM radar_scans WHERE period_type=?
               ORDER BY started_at DESC, id DESC LIMIT 1""",
            (period_type,),
        ).fetchone()
    finally:
        conn.close()

    payload = []
    for row in rows:
        topic = str(row.get("topic") or "").strip()
        source_name = str(row.get("source_name") or "").strip()
        if not topic or not source_name:
            continue
        source_url = str(row.get("source_url") or "")
        payload.append({
            "period_type": period_type,
            "region": str(row.get("region") or "UN"),
            "rank_no": max(1, int(row.get("rank_no") or 1)),
            "topic": topic[:500],
            "source_name": source_name[:120],
            "source_url": source_url if source_url.startswith("https://") else None,
            "source_score": row.get("source_score"),
            "source_score_label": row.get("source_score_label"),
            "growth_pct": row.get("growth_pct"),
            "viral_score": row.get("viral_score"),
            "ai_reason": row.get("ai_reason"),
            "created_at": row.get("created_at"),
        })
    for batch in _chunks(payload):
        admin.upsert_public_trend_signals(batch)

    if scan_row:
        try:
            import json
            source_summary = json.loads(scan_row["source_summary_json"] or "{}")
        except (TypeError, ValueError):
            source_summary = {}
        admin.upsert_public_trend_scan({
            "period_type": period_type,
            "status": scan_row["status"],
            "started_at": scan_row["started_at"],
            "completed_at": scan_row["completed_at"],
            "item_count": int(scan_row["item_count"] or 0),
            "successful_sources": int(scan_row["successful_sources"] or 0),
            "failed_sources": int(scan_row["failed_sources"] or 0),
            "source_summary": source_summary,
        })
    return len(payload)


def run_once(admin=None, scanner=None, db_path: str | None = None) -> dict:
    configured_path = db_path or os.getenv("NEXUS_TREND_RADAR_DB_PATH") or trend_radar.DB_PATH
    trend_radar.DB_PATH = configured_path
    os.environ["NEXUS_TREND_RADAR_DB_PATH"] = configured_path
    os.makedirs(os.path.dirname(os.path.abspath(configured_path)), exist_ok=True)
    if scanner is None:
        scanner = trend_radar.scan_global_trends
    if admin is None:
        admin = SupabaseAdminRestClient()
    result = {}
    cycle_errors = []
    for period in ("daily", "weekly"):
        try:
            scanner(period)
        except Exception as exc:
            # The scanner normally records its failed scan in SQLite before
            # re-raising. Publish that health record, but keep the cycle failed
            # so the outer worker loop retries rather than silently accepting it.
            cycle_errors.append((period, "scan", exc))
            logger.warning("Trend scan failed for %s (%s)", period, type(exc).__name__)
        try:
            result[period] = persist_period(admin, period, trend_radar.DB_PATH)
        except Exception as exc:
            cycle_errors.append((period, "persistence", exc))
            logger.warning("Trend persistence failed for %s (%s)", period, type(exc).__name__)
    if cycle_errors:
        failed_periods = ", ".join(f"{period} {stage}" for period, stage, _ in cycle_errors)
        raise RuntimeError(f"Trend collection cycle failed: {failed_periods}") from cycle_errors[0][2]
    return result


def run_worker():
    if os.getenv("NEXUS_TREND_WORKER_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.info("Hosted trend worker is disabled; no collection or writes will occur.")
        return
    try:
        poll_seconds = max(3600, min(86400, int(os.getenv("NEXUS_TREND_WORKER_POLL_SECONDS", "21600"))))
    except ValueError:
        poll_seconds = 21600
    admin = SupabaseAdminRestClient()
    logger.info("Hosted public trend collector started.")
    while True:
        try:
            logger.info("Persisted trend scan counts: %s", run_once(admin=admin))
        except KeyboardInterrupt:
            logger.info("Hosted public trend collector stopped.")
            return
        except Exception as exc:
            logger.warning("Hosted trend collection failed (%s)", type(exc).__name__)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("NEXUS_LOG_LEVEL", "INFO").upper())
    try:
        run_worker()
    except SupabaseAdminError as exc:
        logger.error("Hosted trend worker configuration is invalid (%s)", type(exc).__name__)
