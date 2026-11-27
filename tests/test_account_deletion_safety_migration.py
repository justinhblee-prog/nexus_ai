import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127110000_nexus_account_deletion_safety.sql"


class AccountDeletionSafetyMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_storage_inventory_rpc_is_service_role_only_and_paginates(self):
        self.assertIn("create or replace function public.list_account_deletion_storage_objects", self.sql)
        self.assertIn("p_limit integer default 1000", self.sql)
        self.assertIn("p_offset integer default 0", self.sql)
        self.assertIn("p_workspace_ids text[] default array[]::text[]", self.sql)
        self.assertIn("limit p_limit offset p_offset", self.sql)
        self.assertIn("where item.workspace_id !~ '^wsp_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", self.sql)
        self.assertIn("where o.owner = p_user_id", self.sql)
        self.assertIn("or o.owner_id = p_user_id::text", self.sql)
        self.assertIn("split_part(o.name, '/', 1) = any(p_workspace_ids)", self.sql)
        self.assertIn("from public.gallery_images as gi", self.sql)
        self.assertIn("o.name in (gi.storage_key, gi.thumbnail_key)", self.sql)
        self.assertIn("revoke all on function public.list_account_deletion_storage_objects(uuid,integer,integer,text[])", self.sql)
        self.assertIn("to service_role", self.sql)

    def test_active_worker_lease_inventory_is_service_role_only(self):
        self.assertIn("create or replace function public.list_account_deletion_active_leases", self.sql)
        self.assertIn("from private.shorts_worker_leases", self.sql)
        self.assertIn("from private.shorts_upload_leases", self.sql)
        self.assertIn("revoke all on function public.list_account_deletion_active_leases(text[])", self.sql)
        self.assertIn("grant execute on function public.list_account_deletion_active_leases(text[]) to service_role", self.sql)

    def test_tombstone_survives_auth_user_deletion_and_is_self_scoped(self):
        self.assertIn("create table if not exists private.account_deletion_tombstones", self.sql)
        self.assertNotIn("user_id uuid references auth.users", self.sql)
        self.assertIn("create or replace function public.mark_account_deletion_tombstone", self.sql)
        self.assertIn("create or replace function public.is_account_deletion_tombstoned", self.sql)
        self.assertIn("v_user_id := (select auth.uid())", self.sql)
        self.assertIn("grant execute on function public.is_account_deletion_tombstoned() to authenticated", self.sql)

    def test_tombstoned_owner_workspaces_are_excluded_from_new_worker_claims(self):
        render_start = self.sql.index("create or replace function public.claim_next_shorts_job")
        render_end = self.sql.index("create or replace function public.claim_next_approved_shorts_job", render_start)
        render_claim = self.sql[render_start:render_end]
        upload_start = self.sql.index("create or replace function public.claim_next_approved_shorts_job")
        upload_end = self.sql.index("create table if not exists private.account_deletion_requests", upload_start)
        upload_claim = self.sql[upload_start:upload_end]
        for claim in (render_claim, upload_claim):
            self.assertIn("not exists", claim)
            self.assertIn("join private.account_deletion_tombstones as t", claim)
            self.assertIn("t.user_id", claim)
            self.assertIn("w.owner_id", claim)
            self.assertIn("where w.workspace_id", claim)

    def test_durable_queue_is_atomic_and_service_role_only(self):
        self.assertIn("create table if not exists private.account_deletion_worker_heartbeats", self.sql)
        self.assertIn("create or replace function public.heartbeat_account_deletion_worker", self.sql)
        self.assertIn("create or replace function public.is_account_deletion_worker_online", self.sql)
        self.assertIn("interval '90 seconds'", self.sql)
        self.assertIn("interval '1 day'", self.sql)
        self.assertIn("create table if not exists private.account_deletion_requests", self.sql)
        self.assertIn("sessions_revoked boolean not null default false", self.sql)
        self.assertIn("create or replace function public.enqueue_account_deletion", self.sql)
        self.assertIn("insert into private.account_deletion_tombstones(user_id)", self.sql)
        self.assertIn("insert into private.account_deletion_requests(user_id,preflight_snapshot)", self.sql)
        self.assertIn("create or replace function public.claim_next_account_deletion_request", self.sql)
        self.assertIn("r.sessions_revoked = true", self.sql)
        self.assertIn("limit 1 for update skip locked", self.sql)
        self.assertIn("create or replace function public.mark_account_deletion_sessions_revoked", self.sql)
        self.assertIn("create or replace function public.heartbeat_account_deletion_request", self.sql)
        self.assertIn("create or replace function public.update_account_deletion_request", self.sql)
        self.assertIn("create or replace function public.delete_account_deletion_private_user_rows", self.sql)
        self.assertIn("create or replace function public.count_account_deletion_private_user_rows", self.sql)
        self.assertIn("grant execute on function public.enqueue_account_deletion(uuid,jsonb) to service_role", self.sql)
        self.assertIn("grant execute on function public.claim_next_account_deletion_request(text,integer) to service_role", self.sql)
        self.assertIn("grant execute on function public.mark_account_deletion_sessions_revoked(uuid) to service_role", self.sql)
        self.assertIn("grant execute on function public.heartbeat_account_deletion_request(uuid,text,integer) to service_role", self.sql)
        self.assertIn("grant execute on function public.update_account_deletion_request(uuid,text,text,text,text,integer) to service_role", self.sql)

    def test_shared_legacy_authorship_columns_can_be_anonymized(self):
        self.assertIn("alter table public.assets alter column owner_id drop not null", self.sql)
        self.assertIn("alter table public.characters alter column owner_id drop not null", self.sql)
        self.assertIn("alter table public.generation_jobs alter column owner_id drop not null", self.sql)
        self.assertIn("alter table public.character_bundle_imports alter column user_id drop not null", self.sql)

    def test_reviewer_fk_anonymization_does_not_weaken_authenticated_approval_guard(self):
        self.assertIn("create or replace function private.guard_shorts_job_approval()", self.sql)
        self.assertIn("current_user in ('postgres', 'supabase_auth_admin', 'service_role')", self.sql)
        self.assertIn("old.approved_by is not null", self.sql)
        self.assertIn("new.approved_by is null", self.sql)
        self.assertIn("new.approved_at is not distinct from old.approved_at", self.sql)
        self.assertIn("new.stage is not distinct from old.stage", self.sql)
        self.assertIn("if not (select private.has_workspace_role(new.workspace_id, array['owner','admin']))", self.sql)

    def test_workspace_ownership_transfer_requires_current_owner_and_existing_admin(self):
        self.assertIn("create or replace function public.transfer_workspace_ownership", self.sql)
        self.assertIn("v_current_owner <> (select auth.uid())", self.sql)
        self.assertIn("and wm.role = 'admin'", self.sql)
        self.assertIn("when user_id = p_new_owner_id then 'owner'", self.sql)
        self.assertIn("when user_id = v_current_owner then 'admin'", self.sql)
        self.assertIn("revoke all on function public.transfer_workspace_ownership(text, uuid) from public, anon", self.sql)
        self.assertIn("grant execute on function public.transfer_workspace_ownership(text, uuid) to authenticated", self.sql)


if __name__ == "__main__":
    unittest.main()
