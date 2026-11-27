import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127093918_nexus_approval_stage_transition.sql"


class ApprovalStageTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_approval_and_rejection_drive_server_controlled_job_stages(self):
        self.assertIn("new.stage := 'approved'", self.sql)
        self.assertIn("new.stage := 'cancelled'", self.sql)
        self.assertIn("only workspace owners or admins may approve shorts jobs", self.sql)
        self.assertIn("new.approved_by is distinct from (select auth.uid())", self.sql)


if __name__ == "__main__":
    unittest.main()
