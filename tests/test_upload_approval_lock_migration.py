import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127094918_nexus_upload_approval_lock.sql"


class UploadApprovalLockMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_approval_cannot_be_changed_after_upload_starts(self):
        self.assertIn("old.stage in ('uploading','published')", self.sql)
        self.assertIn("approval cannot be changed after private youtube upload has started", self.sql)


if __name__ == "__main__":
    unittest.main()
