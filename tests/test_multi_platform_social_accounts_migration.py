import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261128110000_nexus_multi_platform_social_accounts.sql"


class MultiPlatformSocialAccountsMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_provider_constraints_cover_the_initial_platform_set(self):
        expected = "'youtube', 'tiktok', 'instagram', 'facebook', 'linkedin'"
        self.assertIn("check (provider in (" + expected + "))", self.sql)
        self.assertIn("check (platform in (" + expected + "))", self.sql)
        self.assertIn("p_provider not in (" + expected + ")", self.sql)

    def test_existing_workspace_and_connection_keys_are_preserved(self):
        self.assertIn("idx_youtube_connections_workspace_provider_status", self.sql)
        self.assertIn("idx_shorts_channels_workspace_platform_active", self.sql)
        self.assertIn("legacy physical name", self.sql)
        self.assertNotIn("drop table", self.sql)
        self.assertNotIn("delete from", self.sql)

    def test_oauth_state_rpc_remains_service_role_only(self):
        self.assertIn("security definer", self.sql)
        self.assertIn("set search_path = ''", self.sql)
        self.assertIn("coalesce(auth.jwt() ->> 'role', '') <> 'service_role'", self.sql)
        self.assertIn("revoke all on function public.store_youtube_oauth_state", self.sql)
        self.assertIn("to service_role", self.sql)


if __name__ == "__main__":
    unittest.main()
