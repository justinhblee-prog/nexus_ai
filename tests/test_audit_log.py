import json
import os
import tempfile
import unittest
from datetime import datetime

from audit_log import get_ops_metrics, list_events, record_event


class AuditLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "data", "test.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_event_is_persisted_and_payload_round_trips(self):
        event_id = record_event(
            "queue.enqueued", entity_type="topic_queue", entity_id=17,
            payload={"source": "api", "count": 2}, db_path=self.db_path,
            occurred_at="2026-11-26T12:00:00",
        )
        self.assertGreater(event_id, 0)
        events = list_events(self.db_path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "queue.enqueued")
        self.assertEqual(events[0]["entity_id"], "17")
        self.assertEqual(events[0]["payload"], {"count": 2, "source": "api"})

    def test_event_filter_and_limit_are_applied(self):
        record_event("render.started", db_path=self.db_path)
        record_event("render.completed", db_path=self.db_path)
        record_event("render.completed", db_path=self.db_path)
        self.assertEqual(len(list_events(self.db_path, limit=1)), 1)
        self.assertEqual(len(list_events(self.db_path, event_type="render.completed")), 2)

    def test_metrics_cover_existing_queue_scheduler_and_pipeline_tables(self):
        import sqlite3
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE topic_queue(status TEXT, created_at TEXT);
            INSERT INTO topic_queue VALUES
                ('pending', '2026-11-26T10:00:00'), ('running', '2026-11-26T11:00:00'),
                ('pending', '2026-11-26T12:00:00');
            CREATE TABLE scheduler_runs(status TEXT);
            INSERT INTO scheduler_runs VALUES ('completed');
            CREATE TABLE pipeline_jobs(stage TEXT);
            INSERT INTO pipeline_jobs VALUES ('최종컨펌 대기'), ('업로드 완료(비공개)');
            CREATE TABLE source_health(source_name TEXT, region TEXT, last_attempt_at TEXT,
                last_success_at TEXT, last_status TEXT, item_count INTEGER,
                consecutive_failures INTEGER, last_error TEXT);
            INSERT INTO source_health VALUES ('Google News KR', 'KR', '2026-11-26T12:00:00',
                '2026-11-26T12:00:00', 'success', 8, 0, NULL);
            INSERT INTO source_health VALUES ('BBC News', 'GB', '2026-11-26T12:00:00',
                NULL, 'failed', 0, 2, 'timeout');
            CREATE TABLE radar_scans (
                id INTEGER PRIMARY KEY, period_type TEXT, started_at TEXT, completed_at TEXT,
                status TEXT, item_count INTEGER, successful_sources INTEGER, failed_sources INTEGER
            );
            INSERT INTO radar_scans VALUES
                (1, 'daily', '2026-11-26T12:00:00', '2026-11-26T12:01:00', 'partial', 18, 5, 1),
                (2, 'weekly', '2026-11-26T11:00:00', '2026-11-26T11:01:00', 'success', 30, 6, 0);
        """)
        conn.commit()
        conn.close()
        record_event("scheduler.completed", db_path=self.db_path)
        metrics = get_ops_metrics(self.db_path)
        self.assertEqual(metrics["queue_by_status"], {"pending": 2, "running": 1})
        self.assertEqual(metrics["scheduler_by_status"], {"completed": 1})
        self.assertEqual(metrics["pipeline_by_stage"], {"최종컨펌 대기": 1, "업로드 완료(비공개)": 1})
        self.assertEqual(metrics["events_last_24h"], 1)
        self.assertEqual(metrics["latest_event"]["event_type"], "scheduler.completed")
        self.assertEqual(metrics["source_health_summary"], {"success": 1, "failed": 1})
        self.assertEqual(len(metrics["sources"]), 2)
        self.assertEqual(metrics["radar_scans"]["daily"]["status"], "partial")
        self.assertEqual(metrics["radar_scans"]["weekly"]["item_count"], 30)
        self.assertEqual(metrics["oldest_pending_queue_created_at"], "2026-11-26T10:00:00")

    def test_invalid_event_type_is_rejected(self):
        with self.assertRaises(ValueError):
            record_event("", db_path=self.db_path)


if __name__ == "__main__":
    unittest.main()
