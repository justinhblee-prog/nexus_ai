from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HostedWorkspaceMetricsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = (ROOT / "api_server.py").read_text(encoding="utf-8")
        cls.rest = (ROOT / "supabase_rest.py").read_text(encoding="utf-8")

    def test_overview_uses_exact_rls_filtered_counts_without_row_limit(self):
        start = self.api.index('def hosted_workspace_overview(')
        end = self.api.index('@app.get("/api/hosted/workspaces/{workspace_id}/trends")', start)
        route = self.api[start:end]
        self.assertEqual(route.count('client.count('), 6)
        self.assertIn('"workspace_id": f"eq.{workspace_id}"', route)
        self.assertIn('"is_active": "eq.true"', route)
        self.assertIn('"stage": "eq.queued"', route)
        self.assertIn('"approval_status": "eq.pending"', route)
        self.assertIn('"stage": "eq.published"', route)
        self.assertNotIn('"limit":', route)
        self.assertNotIn('client.select("shorts_jobs"', route)

    def test_count_uses_head_exact_preference_and_requires_content_range(self):
        start = self.rest.index('    def count(')
        end = self.rest.index('    def insert(', start)
        method = self.rest[start:end]
        self.assertIn('"HEAD"', method)
        self.assertIn('"Prefer": "count=exact"', method)
        self.assertIn('"Range": "0-0"', method)
        self.assertIn('response.headers.get("Content-Range")', method)
        self.assertIn('raise SupabaseRestError(502, "Supabase did not return an exact row count")', method)
        self.assertIn('if table not in _ALLOWED_TABLES:', method)


    def test_trend_panel_distinguishes_missing_hosted_store_from_empty_scan(self):
        html = (ROOT / "signup.html").read_text(encoding="utf-8")
        self.assertIn('result.available === false', html)
        self.assertIn("공유 트렌드 데이터 저장소 연결 대기", html)
        self.assertIn("호스팅 환경에 공유 트렌드 데이터 저장소가 아직 연결되지 않았습니다.", html)



    def test_hosted_jobs_ui_supports_offset_pagination_and_context_guard(self):
        html = (ROOT / "signup.html").read_text(encoding="utf-8")
        self.assertIn("/jobs?limit=50&offset=", html)
        self.assertIn("data-load-more", html)
        self.assertIn("이전 작업 더 불러오기", html)
        self.assertIn("requestedWorkspaceId !== activeWorkspaceId", html)
        self.assertIn("requestedToken !== activeAccessToken", html)



if __name__ == "__main__":
    unittest.main()
