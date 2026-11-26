import os
import tempfile
import unittest

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
                finally:
                    connection.close()
            finally:
                trend_radar.DB_PATH = previous_path

    def test_channel_matching_is_deterministic(self):
        self.assertEqual(trend_radar.match_ch("an ordinary story"), "Brain Glitch")
        self.assertEqual(
            trend_radar.match_ch("AI chip breakthrough"),
            trend_radar.match_ch("AI chip breakthrough"),
        )

    def test_unknown_period_is_rejected(self):
        with self.assertRaises(ValueError):
            trend_radar.scan_global_trends("monthly")


if __name__ == "__main__":
    unittest.main()
