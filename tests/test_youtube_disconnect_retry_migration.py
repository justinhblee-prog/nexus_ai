import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20261127150000_nexus_youtube_disconnect_retry_state.sql"


class YouTubeDisconnectRetryMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_checkpoint_is_private_and_bound_to_connection(self):
        self.assertIn("create table if not exists private.youtube_oauth_disconnect_states", self.sql)
        self.assertIn("connection_id uuid primary key references public.youtube_connections(connection_id) on delete cascade", self.sql)
        self.assertIn("alter table private.youtube_oauth_disconnect_states enable row level security", self.sql)
        self.assertIn("revoke all on table private.youtube_oauth_disconnect_states from public, anon, authenticated", self.sql)

    def test_rpc_is_service_role_only_and_terminal_states_are_monotonic(self):
        self.assertIn("auth.jwt()->>'role'", self.sql)
        self.assertIn("security definer set search_path=''", self.sql)
        self.assertIn("revoke all on function public.get_youtube_disconnect_state(uuid) from public,anon,authenticated", self.sql)
        self.assertIn("grant execute on function public.get_youtube_disconnect_state(uuid) to service_role", self.sql)
        self.assertIn("grant execute on function public.set_youtube_disconnect_state(uuid,text) to service_role", self.sql)
        self.assertIn("state in ('revoked','preserved','not_required')", self.sql)


if __name__ == "__main__":
    unittest.main()
