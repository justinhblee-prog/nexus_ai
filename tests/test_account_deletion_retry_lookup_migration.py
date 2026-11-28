import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127140000_nexus_account_deletion_retry_lookup.sql"


class AccountDeletionRetryLookupMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_lookup_is_read_only_and_returns_only_retry_metadata(self):
        self.assertIn("create or replace function public.get_account_deletion_request(p_user_id uuid)", self.sql)
        self.assertIn("returns table(status text, phase text, attempt_count integer, sessions_revoked boolean)", self.sql)
        self.assertIn("from private.account_deletion_requests as r", self.sql)
        self.assertIn("where r.user_id = p_user_id", self.sql)
        self.assertNotIn("insert into", self.sql)
        self.assertNotIn("update private.account_deletion_requests", self.sql)
        self.assertNotIn("delete from", self.sql)

    def test_lookup_is_service_role_only(self):
        self.assertIn("security definer", self.sql)
        self.assertIn("set search_path = ''", self.sql)
        self.assertIn("auth.jwt() ->> 'role'", self.sql)
        self.assertIn("revoke all on function public.get_account_deletion_request(uuid) from public, anon, authenticated", self.sql)
        self.assertIn("grant execute on function public.get_account_deletion_request(uuid) to service_role", self.sql)


if __name__ == "__main__":
    unittest.main()
