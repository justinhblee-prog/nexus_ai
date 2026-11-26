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

    def test_edit_is_limited_to_reviewable_or_rejected_jobs(self):
        req = self.api.UpdateJobReq(title="Updated title", script="Updated script")
        self.assertTrue(self.api.update_job(1, req)["ok"])
        self.assertEqual(self._stage(1), "최종컨펌 대기")
        self.assertTrue(self.api.update_job(2, req)["ok"])
        self.assertEqual(self._stage(2), "최종컨펌 대기")
        with self.assertRaises(HTTPException) as caught:
            self.api.update_job(3, req)
        self.assertEqual(caught.exception.status_code, 409)

    def test_edit_rejects_empty_or_oversized_payload(self):
        with self.assertRaises(HTTPException) as empty:
            self.api.update_job(1, self.api.UpdateJobReq(title=" ", script="script"))
        self.assertEqual(empty.exception.status_code, 400)
        with self.assertRaises(HTTPException) as oversized:
            self.api.update_job(1, self.api.UpdateJobReq(title="x" * 201, script="script"))
        self.assertEqual(oversized.exception.status_code, 400)

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
