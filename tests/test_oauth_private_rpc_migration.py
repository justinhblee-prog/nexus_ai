import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127093000_nexus_oauth_private_rpc.sql"


class OAuthPrivateRpcMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_oauth_state_is_one_time_and_expiring(self):
        self.assertIn("add column if not exists code_verifier text", self.sql)
        self.assertIn("add column if not exists return_uri text", self.sql)
        self.assertIn("s.consumed_at is null", self.sql)
        self.assertIn("s.expires_at > now()", self.sql)
        self.assertIn("set consumed_at = now()", self.sql)

    def test_private_credential_read_write_uses_server_only_rpc(self):
        for name in (
            "store_youtube_oauth_state", "consume_youtube_oauth_state",
            "upsert_youtube_oauth_credential", "get_youtube_oauth_credential",
            "delete_youtube_oauth_credential",
        ):
            self.assertIn(f"public.{name}", self.sql)
            self.assertIn(f"to service_role", self.sql)
        self.assertIn("auth.jwt() ->> 'role', '') <> 'service_role'", self.sql)
        self.assertIn("revoke all on function public.get_youtube_oauth_credential(uuid) from public, anon, authenticated", self.sql)

    def test_functions_have_fixed_search_path_and_validate_state_inputs(self):
        self.assertEqual(self.sql.count("security definer"), 5)
        self.assertEqual(self.sql.count("set search_path = ''"), 5)
        self.assertIn("p_state_hash !~ '^[0-9a-f]{64}$'", self.sql)
        self.assertIn("p_expires_at > now() + interval '10 minutes'", self.sql)
        self.assertIn("octet_length(p_encrypted_refresh_token) < 28", self.sql)


if __name__ == "__main__":
    unittest.main()
