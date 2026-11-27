import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "signup.html"
INDEX = ROOT / "index.html"


class HostedSignupPageContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")

    def test_supabase_client_is_pinned_and_uses_browser_safe_config_endpoint(self):
        self.assertIn("@supabase/supabase-js@2.119.2", self.html)
        self.assertIn("/api/hosted/auth-config", self.html)
        self.assertIn("config.publishable_key", self.html)
        self.assertNotIn("service_role", self.html.lower())
        self.assertNotIn("sb_secret_", self.html.lower())

    def test_workspace_dashboard_metrics_load_from_tenant_scoped_hosted_overview(self):
        for metric_id in ("metric-channels", "metric-jobs", "metric-review", "metric-published"):
            self.assertIn('id="' + metric_id + '"', self.html)
        self.assertIn("async function loadWorkspaceOverview()", self.html)
        self.assertIn("/overview", self.html)
        self.assertIn('headers: { Authorization: "Bearer " + activeAccessToken }', self.html)
        self.assertIn("await loadWorkspaceOverview()", self.html)
    def test_final_approval_refreshes_jobs_and_workspace_metrics(self):
        approval_start = self.html.index('"/api/hosted/jobs/" + encodeURIComponent(item.job_id) + "/approve"')
        approval_end = self.html.index("showMessage(\"최종 승인되었습니다.", approval_start)
        approval_handler = self.html[approval_start:approval_end]
        self.assertIn("await loadJobs()", approval_handler)
        self.assertIn("await loadWorkspaceOverview()", approval_handler)

    def test_email_registration_login_and_recovery_flows_exist(self):
        self.assertIn("supabase.auth.signUp", self.html)
        self.assertIn("supabase.auth.signInWithPassword", self.html)
        self.assertIn("supabase.auth.resetPasswordForEmail", self.html)
        self.assertIn("supabase.auth.updateUser", self.html)
        self.assertIn("emailRedirectTo", self.html)

    def test_session_is_verified_by_backend_before_workspace_display(self):
        self.assertIn('"/api/hosted/session"', self.html)
        self.assertIn('Authorization: "Bearer " + session.access_token', self.html)
        self.assertIn('"/api/hosted/workspaces"', self.html)
        self.assertNotIn('.from("workspaces")', self.html)
        self.assertIn("verified.user.user_id !== user.id", self.html)

    def test_local_session_storage_and_text_only_status_rendering(self):
        self.assertIn("storage: window.sessionStorage", self.html)
        self.assertIn("message.textContent = text", self.html)
        self.assertNotIn("innerHTML =", self.html)


    def test_studio_header_links_to_hosted_account_access(self):
        index = INDEX.read_text(encoding="utf-8")
        self.assertIn('href="/signup"', index)
        self.assertIn("회원가입 / 로그인", index)


    def test_multi_workspace_selector_switches_active_tenant_and_refreshes_data(self):
        self.assertIn('id="workspace-select"', self.html)
        self.assertIn('id="workspace-picker"', self.html)
        self.assertIn('workspaceSelect.appendChild(option)', self.html)
        self.assertIn('activeWorkspaceId = workspace.workspace_id', self.html)
        self.assertIn('activeWorkspaceRole = workspace.member_role', self.html)
        self.assertIn('await loadConnections()', self.html)
        self.assertIn('해당 워크스페이스의 채널과 작업만 표시됩니다.', self.html)

    def test_signout_and_auth_expiry_clear_cached_tenant_credentials_and_data(self):
        self.assertIn("function clearHostedSession()", self.html)
        self.assertIn("activeAccessToken = null", self.html)
        self.assertIn("activeWorkspaceId = null", self.html)
        self.assertIn("activeWorkspaceRole = null", self.html)
        self.assertIn('document.getElementById("connections").replaceChildren()', self.html)
        self.assertIn('document.getElementById("jobs").replaceChildren()', self.html)
        self.assertIn("if (!session) clearHostedSession()", self.html)

    def test_workspace_switch_failure_restores_previous_selection(self):
        self.assertIn("const previousWorkspaceId = activeWorkspaceId", self.html)
        self.assertIn("select.value = activeWorkspaceId || \"\"", self.html)
        self.assertIn("finally {\n        select.disabled = false;", self.html)

    def test_account_deletion_ui_requires_preflight_password_reauth_and_exact_phrase(self):
        self.assertIn('id="account-deletion-panel"', self.html)
        self.assertIn('"/api/hosted/account/deletion/preflight"', self.html)
        self.assertIn('"/api/hosted/account/deletion/request"', self.html)
        self.assertIn('id="deletion-password"', self.html)
        self.assertIn('supabase.auth.signInWithPassword', self.html)
        self.assertIn('DELETE MY ACCOUNT', self.html)
        self.assertIn('id="workspace-members-panel"', self.html)
        self.assertIn('"/api/hosted/workspaces/" + encodeURIComponent(activeWorkspaceId) + "/members"', self.html)
        self.assertIn('"/transfer-ownership"', self.html)
        self.assertIn('JSON.stringify({ role: "admin" })', self.html)
        self.assertIn("소유권을 이전했습니다.", self.html)
        self.assertIn('scope: "local"', self.html)
        self.assertIn("showDeletionRetryOnly", self.html)

    def test_youtube_channel_connect_and_disconnect_controls_use_authenticated_api(self):
        self.assertIn('"/youtube/connections"', self.html)
        self.assertIn('"/youtube/connect"', self.html)
        self.assertIn('"/disconnect"', self.html)
        self.assertIn("YouTube 채널 연결", self.html)
        self.assertIn("authorization_url", self.html)
        self.assertIn('"/jobs"', self.html)
        self.assertIn('"/preview"', self.html)
        self.assertIn('"/approve"', self.html)
        self.assertIn("Shorts 제작 요청", self.html)
        self.assertIn("최종 승인", self.html)


if __name__ == "__main__":
    unittest.main()
