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

    def test_workspace_shell_is_initialized_once_before_session_check(self):
        self.assertEqual(self.script.count("initNexusShell();"), 1)
        self.assertLess(self.script.index("initNexusShell();"), self.script.rindex("checkSession();"))

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

    def test_analytics_uses_backend_summary_and_keeps_unavailable_metrics_blank(self):
        self.assertIn('fetch("/api/analytics/summary"', self.script)
        self.assertIn("YouTube 읽기 전용 분석 권한이 연결되지 않았습니다.", self.script)
        self.assertIn("조회수·구독자·참여율·수익은 추정하지 않고 비워 둡니다.", self.script)

    def test_review_edits_trigger_regeneration_and_disable_approval_until_ready(self):
        self.assertIn('["최종컨펌 대기", "반려(수정 필요)", "재제작 실패"]', self.script)
        self.assertIn("수정 후 재제작", self.html)
        self.assertIn("if (response.ok) { activeJobId = null; await loadOverview(); }", self.script)
        self.assertIn('"재제작 대기"', self.script)
        self.assertIn('"재제작 실패"', self.script)

    def test_channel_chart_does_not_claim_unavailable_performance_metrics(self):
        self.assertIn("Channel Production Volume", self.script)
        self.assertNotIn("Global Trend Momentum", self.script)


if __name__ == "__main__":
    unittest.main()
