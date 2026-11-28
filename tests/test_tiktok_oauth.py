import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import requests

from tiktok_oauth import TikTokOAuthConfig, TikTokOAuthError, TikTokOAuthReauthRequired


ENV = {
    "NEXUS_TIKTOK_CLIENT_KEY": "tiktok-client-key",
    "NEXUS_TIKTOK_CLIENT_SECRET": "tiktok-client-secret",
    "NEXUS_TIKTOK_OAUTH_REDIRECT_URI": "https://api.example.test/api/hosted/tiktok/callback",
    "NEXUS_HOSTED_APP_URL": "https://app.example.test",
}


class TikTokOAuthTests(unittest.TestCase):
    def test_config_requires_exact_https_callback_and_origin_only_app_url(self):
        self.assertEqual(TikTokOAuthConfig.from_env(ENV).app_url, "https://app.example.test")
        with self.assertRaises(TikTokOAuthError):
            TikTokOAuthConfig.from_env({**ENV, "NEXUS_TIKTOK_OAUTH_REDIRECT_URI": "https://api.example.test/callback"})
        with self.assertRaises(TikTokOAuthError):
            TikTokOAuthConfig.from_env({**ENV, "NEXUS_TIKTOK_OAUTH_REDIRECT_URI": ENV["NEXUS_TIKTOK_OAUTH_REDIRECT_URI"] + "?workspace=x"})
        with self.assertRaises(TikTokOAuthError):
            TikTokOAuthConfig.from_env({**ENV, "NEXUS_HOSTED_APP_URL": "https://app.example.test/path"})

    def test_authorization_url_uses_web_login_kit_v2_and_csrf_state(self):
        url = TikTokOAuthConfig.from_env(ENV).authorization_url("opaque-state")
        params = parse_qs(urlparse(url).query)
        self.assertEqual(urlparse(url).netloc, "www.tiktok.com")
        self.assertEqual(urlparse(url).path, "/v2/auth/authorize/")
        self.assertEqual(params["client_key"], ["tiktok-client-key"])
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["scope"], ["user.info.basic"])
        self.assertEqual(params["state"], ["opaque-state"])

    def test_code_exchange_uses_form_encoded_v2_endpoint_and_exact_redirect(self):
        http = Mock(return_value=Mock(status_code=200))
        http.return_value.json.return_value = {
            "access_token": "access",
            "refresh_token": "refresh",
            "open_id": "open-id",
            "expires_in": 7200,
            "refresh_expires_in": 15552000,
            "scope": "user.info.basic",
        }
        result = TikTokOAuthConfig.from_env(ENV).exchange_code("auth-code", http_post=http)
        self.assertEqual(result["open_id"], "open-id")
        self.assertEqual(http.call_args.args[0], "https://open.tiktokapis.com/v2/oauth/token/")
        self.assertEqual(http.call_args.kwargs["data"]["redirect_uri"], ENV["NEXUS_TIKTOK_OAUTH_REDIRECT_URI"])
        self.assertEqual(http.call_args.kwargs["data"]["grant_type"], "authorization_code")

    def test_profile_identity_comes_from_tiktok_api_not_browser_input(self):
        http = Mock(return_value=Mock(status_code=200))
        http.return_value.json.return_value = {
            "data": {"user": {"open_id": "open-id", "display_name": "Nexus Creator", "avatar_url": "https://example.test/avatar.png"}},
            "error": {"code": "ok", "message": ""},
        }
        result = TikTokOAuthConfig.from_env(ENV).fetch_account("access-token", http_get=http)
        self.assertEqual(result["account_id"], "open-id")
        self.assertEqual(result["display_name"], "Nexus Creator")
        self.assertEqual(http.call_args.kwargs["params"]["fields"], "open_id,display_name,avatar_url")

    def test_refresh_token_rotation_and_revocation_use_v2_endpoints(self):
        config = TikTokOAuthConfig.from_env(ENV)
        refresh = Mock(return_value=Mock(status_code=200))
        refresh.return_value.json.return_value = {"access_token": "fresh", "refresh_token": "rotated"}
        self.assertEqual(config.refresh_access_token("old-refresh", http_post=refresh)["refresh_token"], "rotated")
        revoke = Mock(return_value=Mock(status_code=200))
        config.revoke_access_token("fresh", http_post=revoke)
        self.assertEqual(revoke.call_args.kwargs["data"]["token"], "fresh")

    def test_invalid_grant_requires_reauthorization(self):
        http = Mock(return_value=Mock(status_code=400))
        http.return_value.json.return_value = {"error": "invalid_grant"}
        with self.assertRaises(TikTokOAuthReauthRequired):
            TikTokOAuthConfig.from_env(ENV).refresh_access_token("expired", http_post=http)


if __name__ == "__main__":
    unittest.main()
