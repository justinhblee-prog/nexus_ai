import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hosted_trend_store import read_shared_trends
from hosted_trend_worker import persist_period


class SharedTrendStoreTests(unittest.TestCase):
    def test_reader_returns_deduplicated_safe_shared_feed_and_scan_status(self):
        client = Mock()
        client.select.side_effect = [
            [
                {"topic": "AI News", "source_url": "https://example.test/a", "rank_no": 1},
                {"topic": " ai   news ", "source_url": "javascript:alert(1)", "rank_no": 2},
                {"topic": "Robotics", "source_url": "http://example.test/b", "rank_no": 3},
            ],
            [{"status": "partial", "item_count": 3, "source_summary": {"Feed": {"status": "failed"}}}],
        ]
        result = read_shared_trends(client)
        self.assertEqual([item["topic"] for item in result["items"]], ["AI News", "Robotics"])
        self.assertEqual(result["items"][0]["source_url"], "https://example.test/a")
        self.assertIsNone(result["items"][1]["source_url"])
        self.assertEqual(result["scan"]["status"], "partial")
        self.assertTrue(result["available"])

    def test_reader_reports_unavailable_when_store_has_no_scan_or_items(self):
        client = Mock()
        client.select.side_effect = [[], []]
        result = read_shared_trends(client)
        self.assertEqual(result["items"], [])
        self.assertFalse(result["available"])
        self.assertEqual(result["scan"]["status"], "not_scanned")


class SharedTrendPersistenceTests(unittest.TestCase):
    def test_persist_period_upserts_source_rows_and_scan_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE trend_recommendations (
                    period_type TEXT, region TEXT, rank_no INTEGER, topic TEXT,
                    source_name TEXT, source_url TEXT, source_score INTEGER,
                    source_score_label TEXT, growth_pct INTEGER, viral_score INTEGER,
                    ai_reason TEXT, created_at TEXT
                );
                CREATE TABLE radar_scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_type TEXT, status TEXT, started_at TEXT, completed_at TEXT,
                    item_count INTEGER, successful_sources INTEGER, failed_sources INTEGER,
                    source_summary_json TEXT
                );
            """)
            conn.execute(
                "INSERT INTO trend_recommendations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("daily", "KR", 1, "Topic", "Feed", "https://example.test", 10,
                 "source points", None, None, "source rank", "2026-11-28T00:00:00"),
            )
            conn.execute(
                """INSERT INTO radar_scans
                   (period_type,status,started_at,completed_at,item_count,
                    successful_sources,failed_sources,source_summary_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                ("daily", "partial", "2026-11-28T00:00:00", "2026-11-28T00:01:00",
                 1, 1, 1, json.dumps({"Feed": {"status": "success"}, "Broken Feed": {"status": "failed"}})),
            )
            conn.commit()
            conn.close()
            admin = Mock()
            count = persist_period(admin, "daily", str(path))
            self.assertEqual(count, 1)
            payload = admin.upsert_public_trend_signals.call_args.args[0]
            self.assertEqual(payload[0]["topic"], "Topic")
            self.assertEqual(payload[0]["source_url"], "https://example.test")
            scan = admin.upsert_public_trend_scan.call_args.args[0]
            self.assertEqual(scan["status"], "partial")
            self.assertEqual(scan["source_summary"]["Feed"]["status"], "success")
            admin.delete_stale_public_trend_signals.assert_called_once_with(
                "daily", "Feed", "2026-11-28T00:00:00"
            )

    def test_run_once_honors_configured_persistent_database_path(self):
        import os
        from unittest.mock import patch
        import hosted_trend_worker as worker

        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "persistent" / "radar.db")
            scanner = Mock()
            admin = Mock()
            with patch.dict(os.environ, {"NEXUS_TREND_RADAR_DB_PATH": path}), \
                 patch.object(worker.trend_radar, "DB_PATH", "default.db"), \
                 patch.object(worker, "persist_period", return_value=4) as persist:
                result = worker.run_once(admin=admin, scanner=scanner)
                self.assertEqual(worker.trend_radar.DB_PATH, path)
                self.assertEqual(result, {"daily": 4, "weekly": 4})
                self.assertEqual([call.args[0] for call in scanner.call_args_list], ["daily", "weekly"])
                self.assertEqual(persist.call_args_list[0].args, (admin, "daily", path))
                self.assertTrue(Path(path).parent.is_dir())

    def test_run_once_publishes_failed_scan_health_and_continues_other_period(self):
        import os
        import hosted_trend_worker as worker

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "radar.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE trend_recommendations (
                    period_type TEXT, region TEXT, rank_no INTEGER, topic TEXT,
                    source_name TEXT, source_url TEXT, source_score INTEGER,
                    source_score_label TEXT, growth_pct INTEGER, viral_score INTEGER,
                    ai_reason TEXT, created_at TEXT
                );
                CREATE TABLE radar_scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, period_type TEXT,
                    status TEXT, started_at TEXT, completed_at TEXT, item_count INTEGER,
                    successful_sources INTEGER, failed_sources INTEGER, source_summary_json TEXT
                );
            """)
            conn.execute(
                "INSERT INTO radar_scans (period_type,status,started_at,source_summary_json) VALUES (?,?,?,?)",
                ("daily", "running", "2026-11-28T00:00:00", "{}"),
            )
            conn.commit()
            conn.close()

            def scanner(period):
                conn = sqlite3.connect(path)
                try:
                    if period == "daily":
                        conn.execute(
                            """INSERT INTO radar_scans
                               (period_type,status,started_at,completed_at,item_count,
                                successful_sources,failed_sources,source_summary_json)
                               VALUES (?,?,?,?,?,?,?,?)""",
                            ("daily", "failed", "2026-11-28T00:00:00", "2026-11-28T00:01:00",
                             0, 0, 5, json.dumps({"scan_error": "TimeoutError"})),
                        )
                        conn.commit()
                        raise TimeoutError("temporary feed failure")
                    conn.execute(
                        """INSERT INTO radar_scans
                           (period_type,status,started_at,completed_at,item_count,
                            successful_sources,failed_sources,source_summary_json)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        ("weekly", "success", "2026-11-28T00:02:00", "2026-11-28T00:03:00",
                         2, 5, 0, "{}"),
                    )
                    conn.commit()
                finally:
                    conn.close()

            admin = Mock()
            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(worker.trend_radar, "DB_PATH", str(path)):
                with self.assertRaisesRegex(RuntimeError, "daily scan"):
                    worker.run_once(admin=admin, scanner=scanner, db_path=str(path))

            self.assertEqual(
                [call.args[0]["status"] for call in admin.upsert_public_trend_scan.call_args_list],
                ["failed", "success"],
            )
            self.assertEqual(admin.upsert_public_trend_scan.call_args_list[0].args[0]["failed_sources"], 5)

    def test_persist_period_rejects_unknown_period(self):
        with self.assertRaises(ValueError):
            persist_period(Mock(), "monthly", "unused.db")


if __name__ == "__main__":
    unittest.main()
