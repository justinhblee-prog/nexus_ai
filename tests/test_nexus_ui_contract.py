from pathlib import Path
import re
import unittest


class NexusUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("index.html").read_text(encoding="utf-8")
        scripts = re.findall(r"<script>(.*?)</script>", cls.html, re.S)
        if not scripts:
            raise AssertionError("Browser studio script is missing")
        cls.script = scripts[-1]


    def test_frontend_api_call_patterns_exist_in_backend_routes(self):
        api_source = Path("api_server.py").read_text(encoding="utf-8")
        routes = re.findall(r"@app\.(?:get|post|put|delete|patch)\(['\"]([^'\"]+)", api_source)
        calls = set(re.findall(r"['\"](/api/[A-Za-z0-9_{}?=/&.-]+)", self.script))
        self.assertTrue(routes, "Backend route decorators are missing")

        def matches_route(path):
            path = path.split("?", 1)[0]
            for route in routes:
                pattern = re.sub(r"\{[^}]+\}", r"[^/]+", route)
                if re.fullmatch(pattern, path):
                    return True
                if path.endswith("/") and route.startswith(path):
                    return True
            return False

        unmatched = sorted(path for path in calls if not matches_route(path))
        self.assertEqual(unmatched, [], "UI calls have no backend route: " + ", ".join(unmatched))

    def test_sample_data_and_layout_controls_are_real_independent_actions(self):
        self.assertIn('addSample.onclick=addSampleData', self.script)
        self.assertIn('removeSample.onclick=removeSampleData', self.script)
        self.assertIn('layout.onchange=()=>setLayout(layout.value)', self.script)
        self.assertIn('sel.onchange=()=>setTheme(sel.value)', self.script)
        self.assertIn('function setLayout(t)', self.script)
        self.assertIn('function setTheme(t)', self.script)
        self.assertIn("NEXUS DESIGN THEMES v2", self.html)
        self.assertIn('[data-layout="creator"] .nexus-shell', self.html)
        self.assertIn('[data-layout="global"] .nexus-shell', self.html)
        self.assertIn('[data-layout="executive"] .nexus-shell', self.html)

    def test_discovery_enqueue_checks_http_response_before_success(self):
        handler = self.script.split("async function produceFromModal()", 1)[1].split("async function loadOpsMetrics()", 1)[0]
        self.assertIn("if (!response.ok) throw new Error", handler)
        self.assertIn('credentials: "same-origin"', handler)

    def test_workspace_shell_uses_secure_session_gate_and_static_preview_fallback(self):
        self.assertEqual(self.script.count("initNexusShell();"), 1)
        self.assertLess(self.script.index("initNexusShell();"), self.script.rindex("startStudio();"))
        self.assertIn("initializeNexusRuntime();", self.script)
        self.assertIn('fetch("/api/session/status"', self.script)
        self.assertIn('fetch("/api/session/login"', self.script)
        self.assertIn('id="nexus-login-overlay"', self.html)
        self.assertIn("미리보기 전용", self.script)
        self.assertIn("session.required && !session.configured", self.script)
        self.assertIn("session.required && !session.authenticated", self.script)

    def test_seven_workspaces_are_declared(self):
        for workspace in (
            "dashboard", "studio", "discovery", "review",
            "publishing", "analytics", "operations",
        ):
            with self.subTest(workspace=workspace):
                self.assertIn(f'["{workspace}"', self.script)

    def test_four_layout_modes_are_independent_of_appearance(self):
        for layout in ("intelligence", "creator", "global", "executive"):
            with self.subTest(layout=layout):
                self.assertIn(f'"{layout}"', self.script)
        self.assertIn("function setAccent", self.script)
        self.assertIn("function setDensity", self.script)

    def test_default_editorial_accent_is_not_overridden_by_legacy_black(self):
        self.assertIn(":root{--accent:#38BDF8}", self.html)
        self.assertNotIn(":root{--accent:#111}", self.html)

    def test_initial_accent_control_matches_editorial_default(self):
        self.assertIn('accentColor="#38BDF8"', self.script)

    def test_dashboard_uses_persisted_queue_and_upload_states(self):
        self.assertIn("queuePending = Number.isFinite(Number(d.queue_pending))", self.script)
        for stage in (
            "최종컨펌 대기", "업로드 진행 중", "업로드 완료(비공개)",
            "업로드 상태 확인 필요", "반려(수정 필요)",
        ):
            with self.subTest(stage=stage):
                self.assertIn(stage, self.script)

    def test_discovery_uses_source_native_rank_and_stale_status(self):
        self.assertIn('currentRankFilter = "ALL"', self.script)
        self.assertIn("source_score_label", self.script)
        self.assertIn("source_is_stale", self.script)
        self.assertIn("글로벌 비교 순위", self.html)
        self.assertNotIn("평균 바이럴 적합도", self.html)
        self.assertNotIn("글로벌 종합 TOP 10", self.html)
        for fabricated_metric in ("viral_score", "growth_pct", "avg_cat_views", "est_views"):
            with self.subTest(metric=fabricated_metric):
                self.assertNotIn(fabricated_metric, self.script)

    def test_analytics_uses_backend_summary_and_keeps_unavailable_metrics_blank(self):
        self.assertIn('fetch("/api/analytics/summary"', self.script)
        self.assertIn("YouTube 읽기 전용 분석 권한이 연결되지 않았습니다.", self.script)
        self.assertIn("조회수·구독자·참여율·수익은 추정하지 않고 비워 둡니다.", self.script)

    def test_review_edits_trigger_regeneration_and_disable_approval_until_ready(self):
        self.assertIn('["최종컨펌 대기", "반려(수정 필요)", "재제작 실패"]', self.script)
        self.assertIn("수정 후 재제작", self.html)
        self.assertIn("수정 대본은 4~8문장", self.html)
        # Preserve the selected job while the refreshed overview reports its new regeneration state.
        edit_handler = self.script.split("async function saveJobEdit()", 1)[1].split("async function rejectJob()", 1)[0]
        self.assertIn("await loadOverview();", edit_handler)
        self.assertIn("if (!response.ok) throw new Error", edit_handler)
        overview = self.script.split("async function loadOverview()", 1)[1].split("function renderJobs()", 1)[0]
        self.assertIn("if (activeJobId) selectJob(activeJobId);", overview)
        self.assertIn('"재제작 대기"', self.script)
        self.assertIn('"재제작 실패"', self.script)

    def test_discovery_render_does_not_overwrite_pipeline_kpis(self):
        radar = self.script.split("function renderRadar()", 1)[1].split("function openRadarById", 1)[0]
        self.assertNotIn('getElementById("kpi-trends")', radar)
        self.assertNotIn('getElementById("kpi-growth")', radar)
        self.assertIn("source_score", radar)

    def test_operations_workspace_displays_radar_and_queue_freshness(self):
        self.assertIn("radar_scans", self.script)
        self.assertIn("oldest_pending_queue_created_at", self.script)
        self.assertIn("수정 재제작 대기", self.script)

    def test_channel_chart_does_not_claim_unavailable_performance_metrics(self):
        self.assertIn("Channel Production Volume", self.script)
        self.assertNotIn("Global Trend Momentum", self.script)

    def test_workflow_actions_check_api_failures_before_reporting_success(self):
        for marker in (
            'if (!response.ok) throw new Error(result.detail || "업로드 승인을 처리하지 못했습니다.")',
            'if (!response.ok) throw new Error(result.detail || "반려 요청을 처리하지 못했습니다.")',
            'if (!response.ok || result.ok === false) throw new Error(result.detail || result.msg || "삭제 요청을 처리하지 못했습니다.")',
            'if (!response.ok) throw new Error(result.detail || "재제작 요청을 처리하지 못했습니다.")',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)

    def test_youtube_upload_requires_an_explicit_confirmation_click(self):
        self.assertIn('confirm("선택한 영상을 YouTube에 비공개로 업로드하도록 승인하시겠습니까?")', self.script)
        self.assertIn('fetch("/api/approve/" + activeJobId', self.script)

    def test_untrusted_job_and_channel_labels_are_rendered_as_text(self):
        jobs = self.script.split("function renderJobs()", 1)[1].split("function selectJob(id)", 1)[0]
        self.assertIn("box.replaceChildren()", jobs)
        self.assertIn("title.textContent = String(j.title || \"\")", jobs)
        self.assertIn("channel.textContent = String(j.channel_name || \"\")", jobs)
        self.assertNotIn("box.innerHTML = allJobs.map", jobs)
        self.assertNotIn("j.title +", jobs)
        self.assertIn("option.textContent = String(c.name || \"\")", self.script)
        self.assertNotIn("sel.innerHTML = chs.map", self.script)


if __name__ == "__main__":
    unittest.main()
