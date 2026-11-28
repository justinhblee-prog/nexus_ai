from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HostedAnalyticsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = (ROOT / "api_server.py").read_text(encoding="utf-8")
        cls.workspace = (ROOT / "workspace.html").read_text(encoding="utf-8")

    def test_analytics_route_is_workspace_member_scoped(self):
        start = self.api.index('def hosted_workspace_analytics(')
        end = self.api.index('@app.post("/api/hosted/workspaces/{workspace_id}/jobs")', start)
        route = self.api[start:end]
        self.assertIn('client.select("workspace_members"', route)
        self.assertIn('"workspace_id": f"eq.{workspace_id}"', route)
        self.assertIn('"user_id": f"eq.{user[\'user_id\']}"', route)
        self.assertIn('client.select("youtube_connections"', route)
        self.assertIn('"provider": "eq.youtube"', route)
        self.assertIn('"status": "eq.connected"', route)

    def test_analytics_uses_encrypted_server_credentials_and_read_only_scopes(self):
        start = self.api.index('def hosted_workspace_analytics(')
        end = self.api.index('@app.post("/api/hosted/workspaces/{workspace_id}/jobs")', start)
        route = self.api[start:end]
        self.assertIn("admin.get_credential(connection_id)", route)
        self.assertIn("decrypt_refresh_token(", route)
        self.assertIn("yt-analytics.readonly", route)
        self.assertIn("youtube.readonly", route)
        self.assertIn('build("youtubeAnalytics", "v2"', route)
        self.assertNotIn("youtube.upload", route)
        self.assertNotIn("refresh_token\": refresh_token", route)

    def test_metrics_are_real_and_unavailable_values_are_null(self):
        start = self.api.index('def hosted_workspace_analytics(')
        end = self.api.index('@app.post("/api/hosted/workspaces/{workspace_id}/jobs")', start)
        route = self.api[start:end]
        self.assertIn('"source": "YouTube Analytics API"', route)
        self.assertIn('"views": None', route)
        self.assertIn('"engagement_rate": None', route)
        self.assertIn('"status": "partial"', route)
        self.assertIn('"status": "scope_required"', route)
        self.assertIn("최근 완료된 28일", route)

    def test_dashboard_and_analytics_views_consume_tenant_metrics(self):
        self.assertIn("/api/hosted/workspaces/'+id+'/analytics", self.workspace)
        self.assertIn("an.views", self.workspace)
        self.assertIn("an.watch_minutes", self.workspace)
        self.assertIn("dashboard-analytics", self.workspace)
        self.assertIn("analytics-status", self.workspace)
        self.assertIn("reauth_required", self.workspace)

    def test_discovery_preserves_scan_metadata_and_source_rankings(self):
        self.assertIn("trends=tr", self.workspace)
        self.assertIn("result.scan||{}", self.workspace)
        self.assertIn("t.rank_no", self.workspace)
        self.assertIn("t.source_score", self.workspace)
        self.assertIn("t.growth_pct", self.workspace)
        self.assertIn('rel="noopener noreferrer"', self.workspace)


if __name__ == "__main__":
    unittest.main()
