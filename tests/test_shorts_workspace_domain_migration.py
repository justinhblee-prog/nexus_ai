import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127092414_nexus_shorts_workspace_domain.sql"


class ShortsWorkspaceDomainMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_shorts_domain_tables_are_workspace_scoped(self):
        for table in (
            "youtube_connections", "shorts_channels", "shorts_jobs",
            "shorts_job_events", "shorts_analytics_snapshots", "shorts_assets",
        ):
            self.assertIn(f"create table if not exists public.{table}", self.sql)
            self.assertIn(f"alter table public.{table} enable row level security", self.sql)
        self.assertIn("foreign key (workspace_id, channel_id)", self.sql)

    def test_role_helper_uses_verified_auth_uid_and_is_private(self):
        self.assertIn("private.has_workspace_role", self.sql)
        self.assertIn("wm.user_id = (select auth.uid())", self.sql)
        self.assertIn("revoke all on function private.has_workspace_role(text, text[]) from public, anon", self.sql)

    def test_oauth_refresh_tokens_and_state_are_private_and_not_client_granted(self):
        self.assertIn("create table if not exists private.youtube_oauth_credentials", self.sql)
        self.assertIn("encrypted_refresh_token bytea not null", self.sql)
        self.assertIn("create table if not exists private.youtube_oauth_states", self.sql)
        self.assertIn("alter table private.youtube_oauth_credentials enable row level security", self.sql)
        self.assertIn("alter table private.youtube_oauth_states enable row level security", self.sql)
        self.assertIn("revoke all on table private.youtube_oauth_credentials, private.youtube_oauth_states from public, anon, authenticated", self.sql)

    def test_job_approval_is_owner_admin_only_and_private_by_default(self):
        self.assertIn("privacy_status text not null default 'private'", self.sql)
        self.assertIn("check (privacy_status = 'private')", self.sql)
        self.assertIn("private.guard_shorts_job_approval()", self.sql)
        self.assertIn("array['owner','admin']", self.sql)
        self.assertIn("approval must be attributed to the authenticated reviewer", self.sql)
        self.assertIn("stage not in ('approved', 'uploading', 'published') or approval_status = 'approved'", self.sql)
        self.assertIn("stage <> 'published' or (provider_video_id is not null and uploaded_at is not null)", self.sql)

    def test_client_grants_prevent_tenant_and_pipeline_control_field_reassignment(self):
        self.assertIn("grant update (display_name, persona, is_active, updated_at)", self.sql)
        self.assertIn("grant update (topic, title, script, updated_at, approval_status, approved_by, approved_at)", self.sql)
        self.assertNotIn("grant update on public.shorts_jobs", self.sql)
        self.assertNotIn("grant insert, update, delete on public.shorts_jobs", self.sql)

    def test_every_workspace_data_policy_is_authenticated_and_membership_scoped(self):
        tables = (
            "youtube_connections", "shorts_channels", "shorts_jobs",
            "shorts_job_events", "shorts_analytics_snapshots", "shorts_assets",
        )
        for table in tables:
            self.assertIn(f"alter table public.{table} enable row level security", self.sql)
            self.assertIn(f"{table}_member_read", self.sql)
            self.assertIn(f"private.has_workspace_role({table}.workspace_id", self.sql)
        self.assertIn("to authenticated", self.sql)
        self.assertNotIn("to anon", self.sql)
        self.assertNotIn("using (true)", self.sql)
        self.assertNotIn("with check (true)", self.sql)

    def test_workspace_membership_helper_cannot_trust_client_supplied_user_ids(self):
        helper_start = self.sql.index("create or replace function private.has_workspace_role")
        helper_end = self.sql.index("$function$;", helper_start)
        helper = self.sql[helper_start:helper_end]
        self.assertIn("security definer", helper)
        self.assertIn("set search_path = ''", helper)
        self.assertIn("wm.user_id = (select auth.uid())", helper)
        self.assertIn("wm.workspace_id = p_workspace_id", helper)
        self.assertIn("wm.role = any(p_allowed_roles)", helper)
        self.assertNotIn("auth.jwt()", helper)

    def test_workspace_update_policies_prevent_cross_workspace_row_reassignment(self):
        for table in ("shorts_channels", "shorts_jobs", "shorts_assets", "youtube_connections"):
            start = self.sql.index(f"create policy {table}_")
            end = self.sql.find(";", start)
            section = self.sql[start:end]
            update_start = section.find("for update")
            if update_start >= 0:
                update_policy = section[update_start:]
                self.assertIn("using", update_policy)
                self.assertIn("with check", update_policy)
                self.assertIn("private.has_workspace_role", update_policy)

    def test_read_and_write_policies_are_role_scoped(self):
        self.assertIn("shorts_jobs_member_read", self.sql)
        self.assertIn("shorts_jobs_editor_insert", self.sql)
        self.assertIn("shorts_jobs_admin_delete", self.sql)
        self.assertIn("youtube_connections_admin_insert", self.sql)
        self.assertIn("shorts_analytics_member_read", self.sql)


if __name__ == "__main__":
    unittest.main()
