import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import trend_radar


class TrendRadarSmokeTests(unittest.TestCase):
    def test_database_initializes_required_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_path = trend_radar.DB_PATH
            trend_radar.DB_PATH = os.path.join(directory, "studio_data.db")
            try:
                connection = trend_radar.init_radar_db()
                try:
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    self.assertIn("trend_recommendations", tables)
                    self.assertIn("auto_produced_topics", tables)
                    self.assertIn("source_health", tables)
                    self.assertIn("radar_scans", tables)
                finally:
                    connection.close()
            finally:
                trend_radar.DB_PATH = previous_path

    def test_source_health_tracks_success_and_consecutive_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_path = trend_radar.DB_PATH
            trend_radar.DB_PATH = os.path.join(directory, "studio_data.db")
            try:
                connection = trend_radar.init_radar_db()
                try:
                    trend_radar.record_source_health(
                        connection, "KR", "Google News KR", "https://example.test/rss",
                        success=True, item_count=5, now="2026-11-26T10:00:00",
                    )
                    trend_radar.record_source_health(
                        connection, "KR", "Google News KR", "https://example.test/rss",
                        success=False, item_count=0, error="timeout", now="2026-11-26T10:05:00",
                    )
                    trend_radar.record_source_health(
                        connection, "KR", "Google News KR", "https://example.test/rss",
                        success=False, item_count=0, error="timeout", now="2026-11-26T10:10:00",
                    )
                    row = connection.execute(
                        "SELECT last_status, last_success_at, consecutive_failures, last_error FROM source_health WHERE source_name=?",
                        ("Google News KR",),
                    ).fetchone()
                finally:
                    connection.close()
            finally:
                trend_radar.DB_PATH = previous_path
        self.assertEqual(row[0], "failed")
        self.assertEqual(row[1], "2026-11-26T10:00:00")
        self.assertEqual(row[2], 2)
        self.assertEqual(row[3], "timeout")

    def test_channel_matching_is_deterministic(self):
        self.assertEqual(trend_radar.match_ch("an ordinary story"), "Brain Glitch")
        self.assertEqual(
            trend_radar.match_ch("AI chip breakthrough"),
            trend_radar.match_ch("AI chip breakthrough"),
        )

    def test_scan_persists_per_source_health_even_when_one_feed_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_path = trend_radar.DB_PATH
            trend_radar.DB_PATH = os.path.join(directory, "studio_data.db")
            try:
                def fake_parse(geo, label, url):
                    if label == "Google News JP":
                        return [], "timeout"
                    item = (geo, f"{label} headline", label, f"https://example.test/{geo.lower()}", None)
                    return [item], None

                with patch.object(trend_radar, "_fetch_hn", return_value=(
                    [("US", "HN headline", "Hacker News", "https://news.ycombinator.com/", 25)], None
                )), patch.object(trend_radar, "_parse_rss_safe", side_effect=fake_parse):
                    items = trend_radar.scan_global_trends("daily")

                connection = trend_radar.init_radar_db()
                try:
                    health = {
                        row[0]: (row[1], row[2], row[3])
                        for row in connection.execute(
                            "SELECT source_name, last_status, item_count, consecutive_failures FROM source_health"
                        )
                    }
                    scan = trend_radar.get_scan_status("daily")
                finally:
                    connection.close()
            finally:
                trend_radar.DB_PATH = previous_path
        self.assertEqual(len(items), 5)
        self.assertEqual(len(health), 6)
        self.assertEqual(health["Google News JP"], ("failed", 0, 1))
        self.assertEqual(health["Google News KR"], ("success", 1, 0))
        self.assertEqual(health["Hacker News"], ("success", 1, 0))
        self.assertEqual(scan["status"], "partial")
        self.assertEqual(scan["successful_sources"], 5)
        self.assertEqual(scan["failed_sources"], 1)

    def test_source_scores_keep_native_units_and_never_create_global_viral_rank(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_path = trend_radar.DB_PATH
            trend_radar.DB_PATH = os.path.join(directory, "studio_data.db")
            try:
                with patch.object(trend_radar, "_fetch_hn", return_value=(
                    [("US", "HN story", "Hacker News", "https://news.ycombinator.com/item?id=1", 37)], None
                )), patch.object(trend_radar, "_parse_rss_safe", return_value=(
                    [("KR", "RSS story", "Google News KR", "https://example.test/rss", None)], None
                )):
                    trend_radar.scan_global_trends("daily")
                conn = trend_radar.init_radar_db()
                conn.row_factory = sqlite3.Row
                try:
                    rows = [dict(row) for row in conn.execute(
                        """SELECT source_name, source_score, source_score_label, viral_score,
                                  is_global_top10, source_rank
                           FROM trend_recommendations WHERE period_type='daily'"""
                    )]
                finally:
                    conn.close()
            finally:
                trend_radar.DB_PATH = previous_path
        hn = next(row for row in rows if row["source_name"] == "Hacker News")
        rss = next(row for row in rows if row["source_name"] == "Google News KR")
        self.assertEqual(hn["source_score"], 37)
        self.assertEqual(hn["source_score_label"], "Hacker News points")
        self.assertIsNone(hn["viral_score"])
        self.assertIsNone(rss["source_score"])
        self.assertIsNone(rss["source_score_label"])
        self.assertTrue(all(row["viral_score"] is None for row in rows))
        self.assertTrue(all(row["is_global_top10"] == 0 for row in rows))

    def test_empty_failed_scan_keeps_last_good_data_and_marks_it_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_path = trend_radar.DB_PATH
            trend_radar.DB_PATH = os.path.join(directory, "studio_data.db")
            try:
                with patch.object(trend_radar, "_fetch_hn", return_value=(
                    [("US", "Existing HN story", "Hacker News", "https://news.ycombinator.com/item?id=2", 12)], None
                )), patch.object(trend_radar, "_parse_rss_safe", return_value=([], None)):
                    trend_radar.scan_global_trends("daily")
                with patch.object(trend_radar, "_fetch_hn", return_value=([], "network unavailable")), \
                     patch.object(trend_radar, "_parse_rss_safe", return_value=([], "feed unavailable")):
                    result = trend_radar.scan_global_trends("daily")
                conn = trend_radar.init_radar_db()
                try:
                    rows = conn.execute(
                        "SELECT topic FROM trend_recommendations WHERE period_type='daily'"
                    ).fetchall()
                finally:
                    conn.close()
                scan = trend_radar.get_scan_status("daily")
            finally:
                trend_radar.DB_PATH = previous_path
        self.assertEqual(result, [])
        self.assertEqual([row[0] for row in rows], ["Existing HN story"])
        self.assertEqual(scan["status"], "failed")
        self.assertEqual(scan["item_count"], 0)

    def test_legacy_recommendation_table_migrates_source_score_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_path = trend_radar.DB_PATH
            trend_radar.DB_PATH = os.path.join(directory, "studio_data.db")
            try:
                os.makedirs(directory, exist_ok=True)
                conn = sqlite3.connect(trend_radar.DB_PATH)
                conn.execute("""CREATE TABLE trend_recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, period_type TEXT, region TEXT,
                    rank_no INTEGER, is_global_top10 INTEGER, topic TEXT, matched_channel TEXT,
                    source_name TEXT, source_url TEXT, est_views INTEGER, avg_cat_views INTEGER,
                    growth_pct INTEGER, viral_score INTEGER, ai_reason TEXT, created_at TEXT
                )""")
                conn.commit()
                conn.close()
                conn = trend_radar.init_radar_db()
                try:
                    columns = {row[1] for row in conn.execute("PRAGMA table_info(trend_recommendations)")}
                finally:
                    conn.close()
            finally:
                trend_radar.DB_PATH = previous_path
        self.assertIn("source_rank", columns)
        self.assertIn("source_score", columns)
        self.assertIn("source_score_label", columns)

    def test_unknown_period_is_rejected(self):
        with self.assertRaises(ValueError):
            trend_radar.scan_global_trends("monthly")


if __name__ == "__main__":
    unittest.main()
