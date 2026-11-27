import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127091116_nexus_auth_identity_foundation.sql"


class SaaSIdentityMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_auth_user_insert_bootstraps_profile_and_workspace(self):
        self.assertIn("after insert on auth.users", self.sql)
        self.assertIn("private.bootstrap_nexus_auth_user()", self.sql)
        self.assertIn("insert into public.profiles", self.sql)
        self.assertIn("insert into public.workspaces", self.sql)
        self.assertIn("trg_workspace_owner_membership", self.sql)

    def test_profiles_are_self_scoped_and_rls_protected(self):
        self.assertIn("alter table public.profiles enable row level security", self.sql)
        self.assertIn("using ((select auth.uid()) = id)", self.sql)
        self.assertIn("with check ((select auth.uid()) = id)", self.sql)
        self.assertIn("revoke all on table public.profiles from anon, authenticated", self.sql)

    def test_workspace_membership_policy_avoids_recursive_policy_lookup(self):
        self.assertIn("private.is_workspace_owner(p_workspace_id text)", self.sql)
        self.assertIn("security definer", self.sql)
        self.assertIn("where w.workspace_id = p_workspace_id", self.sql)
        self.assertIn("and w.owner_id = (select auth.uid())", self.sql)
        self.assertIn("workspace_members_owner_insert", self.sql)
        self.assertIn("workspace_members_owner_update", self.sql)
        self.assertIn("workspace_members_owner_delete", self.sql)

    def test_privileged_helpers_are_not_publicly_executable(self):
        self.assertIn("revoke all on function private.is_workspace_owner(text) from public, anon", self.sql)
        self.assertIn("revoke all on function private.bootstrap_nexus_auth_user() from public, anon, authenticated", self.sql)
        self.assertNotIn("security definer", self.sql.split("create or replace function public.", 1)[-1] if "create or replace function public." in self.sql else "")

    def test_no_user_supplied_identity_is_used_for_authorization(self):
        self.assertNotIn("user_metadata", self.sql)
        self.assertNotIn("owner_user_id", self.sql)


if __name__ == "__main__":
    unittest.main()
