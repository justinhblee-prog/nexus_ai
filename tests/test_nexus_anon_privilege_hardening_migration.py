import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127160000_nexus_anon_privilege_hardening.sql"


class NexusAnonPrivilegeHardeningMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_current_tenant_tables_revoke_all_anon_privileges(self):
        self.assertIn("revoke all on table", self.sql)
        for table in (
            "public.workspaces",
            "public.workspace_members",
            "public.youtube_connections",
            "public.shorts_channels",
            "public.shorts_jobs",
            "public.shorts_job_events",
            "public.shorts_analytics_snapshots",
            "public.shorts_assets",
            "public.assets",
            "public.character_assets",
            "public.character_bundle_imports",
            "public.characters",
            "public.gallery_images",
            "public.generation_jobs",
        ):
            self.assertIn(table, self.sql)
        self.assertIn("from anon", self.sql)

    def test_future_public_tables_do_not_inherit_anon_privileges(self):
        self.assertIn("alter default privileges for role postgres in schema public", self.sql)
        self.assertNotIn("alter default privileges for role supabase_admin", self.sql)
        self.assertEqual(self.sql.count("revoke all on tables from anon"), 1)

    def test_supabase_admin_and_storage_owner_acl_followup_is_documented_separately(self):
        admin_doc = (ROOT / "docs" / "SUPABASE_ADMIN_DEFAULT_PRIVILEGES.md").read_text(encoding="utf-8").lower()
        admin_sql = (ROOT / "supabase" / "operations" / "nexus_admin_anon_acl_hardening.sql").read_text(encoding="utf-8").lower()
        self.assertIn("alter default privileges for role supabase_admin in schema public", admin_sql)
        self.assertIn("alter default privileges for role supabase_admin in schema public", admin_sql)
        self.assertIn("alter default privileges for role supabase_admin in schema public", admin_sql)
        self.assertIn("revoke all on sequences from anon", admin_sql)
        self.assertIn("revoke all on table storage.objects from anon", admin_sql)
        self.assertIn("set role supabase_admin", admin_sql)
        self.assertIn("partially complete", admin_doc)

    def test_authenticated_and_service_role_grants_are_not_revoked(self):
        self.assertNotIn("from authenticated", self.sql)
        self.assertNotIn("from service_role", self.sql)


if __name__ == "__main__":
    unittest.main()
