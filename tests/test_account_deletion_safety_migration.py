import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127110000_nexus_account_deletion_safety.sql"


class AccountDeletionSafetyMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_shared_workspace_author_records_are_preserved_as_null(self):
        for table, column in (
            ("youtube_connections", "connected_by"),
            ("shorts_channels", "created_by"),
            ("shorts_jobs", "created_by"),
            ("shorts_assets", "created_by"),
        ):
            self.assertIn(f"alter table public.{table}", self.sql)
            self.assertIn(f"alter column {column} drop not null", self.sql)
            self.assertIn(f"foreign key ({column}) references auth.users(id) on delete set null", self.sql)

    def test_approval_and_event_audit_references_are_anonymized_not_cascaded(self):
        self.assertIn("foreign key (actor_id) references auth.users(id) on delete set null", self.sql)
        self.assertIn("foreign key (approved_by) references auth.users(id) on delete set null", self.sql)
        self.assertIn("drop constraint if exists shorts_jobs_check", self.sql)
        self.assertIn("approval_status = 'approved' and approved_at is not null", self.sql)

    def test_reviewer_fk_anonymization_does_not_weaken_authenticated_approval_guard(self):
        self.assertIn("create or replace function private.guard_shorts_job_approval()", self.sql)
        self.assertIn("(select auth.uid()) is null", self.sql)
        self.assertIn("current_user in ('postgres', 'supabase_auth_admin', 'service_role')", self.sql)
        self.assertIn("old.approval_status = 'approved'", self.sql)
        self.assertIn("new.approval_status = 'approved'", self.sql)
        self.assertIn("old.approved_by is not null", self.sql)
        self.assertIn("new.approved_by is null", self.sql)
        self.assertIn("new.approved_at is not distinct from old.approved_at", self.sql)
        self.assertIn("new.stage is not distinct from old.stage", self.sql)
        self.assertIn("approval must be attributed to the authenticated reviewer", self.sql)

    def test_ownership_transfer_requires_authenticated_current_owner(self):
        self.assertIn("create or replace function public.transfer_workspace_ownership", self.sql)
        self.assertIn("security definer", self.sql)
        self.assertIn("set search_path = ''", self.sql)
        self.assertIn("if (select auth.uid()) is null", self.sql)
        self.assertIn("v_current_owner <> (select auth.uid())", self.sql)

    def test_new_owner_must_already_be_admin_and_old_owner_becomes_admin(self):
        self.assertIn("and wm.role = 'admin'", self.sql)
        self.assertIn("when user_id = p_new_owner_id then 'owner'", self.sql)
        self.assertIn("when user_id = v_current_owner then 'admin'", self.sql)

    def test_ownership_transfer_is_not_publicly_callable(self):
        self.assertIn("revoke all on function public.transfer_workspace_ownership(text, uuid) from public, anon", self.sql)
        self.assertIn("grant execute on function public.transfer_workspace_ownership(text, uuid) to authenticated", self.sql)


if __name__ == "__main__":
    unittest.main()
