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


    def test_render_job_and_queue_completion_commit_atomically(self):
        self.api.enqueue_topic("Future Leak | atomic render", source="daily_radar")
        item = self.api.claim_next_topic(lease_seconds=60)
        with patch.object(self.api.video_maker, "render_pro_short",
                          return_value=("output/atomic.mp4", "Atomic title", "Atomic script"), create=True), \
             patch.object(self.api, "validate_video", return_value={"ok": True, "checks": {}, "errors": []}):
            job_id = self.api.run_make_video(
                "Future Leak", "persona", "atomic render",
                queue_id=item["id"], lease_token=item["lease_token"],
            )
        db = self.api.get_db()
        try:
            job = db.execute("SELECT id, stage FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()
            queue = db.execute("SELECT status, lease_token FROM topic_queue WHERE id=?", (item["id"],)).fetchone()
            produced = db.execute(
                "SELECT topic FROM auto_produced_topics WHERE topic='atomic render'"
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(job["stage"], "최종컨펌 대기")
        self.assertEqual(queue["status"], "completed")
        self.assertIsNone(queue["lease_token"])
        self.assertIsNotNone(produced)

    def test_edited_job_regenerates_in_place_before_final_review(self):
        db = self.api.get_db()
        try:
            db.execute(
                "INSERT INTO pipeline_jobs (channel_name,title,script,video_path,stage,created_at) VALUES (?,?,?,?,?,?)",
                ("Future Leak", "Old title", "Old script", "output/old.mp4", "반려(수정 필요)", "now"),
            )
            db.commit()
        finally:
            db.close()
        revised_title = "Revised title"
        revised_script = "첫째 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다."
        queue_id = self.api.enqueue_job_regeneration(1, revised_title, revised_script)
        self.assertEqual(self._stage_for_test(1), "재제작 대기")
        item = self.api.claim_next_topic(lease_seconds=60)
        self.assertEqual(item["id"], queue_id)
        with patch.object(self.api.video_maker, "render_pro_short",
                          return_value=("output/revised.mp4", revised_title, revised_script), create=True) as render, \
             patch.object(self.api, "validate_video", return_value={"ok": True, "checks": {}, "errors": []}):
            job_id = self.api.run_make_video(
                "Future Leak", "persona", item["topic"],
                queue_id=item["id"], lease_token=item["lease_token"],
                script_override=item["script_override"], title_override=item["title_override"],
                target_job_id=item["target_job_id"],
            )
        self.assertEqual(job_id, 1)
        self.assertEqual(render.call_args.kwargs["script_override"], revised_script)
        self.assertEqual(render.call_args.kwargs["title_override"], revised_title)
        db = self.api.get_db()
        try:
            job = db.execute("SELECT title, script, video_path, stage FROM pipeline_jobs WHERE id=1").fetchone()
            queue = db.execute("SELECT status FROM topic_queue WHERE id=?", (queue_id,)).fetchone()
        finally:
            db.close()
        self.assertEqual(tuple(job), (revised_title, revised_script, "output/revised.mp4", "최종컨펌 대기"))
        self.assertEqual(queue["status"], "completed")

    def _stage_for_test(self, job_id):
        db = self.api.get_db()
        try:
            return db.execute("SELECT stage FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()[0]
        finally:
            db.close()

    def test_expired_max_attempt_regeneration_lease_marks_job_failed(self):
        db = self.api.get_db()
        try:
            db.execute(
                "INSERT INTO pipeline_jobs (channel_name,title,script,video_path,stage,created_at) VALUES (?,?,?,?,?,?)",
                ("Future Leak", "Old title", "Old script", "output/old.mp4", "반려(수정 필요)", "now"),
            )
            db.commit()
        finally:
            db.close()
        queue_id = self.api.enqueue_job_regeneration(
            1, "Revised title",
            "첫째 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다.",
        )
        item = self.api.claim_next_topic(lease_seconds=60)
        db = self.api.get_db()
        try:
            db.execute("UPDATE topic_queue SET lease_until=0, attempts=3 WHERE id=?", (queue_id,))
            db.commit()
        finally:
            db.close()
        self.assertIsNone(self.api.claim_next_topic())
        self.assertEqual(self._stage_for_test(1), "재제작 실패")

    def test_failed_regeneration_moves_job_to_retryable_failure_state(self):
        db = self.api.get_db()
        try:
            db.execute(
                "INSERT INTO pipeline_jobs (channel_name,title,script,video_path,stage,created_at) VALUES (?,?,?,?,?,?)",
                ("Future Leak", "Old title", "Old script", "output/old.mp4", "반려(수정 필요)", "now"),
            )
            db.commit()
        finally:
            db.close()
        queue_id = self.api.enqueue_job_regeneration(
            1, "Revised title",
            "첫째 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다.",
        )
        item = self.api.claim_next_topic(lease_seconds=60)
        db = self.api.get_db()
        try:
            db.execute("UPDATE topic_queue SET attempts=3 WHERE id=?", (queue_id,))
            db.commit()
        finally:
            db.close()
        self.assertTrue(self.api.finish_topic(queue_id, item["lease_token"], "render failed"))
        self.assertEqual(self._stage_for_test(1), "재제작 실패")

    def test_stale_render_cannot_commit_pipeline_job(self):
        self.api.enqueue_topic("Future Leak | stale render", source="test")
        item = self.api.claim_next_topic(lease_seconds=60)
        with patch.object(self.api.video_maker, "render_pro_short",
                          return_value=("output/stale.mp4", "Stale title", "Stale script"), create=True), \
             patch.object(self.api, "validate_video", return_value={"ok": True, "checks": {}, "errors": []}):
            with self.assertRaisesRegex(RuntimeError, "lease was lost"):
                self.api.run_make_video(
                    "Future Leak", "persona", "stale render",
                    queue_id=item["id"], lease_token="not-the-current-token",
                )
        db = self.api.get_db()
        try:
            count = db.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(count, 0)

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
        self.assertIn("title_override", columns)
        self.assertIn("script_override", columns)
        self.assertIn("target_job_id", columns)

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

    def test_batch_queue_rejects_unknown_channels_and_malformed_lines(self):
        with self.assertRaises(Exception) as unknown:
            self.api.save_queue(self.api.QueueReq(topics_text="Missing Channel | topic"))
        self.assertEqual(getattr(unknown.exception, "status_code", None), 400)
        with self.assertRaises(Exception) as malformed:
            self.api.save_queue(self.api.QueueReq(topics_text="Future Leak | "))
        self.assertEqual(getattr(malformed.exception, "status_code", None), 400)
        self.assertEqual(len(self._rows()), 0)

    def test_batch_queue_enforces_payload_and_item_limits(self):
        with self.assertRaises(Exception) as oversized:
            self.api.save_queue(self.api.QueueReq(topics_text="x" * 20001))
        self.assertEqual(getattr(oversized.exception, "status_code", None), 413)
        with self.assertRaises(Exception) as too_many:
            self.api.save_queue(self.api.QueueReq(topics_text="\n".join(f"topic {i}" for i in range(101))))
        self.assertEqual(getattr(too_many.exception, "status_code", None), 400)
        self.assertEqual(len(self._rows()), 0)

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
