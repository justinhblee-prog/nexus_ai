import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import requests

from youtube_oauth import (
    GoogleOAuthConfig,
    GoogleOAuthError,
    GoogleOAuthReauthRequired,
    create_oauth_state,
    create_pkce_pair,
)


ENV = {
    "NEXUS_GOOGLE_OAUTH_CLIENT_ID": "client-id.apps.googleusercontent.com",
    "NEXUS_GOOGLE_OAUTH_CLIENT_SECRET": "client-secret-test",
    "NEXUS_GOOGLE_OAUTH_REDIRECT_URI": "https://api.example.test/api/hosted/youtube/callback",
    "NEXUS_HOSTED_APP_URL": "https://app.example.test",
}


class GoogleOAuthTests(unittest.TestCase):
    def test_config_requires_https_and_origin_only_app_url(self):
        self.assertEqual(GoogleOAuthConfig.from_env(ENV).app_url, "https://app.example.test")
        with self.assertRaises(GoogleOAuthError):
            GoogleOAuthConfig.from_env({**ENV, "NEXUS_HOSTED_APP_URL": "http://app.example.test"})
        with self.assertRaises(GoogleOAuthError):
            GoogleOAuthConfig.from_env({**ENV, "NEXUS_HOSTED_APP_URL": "https://app.example.test/path"})
        with self.assertRaises(GoogleOAuthError):
            GoogleOAuthConfig.from_env({**ENV, "NEXUS_GOOGLE_OAUTH_REDIRECT_URI": "https://attacker.example/callback"})
        with self.assertRaises(GoogleOAuthError):
            GoogleOAuthConfig.from_env({**ENV, "NEXUS_GOOGLE_OAUTH_REDIRECT_URI": "https://attacker.example/callback"})

    def test_pkce_and_state_are_unpredictable_and_hashed(self):
        verifier, challenge = create_pkce_pair()
        state, state_hash = create_oauth_state()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertEqual(len(challenge), 43)
        self.assertNotEqual(state, state_hash)
        self.assertEqual(len(state_hash), 64)

    def test_authorization_url_uses_offline_consent_and_pkce(self):
        config = GoogleOAuthConfig.from_env(ENV)
        url = config.authorization_url("random-state", "challenge")
        params = parse_qs(urlparse(url).query)
        self.assertEqual(params["access_type"], ["offline"])
        self.assertEqual(params["prompt"], ["consent"])
        self.assertEqual(params["state"], ["random-state"])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertIn("youtube.upload", params["scope"][0])

    def test_code_exchange_uses_exact_redirect_and_verifier(self):
        config = GoogleOAuthConfig.from_env(ENV)
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}
        http.return_value = response
        result = config.exchange_code("auth-code", "pkce-verifier", http_post=http)
        self.assertEqual(result["refresh_token"], "refresh")
        self.assertEqual(http.call_args.kwargs["data"]["redirect_uri"], ENV["NEXUS_GOOGLE_OAUTH_REDIRECT_URI"])
        self.assertEqual(http.call_args.kwargs["data"]["code_verifier"], "pkce-verifier")

    def test_channel_identity_is_fetched_from_google_not_browser_input(self):
        config = GoogleOAuthConfig.from_env(ENV)
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"items": [
            {"id": "UC123", "snippet": {"title": "NEXUS Channel"}},
            {"id": "UC456", "snippet": {"title": "Second Channel"}},
        ]}
        http.return_value = response
        result = config.fetch_channels("verified-access-token", http_get=http)
        self.assertEqual(result, [
            {"channel_id": "UC123", "title": "NEXUS Channel"},
            {"channel_id": "UC456", "title": "Second Channel"},
        ])
        self.assertEqual(http.call_args.kwargs["params"]["mine"], "true")

    def test_revoke_requires_google_confirmation(self):
        config = GoogleOAuthConfig.from_env(ENV)
        http = Mock()
        http.return_value = Mock(status_code=200)
        config.revoke_refresh_token("refresh", http_post=http)
        http.return_value = Mock(status_code=400)
        with self.assertRaises(GoogleOAuthError):
            config.revoke_refresh_token("refresh", http_post=http)
        http.return_value = Mock(status_code=500)
        with self.assertRaises(GoogleOAuthError):
            config.revoke_refresh_token("refresh", http_post=http)


    def test_google_account_subject_is_verified_with_openid_userinfo(self):
        config = GoogleOAuthConfig.from_env(ENV)
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"sub": "google-account-123", "email": "owner@example.test", "name": "Workspace Owner"}
        http.return_value = response
        result = config.fetch_account("verified-access-token", http_get=http)
        self.assertEqual(result["account_id"], "google-account-123")
        self.assertEqual(result["email"], "owner@example.test")
        self.assertIn("openid", config.authorization_url("state", "challenge"))


    def test_refresh_token_exchange_returns_only_access_token(self):
        config = GoogleOAuthConfig.from_env(ENV)
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"access_token": "fresh-access", "expires_in": 3600}
        http.return_value = response
        token = config.refresh_access_token("refresh-token", http_post=http)
        self.assertEqual(token, "fresh-access")
        self.assertEqual(http.call_args.kwargs["data"]["grant_type"], "refresh_token")

    def test_private_resumable_upload_verifies_exact_channel_and_visibility(self):
        config = GoogleOAuthConfig.from_env(ENV)
        with patch.object(GoogleOAuthConfig, "fetch_channels", return_value=[{"channel_id": "UC123", "title": "NEXUS"}]):
            init = Mock(status_code=200)
            init.headers = {"Location": "https://upload.youtube.example/session"}
            upload = Mock(status_code=200)
            upload.json.return_value = {
                "id": "video-123",
                "snippet": {"channelId": "UC123"},
                "status": {"privacyStatus": "private"},
            }
            post = Mock(return_value=init)
            put = Mock(return_value=upload)
            result = config.upload_private_video(
                "fresh-access", b"video-bytes", "NEXUS title", "script", "UC123",
                http_post=post, http_put=put,
            )
        self.assertEqual(result, {
            "video_id": "video-123", "channel_id": "UC123", "privacy_status": "private"
        })
        self.assertEqual(post.call_args.kwargs["json"]["status"]["privacyStatus"], "private")
        self.assertEqual(put.call_args.kwargs["data"], b"video-bytes")

    def test_private_upload_fails_closed_for_ambiguous_channel_or_public_response(self):
        config = GoogleOAuthConfig.from_env(ENV)
        with patch.object(GoogleOAuthConfig, "fetch_channels", return_value=[
            {"channel_id": "UC123", "title": "One"},
            {"channel_id": "UC456", "title": "Two"},
        ]):
            with self.assertRaises(GoogleOAuthError):
                config.upload_private_video("token", b"video", "title", "desc", "UC123")
        with patch.object(GoogleOAuthConfig, "fetch_channels", return_value=[{"channel_id": "UC123", "title": "One"}]):
            init = Mock(status_code=200)
            init.headers = {"Location": "https://upload.youtube.example/session"}
            upload = Mock(status_code=200)
            upload.json.return_value = {
                "id": "video-123",
                "snippet": {"channelId": "UC123"},
                "status": {"privacyStatus": "public"},
            }
            with self.assertRaises(GoogleOAuthError):
                config.upload_private_video(
                    "token", b"video", "title", "desc", "UC123",
                    http_post=Mock(return_value=init), http_put=Mock(return_value=upload),
                )


    def test_invalid_grant_is_classified_as_reauthorization_required(self):
        config = GoogleOAuthConfig.from_env(ENV)
        http = Mock()
        response = Mock(status_code=400)
        response.json.return_value = {"error": "invalid_grant"}
        http.return_value = response
        with self.assertRaises(GoogleOAuthReauthRequired):
            config.refresh_access_token("revoked-refresh-token", http_post=http)


if __name__ == "__main__":
    unittest.main()
