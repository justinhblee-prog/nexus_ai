import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127094359_nexus_worker_claim_ambiguous_fix.sql"


class WorkerClaimAmbiguousFixMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_claim_uses_named_primary_key_constraint_to_avoid_output_parameter_collision(self):
        self.assertIn("on conflict on constraint shorts_worker_leases_pkey do update", self.sql)
        self.assertIn("for update of j skip locked", self.sql)
        self.assertIn("to service_role", self.sql)


if __name__ == "__main__":
    unittest.main()
