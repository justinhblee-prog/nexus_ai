import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from fastapi import HTTPException


class ApiReviewGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stubs = {
            "video_maker": types.ModuleType("video_maker"),
            "yt_uploader": types.ModuleType("yt_uploader"),
            "trend_radar": types.ModuleType("trend_radar"),
        }
        cls.module_patch = patch.dict(sys.modules, cls.stubs)
        cls.module_patch.start()
        sys.modules.pop("api_server", None)
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
        db = self.api.get_db()
        try:
            db.executemany(
                "INSERT INTO pipeline_jobs (channel_name,title,script,video_path,stage,created_at) VALUES (?,?,?,?,?,?)",
                [
                    ("Future Leak", "Pending", "script", "", "최종컨펌 대기", "now"),
                    ("Future Leak", "Rejected", "script", "", "반려(수정 필요)", "now"),
                    ("Future Leak", "Uploaded", "script", "", "업로드 완료(비공개)", "now"),
                ],
            )
            db.commit()
        finally:
            db.close()

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temp.cleanup()

    def _stage(self, job_id):
        db = self.api.get_db()
        try:
            return db.execute("SELECT stage FROM pipeline_jobs WHERE id=?", (job_id,)).fetchone()[0]
        finally:
            db.close()

    def test_edit_queues_regeneration_for_reviewable_or_rejected_jobs(self):
        revised_script = "첫째 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다."
        req = self.api.UpdateJobReq(title="Updated title", script=revised_script)
        result = self.api.update_job(1, req)
        self.assertTrue(result["queued"])
        self.assertEqual(self._stage(1), "재제작 대기")
        result = self.api.update_job(2, req)
        self.assertTrue(result["queued"])
        self.assertEqual(self._stage(2), "재제작 대기")
        with self.assertRaises(HTTPException) as caught:
            self.api.update_job(3, req)
        self.assertEqual(caught.exception.status_code, 409)
        db = self.api.get_db()
        try:
            queued = db.execute(
                "SELECT title_override, script_override, target_job_id, source FROM topic_queue ORDER BY id"
            ).fetchall()
            original = db.execute("SELECT title, script FROM pipeline_jobs WHERE id=1").fetchone()
        finally:
            db.close()
        self.assertEqual(queued[0]["title_override"], "Updated title")
        self.assertEqual(queued[0]["script_override"], revised_script)
        self.assertEqual(queued[0]["target_job_id"], 1)
        self.assertEqual(queued[0]["source"], "review_regeneration")
        self.assertEqual(original["title"], "Pending")
        self.assertEqual(original["script"], "script")

    def test_edit_rejects_empty_or_oversized_payload(self):
        with self.assertRaises(HTTPException) as empty:
            self.api.update_job(1, self.api.UpdateJobReq(title=" ", script="문장입니다. 문장입니다. 문장입니다. 문장입니다."))
        self.assertEqual(empty.exception.status_code, 400)
        with self.assertRaises(HTTPException) as oversized:
            self.api.update_job(1, self.api.UpdateJobReq(title="x" * 201, script="문장입니다. 문장입니다. 문장입니다. 문장입니다."))
        self.assertEqual(oversized.exception.status_code, 400)

    def test_edit_requires_four_to_eight_sentences(self):
        with self.assertRaises(HTTPException) as caught:
            self.api.update_job(
                1,
                self.api.UpdateJobReq(title="Updated", script="Only one sentence."),
            )
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(self._stage(1), "최종컨펌 대기")

    def test_failed_final_qa_blocks_upload_and_preserves_review_stage(self):
        os.makedirs("output", exist_ok=True)
        path = os.path.join("output", "candidate.mp4")
        with open(path, "wb") as handle:
            handle.write(b"test-video")
        db = self.api.get_db()
        try:
            db.execute("UPDATE pipeline_jobs SET video_path=? WHERE id=1", (path,))
            db.commit()
        finally:
            db.close()
        with patch.object(self.api, "validate_video", return_value={"ok": False, "errors": ["h264_video"]}), \
             patch.object(self.api.yt_uploader, "upload_to_youtube", create=True) as upload:
            with self.assertRaises(HTTPException) as caught:
                self.api.approve_job(1)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self._stage(1), "최종컨펌 대기")
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
