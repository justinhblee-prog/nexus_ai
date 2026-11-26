import importlib
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


def _stub(name):
    module = types.ModuleType(name)
    return module


class DurableTopicQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The queue tests do not exercise rendering, YouTube, or external trend feeds.
        stubs = {
            "video_maker": _stub("video_maker"),
            "yt_uploader": _stub("yt_uploader"),
            "trend_radar": _stub("trend_radar"),
        }
        cls.module_patch = patch.dict(sys.modules, stubs)
        cls.module_patch.start()
        cls.api = importlib.import_module("api_server")

    @classmethod
    def tearDownClass(cls):
        cls.module_patch.stop()
        sys.modules.pop("api_server", None)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_cwd = os.getcwd()
        os.chdir(self.temp.name)
        self.api.init_app_db()

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def _rows(self):
        db = self.api.get_db()
        try:
            return db.execute("SELECT * FROM topic_queue ORDER BY id").fetchall()
        finally:
            db.close()

    def test_plain_topic_expands_to_channel_scoped_jobs(self):
        added = self.api.enqueue_topic("A test topic", source="test")
        self.assertEqual(added, 10)
        rows = self._rows()
        self.assertEqual(len(rows), 10)
        self.assertEqual({row["status"] for row in rows}, {"pending"})
        self.assertEqual(len({row["channel_name"] for row in rows}), 10)

    def test_claim_lease_and_retry_limit(self):
        self.api.enqueue_topic("Future Leak | AI chip test", source="test")
        first = self.api.claim_next_topic(lease_seconds=1)
        self.assertIsNotNone(first)
        self.assertEqual(first["attempts"], 1)

        db = self.api.get_db()
        try:
            db.execute("UPDATE topic_queue SET lease_until=0 WHERE id=?", (first["id"],))
            db.commit()
        finally:
            db.close()

        second = self.api.claim_next_topic(lease_seconds=1)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["attempts"], 2)
        self.api.finish_topic(second["id"], "temporary failure")

        db = self.api.get_db()
        try:
            db.execute("UPDATE topic_queue SET available_at=0 WHERE id=?", (second["id"],))
            db.commit()
        finally:
            db.close()

        third = self.api.claim_next_topic(lease_seconds=1)
        self.assertEqual(third["attempts"], 3)
        self.api.finish_topic(third["id"], "permanent failure")
        self.assertIsNone(self.api.claim_next_topic())

        row = self._rows()[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 3)


    def test_daily_scheduler_claim_is_idempotent_and_recovers_failed_run(self):
        self.assertTrue(self.api.claim_daily_schedule("2026-11-26", lease_seconds=1))
        self.assertFalse(self.api.claim_daily_schedule("2026-11-26"))
        self.api.finish_daily_schedule("2026-11-26", "temporary failure")
        self.assertTrue(self.api.claim_daily_schedule("2026-11-26"))
        self.api.finish_daily_schedule("2026-11-26")
        self.assertFalse(self.api.claim_daily_schedule("2026-11-26"))

    def test_legacy_file_import_is_idempotent_and_clears_after_commit(self):
        with open("topics.txt", "w", encoding="utf-8") as handle:
            handle.write("Future Leak | imported topic\n")
        self.api.import_legacy_topics_file()
        self.api.import_legacy_topics_file()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel_name"], "Future Leak")
        self.assertEqual(rows[0]["topic"], "imported topic")
        with open("topics.txt", "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "")


if __name__ == "__main__":
    unittest.main()
