import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127123000_nexus_account_deletion_oauth_retry_state.sql"


class AccountDeletionOAuthRetryMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_checkpoint_table_stores_only_hashed_provider_identity_and_state(self):
        self.assertIn("private.account_deletion_oauth_states", self.sql)
        self.assertIn("provider_account_hash text not null", self.sql)
        self.assertIn("provider_account_hash ~ '^[0-9a-f]{64}$'", self.sql)
        self.assertIn("references private.account_deletion_requests(user_id)", self.sql)
        self.assertNotIn("refresh_token", self.sql)
        self.assertIn("enable row level security", self.sql)
        self.assertIn("from public, anon, authenticated", self.sql)

    def test_checkpoint_rpcs_are_service_role_only_and_terminal_states_are_monotonic(self):
        self.assertIn("create or replace function public.get_account_deletion_oauth_state", self.sql)
        self.assertIn("create or replace function public.set_account_deletion_oauth_state", self.sql)
        self.assertIn("auth.jwt()->>'role'", self.sql)
        self.assertIn("service_role required", self.sql)
        self.assertIn("state in ('revoked','preserved','not_required')", self.sql)
        self.assertIn("grant execute on function public.get_account_deletion_oauth_state(uuid,text) to service_role", self.sql)
        self.assertIn("grant execute on function public.set_account_deletion_oauth_state(uuid,text,text) to service_role", self.sql)


if __name__ == "__main__":
    unittest.main()
