import os
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
                finally:
                    connection.close()
            finally:
                trend_radar.DB_PATH = previous_path
        self.assertEqual(len(items), 5)
        self.assertEqual(len(health), 6)
        self.assertEqual(health["Google News JP"], ("failed", 0, 1))
        self.assertEqual(health["Google News KR"], ("success", 1, 0))
        self.assertEqual(health["Hacker News"], ("success", 1, 0))

    def test_unknown_period_is_rejected(self):
        with self.assertRaises(ValueError):
            trend_radar.scan_global_trends("monthly")


if __name__ == "__main__":
    unittest.main()
