import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127093911_nexus_hosted_render_worker.sql"


class HostedRenderWorkerMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_worker_leases_are_private_and_service_role_only(self):
        self.assertIn("create table if not exists private.shorts_worker_leases", self.sql)
        self.assertIn("alter table private.shorts_worker_leases enable row level security", self.sql)
        self.assertIn("revoke all on table private.shorts_worker_leases from public, anon, authenticated", self.sql)
        for function in ("claim_next_shorts_job", "heartbeat_shorts_job", "finish_shorts_job"):
            self.assertIn(f"public.{function}", self.sql)
            self.assertIn(f"to service_role", self.sql)
        self.assertEqual(len(re.findall(r"language plpgsql\s+security definer", self.sql)), 3)

    def test_worker_uses_skip_locked_leases_and_fencing_tokens(self):
        self.assertIn("for update of j skip locked", self.sql)
        self.assertIn("gen_random_uuid()::text", self.sql)
        self.assertIn("lease_token = p_lease_token", self.sql)
        self.assertIn("lease_until > now()", self.sql)
        self.assertIn("attempts < p_max_attempts", self.sql)

    def test_successful_render_waits_for_human_review(self):
        self.assertIn("set stage = 'review_pending'", self.sql)
        self.assertIn("left(p_output_storage_key, length(v_lease.workspace_id) + 1) <> v_lease.workspace_id || '/'", self.sql)
        self.assertIn("'render.completed'", self.sql)
        self.assertIn("'render.failed'", self.sql)
        self.assertIn("set stage = v_next_stage", self.sql)

    def test_private_storage_bucket_is_not_public_and_has_workspace_policies(self):
        self.assertIn("'nexus-shorts', 'nexus-shorts', false, 104857600", self.sql)
        self.assertIn("nexus_shorts_member_read", self.sql)
        self.assertIn("nexus_shorts_editor_insert", self.sql)
        self.assertIn("nexus_shorts_admin_delete", self.sql)
        self.assertIn("private.has_workspace_role((storage.foldername(name))[1]", self.sql)


if __name__ == "__main__":
    unittest.main()
