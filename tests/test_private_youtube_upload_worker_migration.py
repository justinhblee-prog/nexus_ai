import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127094903_nexus_private_youtube_upload_worker.sql"


class PrivateYouTubeUploadWorkerMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_upload_queue_is_private_and_service_role_only(self):
        self.assertIn("create table if not exists private.shorts_upload_leases", self.sql)
        self.assertIn("alter table private.shorts_upload_leases enable row level security", self.sql)
        self.assertIn("claim_next_approved_shorts_job", self.sql)
        self.assertIn("record_shorts_upload_video_id", self.sql)
        self.assertIn("finish_shorts_upload", self.sql)
        self.assertIn("to service_role", self.sql)
        self.assertRegex(self.sql, r"from\s+public\s*,\s*anon\s*,\s*authenticated")

    def test_only_approved_private_jobs_are_claimed_with_daily_quota_cap(self):
        self.assertIn("j.approval_status='approved'", self.sql)
        self.assertIn("j.privacy_status='private'", self.sql)
        self.assertIn("p_daily_limit not between 1 and 3", self.sql)
        self.assertIn("america/los_angeles", self.sql)
        self.assertIn("for update of j skip locked", self.sql)

    def test_completion_requires_verified_channel_and_private_visibility(self):
        self.assertIn("c.provider_channel_id=p_verified_channel_id", self.sql)
        self.assertIn("p_privacy_status<>'private'", self.sql)
        self.assertIn("v_lease.privacy_status is distinct from 'private'", self.sql)
        self.assertIn("set stage='published'", self.sql)


if __name__ == "__main__":
    unittest.main()
