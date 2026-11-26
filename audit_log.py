"""Append-only operational events and lightweight SQLite metrics for NEXUS."""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta


def _connect(db_path):
    parent = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL DEFAULT 'system',
            entity_id TEXT,
            occurred_at TEXT NOT NULL,
            correlation_id TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_time ON audit_events(occurred_at DESC, id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type, occurred_at DESC)")
    return conn


def record_event(event_type, entity_type="system", entity_id=None, payload=None,
                 correlation_id=None, db_path="data/studio_data.db", occurred_at=None):
    """Persist one event. Callers must never pass passwords, tokens, or API keys."""
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("event_type is required")
    safe_payload = payload if isinstance(payload, dict) else {}
    encoded = json.dumps(safe_payload, ensure_ascii=False, sort_keys=True, default=str)
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            """INSERT INTO audit_events
               (event_id, event_type, entity_type, entity_id, occurred_at, correlation_id, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), event_type.strip(), entity_type or "system",
             None if entity_id is None else str(entity_id),
             occurred_at or datetime.now().isoformat(timespec="seconds"),
             correlation_id, encoded),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def list_events(db_path="data/studio_data.db", limit=50, event_type=None):
    limit = max(1, min(int(limit), 200))
    conn = _connect(db_path)
    try:
        if event_type:
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE event_type=? ORDER BY id DESC LIMIT ?",
                (event_type, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            result.append(item)
        return result
    finally:
        conn.close()


def get_ops_metrics(db_path="data/studio_data.db", now=None):
    """Return counts only; no credentials or user content are included."""
    conn = _connect(db_path)
    try:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        def grouped(table, column):
            if table not in tables:
                return {}
            return {row[0]: row[1] for row in conn.execute(
                f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column}"
            )}
        current = now or datetime.now()
        cutoff = (current - timedelta(hours=24)).isoformat(timespec="seconds")
        recent_events = conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE occurred_at >= ?", (cutoff,)
        ).fetchone()[0]
        latest = conn.execute(
            "SELECT event_type, occurred_at FROM audit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "queue_by_status": grouped("topic_queue", "status"),
            "scheduler_by_status": grouped("scheduler_runs", "status"),
            "pipeline_by_stage": grouped("pipeline_jobs", "stage"),
            "events_last_24h": recent_events,
            "latest_event": dict(latest) if latest else None,
        }
    finally:
        conn.close()


def safe_record_event(*args, **kwargs):
    """Audit failures must not change queue, render, scheduler, or upload outcomes."""
    import logging
    try:
        return record_event(*args, **kwargs)
    except Exception:
        logging.getLogger("nexus.audit").exception("Could not persist operational audit event")
        return None
