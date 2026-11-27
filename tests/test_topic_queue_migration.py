from pathlib import Path
import re
import unittest


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20261127143658_nexus_user_workspace_topic_queue.sql"
)


class HostedTopicQueueMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = re.sub(r"\s+", " ", cls.sql).lower()

    def test_table_is_scoped_to_workspace_and_auth_user(self):
        self.assertIn("create table if not exists public.shorts_topic_queue", self.normalized)
        self.assertRegex(
            self.normalized,
            r"workspace_id text not null references public\.workspaces\(workspace_id\) on delete cascade",
        )
        self.assertRegex(
            self.normalized,
            r"user_id uuid not null references auth\.users\(id\) on delete cascade",
        )

    def test_topic_normalization_and_input_constraints_are_present(self):
        self.assertIn("normalized_topic text generated always as", self.normalized)
        self.assertIn("lower(regexp_replace(btrim(topic)", self.normalized)
        self.assertIn("unique (workspace_id, user_id, normalized_topic)", self.normalized)
        self.assertIn("char_length(btrim(topic)) between 1 and 300", self.normalized)
        self.assertIn("source_url is null or source_url ~ '^https://'", self.normalized)

    def test_rls_is_enabled_and_all_policies_bind_user_and_workspace(self):
        self.assertIn("alter table public.shorts_topic_queue enable row level security", self.normalized)
        policies = re.findall(
            r"create policy shorts_topic_queue_member_(?:read|insert|delete).*?;",
            self.normalized,
        )
        self.assertEqual(len(policies), 3)
        for policy in policies:
            self.assertIn("user_id = (select auth.uid())", policy)
            self.assertIn("private.has_workspace_role(", policy)
            self.assertIn("workspace_id", policy)

    def test_client_privileges_are_minimal_and_no_update_is_granted(self):
        self.assertIn(
            "revoke all on table public.shorts_topic_queue from public, anon, authenticated",
            self.normalized,
        )
        self.assertIn(
            "grant select, insert, delete on table public.shorts_topic_queue to authenticated",
            self.normalized,
        )
        self.assertNotRegex(
            self.normalized,
            r"grant\s+[^;]*\bupdate\b[^;]*on\s+(?:table\s+)?public\.shorts_topic_queue",
        )
        self.assertNotIn("to service_role", self.normalized)


if __name__ == "__main__":
    unittest.main()
