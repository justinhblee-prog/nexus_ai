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



    def test_topic_queue_ui_uses_server_storage_and_preserves_local_fallback(self):
        html = (ROOT / "signup.html").read_text(encoding="utf-8")
        self.assertIn('"/topic-queue"', html)
        self.assertIn('method: "POST"', html)
        self.assertIn('method: "DELETE"', html)
        self.assertIn("서버 저장 · 이 계정의 워크스페이스 주제 큐", html)
        self.assertIn("현재 브라우저 임시 저장을 사용합니다.", html)
        self.assertIn("readSavedTopicQueue()", html)
        self.assertIn("savedTopicQueueMode = serverAvailable ? \"server\" : \"local\"", html)
        self.assertIn("remainingLocalItems", html)
        self.assertIn("migrationResponse.status !== 409", html)
        self.assertIn("workspaceId !== activeWorkspaceId || token !== activeAccessToken", html)

    def test_topic_queue_schema_handoff_keeps_worker_and_account_boundaries(self):
        spec = (ROOT / "docs" / "TOPIC_QUEUE_SERVER_PERSISTENCE.md").read_text(encoding="utf-8")
        self.assertIn("REFERENCES auth.users(id) ON DELETE CASCADE", spec)
        self.assertIn("REFERENCES public.workspaces(workspace_id) ON DELETE CASCADE", spec)
        self.assertIn("ENABLE ROW LEVEL SECURITY", spec)
        self.assertIn("private.has_workspace_role", spec)
        self.assertIn("UNIQUE (workspace_id, user_id, normalized_topic)", spec)
        self.assertNotIn("shorts_jobs", spec.split("## SQL", 1)[1].split("## Lifecycle", 1)[0].split("CREATE TABLE", 1)[1].split(");", 1)[0])



if __name__ == "__main__":
    unittest.main()
