import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127130000_nexus_foreign_key_index_coverage.sql"


class NexusForeignKeyIndexCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_all_live_advisor_foreign_keys_have_covering_indexes(self):
        expected = [
            ("private.shorts_upload_leases", "(workspace_id, job_id)"),
            ("private.shorts_worker_leases", "(workspace_id, job_id)"),
            ("private.youtube_oauth_credentials", "(workspace_id, connection_id)"),
            ("private.youtube_oauth_states", "(user_id)"),
            ("private.youtube_oauth_states", "(workspace_id)"),
            ("public.shorts_assets", "(created_by)"),
            ("public.shorts_channels", "(created_by)"),
            ("public.shorts_channels", "(workspace_id, connection_id)"),
            ("public.shorts_job_events", "(actor_id)"),
            ("public.shorts_job_events", "(workspace_id, job_id)"),
            ("public.shorts_jobs", "(approved_by)"),
            ("public.shorts_jobs", "(created_by)"),
            ("public.shorts_jobs", "(workspace_id, channel_id)"),
            ("public.youtube_connections", "(connected_by)"),
        ]
        for table, columns in expected:
            with self.subTest(table=table, columns=columns):
                self.assertIn(f"on {table} {columns}", self.sql)

    def test_index_creation_is_repeatable_and_non_destructive(self):
        self.assertEqual(self.sql.count("create index if not exists"), 14)
        self.assertNotIn("drop index", self.sql)
        self.assertNotIn("drop table", self.sql)


if __name__ == "__main__":
    unittest.main()
