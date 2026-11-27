from pathlib import Path
import re
import unittest


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20261128100000_nexus_shared_public_trend_store.sql"
)


class SharedPublicTrendMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8")).lower()

    def test_tables_are_shared_and_have_stable_source_keys(self):
        self.assertIn("create table if not exists public.public_trend_signals", self.sql)
        self.assertIn("unique (period_type, region, source_name, topic)", self.sql)
        self.assertIn("create table if not exists public.public_trend_scans", self.sql)
        self.assertIn("period_type text primary key", self.sql)

    def test_authenticated_access_is_select_only_and_service_role_can_write(self):
        self.assertIn("alter table public.public_trend_signals enable row level security", self.sql)
        self.assertIn("alter table public.public_trend_scans enable row level security", self.sql)
        self.assertIn("revoke all on table public.public_trend_signals from public, anon, authenticated", self.sql)
        self.assertIn("grant select on table public.public_trend_signals to authenticated", self.sql)
        self.assertIn("grant select, insert, update, delete on table public.public_trend_signals to service_role", self.sql)
        self.assertIn("create policy public_trend_signals_authenticated_read", self.sql)
        self.assertNotRegex(self.sql, r"grant\s+[^;]*\b(insert|update|delete)\b[^;]*to\s+authenticated")

    def test_source_links_are_https_only_and_scan_metadata_is_bounded(self):
        self.assertIn("source_url is null or source_url ~ '^https://'", self.sql)
        self.assertIn("item_count integer not null default 0 check (item_count >= 0)", self.sql)
        self.assertIn("source_summary jsonb not null", self.sql)


if __name__ == "__main__":
    unittest.main()
