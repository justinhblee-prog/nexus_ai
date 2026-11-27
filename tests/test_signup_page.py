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


if __name__ == "__main__":
    unittest.main()
