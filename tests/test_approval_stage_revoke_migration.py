import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127093927_nexus_approval_stage_revoke.sql"


class ApprovalStageRevokeMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_revoking_approval_returns_job_to_review_pending(self):
        self.assertIn("new.stage := 'review_pending'", self.sql)
        self.assertIn("new.approval_status = 'pending'", self.sql)
        self.assertIn("new.approved_by := null", self.sql)
        self.assertIn("new.approved_at := null", self.sql)
        self.assertIn("revoke all on function private.guard_shorts_job_approval()", self.sql)


if __name__ == "__main__":
    unittest.main()
