import importlib
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
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
        self.assertIn("lease_token", rows[0].keys())
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
        self.assertNotEqual(first["lease_token"], second["lease_token"])
        self.assertFalse(self.api.finish_topic(first["id"], first["lease_token"]))
        self.assertTrue(self.api.finish_topic(second["id"], second["lease_token"], "temporary failure"))

        db = self.api.get_db()
        try:
            db.execute("UPDATE topic_queue SET available_at=0 WHERE id=?", (second["id"],))
            db.commit()
        finally:
            db.close()

        third = self.api.claim_next_topic(lease_seconds=1)
        self.assertEqual(third["attempts"], 3)
        self.assertTrue(self.api.finish_topic(third["id"], third["lease_token"], "permanent failure"))
        self.assertIsNone(self.api.claim_next_topic())

        row = self._rows()[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 3)


    def test_stale_worker_cannot_finish_or_renew_reclaimed_lease(self):
        self.api.enqueue_topic("Future Leak | fenced lease", source="test")
        first = self.api.claim_next_topic(lease_seconds=60)
        db = self.api.get_db()
        try:
            db.execute("UPDATE topic_queue SET lease_until=0 WHERE id=?", (first["id"],))
            db.commit()
        finally:
            db.close()
        second = self.api.claim_next_topic(lease_seconds=60)
        self.assertNotEqual(first["lease_token"], second["lease_token"])
        self.assertFalse(self.api.renew_topic_lease(first["id"], first["lease_token"]))
        self.assertFalse(self.api.finish_topic(first["id"], first["lease_token"], "late failure"))
        self.assertTrue(self.api.renew_topic_lease(second["id"], second["lease_token"], lease_seconds=120))
        self.assertTrue(self.api.finish_topic(second["id"], second["lease_token"]))

    def test_existing_queue_schema_is_migrated_with_lease_token(self):
        db = self.api.get_db()
        try:
            db.execute("DROP TABLE topic_queue")
            db.execute("""CREATE TABLE topic_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL UNIQUE,
                channel_name TEXT, topic TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'api',
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                available_at INTEGER NOT NULL, lease_until INTEGER, last_error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            db.commit()
        finally:
            db.close()
        self.api.init_app_db()
        db = self.api.get_db()
        try:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(topic_queue)")}
        finally:
            db.close()
        self.assertIn("lease_token", columns)

    def test_concurrent_connections_cannot_claim_the_same_queue_item(self):
        self.api.enqueue_topic("Future Leak | one shared queue item", source="test")
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: self.api.claim_next_topic(lease_seconds=60), range(8)))
        claimed = [item for item in claims if item is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(len({item["id"] for item in claimed}), 1)
        row = self._rows()[0]
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["attempts"], 1)

    def test_concurrent_scheduler_claims_are_single_winner(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.api.claim_daily_schedule("parallel-day"), range(8)))
        self.assertEqual(sum(bool(result) for result in results), 1)

    def test_daily_scheduler_claim_is_idempotent_and_recovers_failed_run(self):
        first_token = self.api.claim_daily_schedule("2026-11-26", lease_seconds=60)
        self.assertTrue(first_token)
        self.assertFalse(self.api.claim_daily_schedule("2026-11-26"))
        self.assertTrue(self.api.finish_daily_schedule("2026-11-26", first_token, "temporary failure"))
        second_token = self.api.claim_daily_schedule("2026-11-26")
        self.assertTrue(second_token)
        self.assertTrue(self.api.finish_daily_schedule("2026-11-26", second_token))
        self.assertFalse(self.api.claim_daily_schedule("2026-11-26"))

    def test_stale_scheduler_owner_cannot_finish_reclaimed_run(self):
        first_token = self.api.claim_daily_schedule("fenced-day", lease_seconds=60)
        db = self.api.get_db()
        try:
            db.execute("UPDATE scheduler_runs SET lease_until=0 WHERE schedule_key='fenced-day'")
            db.commit()
        finally:
            db.close()
        second_token = self.api.claim_daily_schedule("fenced-day", lease_seconds=60)
        self.assertNotEqual(first_token, second_token)
        self.assertFalse(self.api.finish_daily_schedule("fenced-day", first_token))
        self.assertTrue(self.api.finish_daily_schedule("fenced-day", second_token))

    def test_existing_scheduler_schema_is_migrated_with_lease_token(self):
        db = self.api.get_db()
        try:
            db.execute("DROP TABLE scheduler_runs")
            db.execute("""CREATE TABLE scheduler_runs (
                schedule_key TEXT PRIMARY KEY, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, lease_until INTEGER,
                last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            db.commit()
        finally:
            db.close()
        self.api.init_app_db()
        db = self.api.get_db()
        try:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(scheduler_runs)")}
        finally:
            db.close()
        self.assertIn("lease_token", columns)

    def test_daily_radar_picks_enter_durable_queue_before_rendering(self):
        db = self.api.get_db()
        try:
            db.execute("""CREATE TABLE trend_recommendations (
                period_type TEXT, is_global_top10 INTEGER, topic TEXT, matched_channel TEXT
            )""")
            db.execute(
                "INSERT INTO trend_recommendations VALUES ('daily', 1, 'durable radar topic', 'Future Leak')"
            )
            db.commit()
        finally:
            db.close()

        with patch.object(self.api.trend_radar, "init_radar_db", self.api.get_db, create=True), \
             patch.object(self.api, "run_make_video", side_effect=AssertionError("must use durable queue")):
            self.assertEqual(self.api.auto_produce_top_trends(count=3), 1)
            self.assertEqual(self.api.auto_produce_top_trends(count=3), 0)

        row = self._rows()[0]
        self.assertEqual(row["source"], "daily_radar")
        self.assertEqual(row["status"], "pending")
        claimed = self.api.claim_next_topic()
        self.assertEqual(claimed["topic"], "durable radar topic")
        self.assertTrue(self.api.finish_topic(claimed["id"], claimed["lease_token"]))
        db = self.api.get_db()
        try:
            produced = db.execute(
                "SELECT topic FROM auto_produced_topics WHERE topic='durable radar topic'"
            ).fetchone()
        finally:
            db.close()
        self.assertIsNotNone(produced)

    def test_duplicate_active_channel_topic_is_not_enqueued_twice(self):
        first = self.api.enqueue_topic("Future Leak | active topic", source="manual")
        second = self.api.enqueue_topic("Future Leak | active topic", source="manual")
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "pending")

    def test_concurrent_duplicate_enqueue_has_single_winner(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: self.api.enqueue_topic("Future Leak | concurrent topic", source="manual"),
                range(8),
            ))
        self.assertEqual(sum(results), 1)
        self.assertEqual(len(self._rows()), 1)

    def test_manual_api_create_routes_through_durable_queue(self):
        request = self.api.CreateReq(channel_name="Future Leak", topic="API queued topic")
        result = self.api.create_single(request)
        self.assertEqual(result["queued"], 1)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "api_create")
        self.assertEqual(rows[0]["channel_name"], "Future Leak")
        self.assertEqual(rows[0]["topic"], "API queued topic")

    def test_create_all_queues_every_channel_without_inline_render(self):
        result = self.api.create_all()
        self.assertEqual(result["queued"], 10)
        rows = self._rows()
        self.assertEqual(len(rows), 10)
        self.assertEqual({row["source"] for row in rows}, {"api_create_all"})
        self.assertEqual({row["status"] for row in rows}, {"pending"})

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
