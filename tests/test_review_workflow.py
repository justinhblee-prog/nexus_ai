import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from review_workflow import claim_upload, upload_result_stage


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "studio.db")
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE pipeline_jobs(id INTEGER PRIMARY KEY, stage TEXT NOT NULL)")
        conn.execute("INSERT INTO pipeline_jobs(id, stage) VALUES (1, '최종컨펌 대기')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp.cleanup()

    def _claim(self, _):
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            result = claim_upload(conn, 1)
            conn.commit()
            return result
        finally:
            conn.close()

    def test_only_one_concurrent_request_claims_upload(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self._claim, range(8)))
        self.assertEqual(sum(results), 1)
        conn = sqlite3.connect(self.path)
        try:
            stage = conn.execute("SELECT stage FROM pipeline_jobs WHERE id=1").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(stage, "업로드 진행 중")

    def test_upload_outcomes_map_to_safe_stages(self):
        self.assertEqual(upload_result_stage(True), "업로드 완료(비공개)")
        self.assertEqual(upload_result_stage(False, True), "업로드 상태 확인 필요")
        self.assertEqual(upload_result_stage(False), "최종컨펌 대기")


if __name__ == "__main__":
    unittest.main()
