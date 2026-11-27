import importlib
import logging
import asyncio
import os
import sys
import types
import unittest
from starlette.requests import Request
from starlette.responses import Response
from unittest.mock import Mock, patch


class SignedSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env_patch = patch.dict(os.environ, {
            "NEXUS_API_PASSWORD": "unit-test-password-12",
            "NEXUS_SESSION_SECRET": "s" * 48,
        })
        cls.env_patch.start()
        stubs = {
            "video_maker": types.ModuleType("video_maker"),
            "yt_uploader": types.ModuleType("yt_uploader"),
            "trend_radar": types.ModuleType("trend_radar"),
        }
        cls.module_patch = patch.dict(sys.modules, stubs)
        cls.module_patch.start()
        sys.modules.pop("api_server", None)
        cls.api = importlib.import_module("api_server")

    @classmethod
    def tearDownClass(cls):
        cls.module_patch.stop()
        cls.env_patch.stop()
        sys.modules.pop("api_server", None)

    def test_signed_cookie_round_trip_and_expiry(self):
        now = 1_800_000_000
        cookie = self.api.create_session_cookie(now=now)
        self.assertTrue(self.api.verify_session_cookie(cookie, now=now + 1))
        self.assertFalse(self.api.verify_session_cookie(cookie, now=now + 12 * 60 * 60))

    def test_tampered_or_malformed_cookie_is_rejected(self):
        now = 1_800_000_000
        cookie = self.api.create_session_cookie(now=now)
        self.assertFalse(self.api.verify_session_cookie(cookie + "x", now=now))
        self.assertFalse(self.api.verify_session_cookie("not-a-session", now=now))
        self.assertFalse(self.api.verify_session_cookie(None, now=now))

    def _request(self, path, method='GET', cookie=None, origin=None, authorization=None):
        headers = []
        if cookie:
            headers.append((b'cookie', f'nexus_session={cookie}'.encode('ascii')))
        if origin:
            headers.append((b'origin', origin.encode('ascii')))
        if authorization:
            headers.append((b'authorization', authorization.encode('ascii')))
        scope = {
            'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode('ascii'),
            'query_string': b'', 'headers': headers, 'server': ('testserver', 80),
            'client': ('127.0.0.1', 12345),
        }
        return Request(scope)

    def test_api_and_output_require_a_valid_session(self):
        async def next_response(_request):
            return Response(status_code=204)
        cookie = self.api.create_session_cookie(now=1_800_000_000)
        with patch.dict(os.environ, {"NEXUS_AUTH_ENABLED": "true"}):
            with patch.object(self.api.time, 'time', return_value=1_800_000_001):
                denied_api = asyncio.run(self.api.enforce_local_origin_and_session(self._request('/api/overview'), next_response))
                denied_output = asyncio.run(self.api.enforce_local_origin_and_session(self._request('/output/preview.mp4'), next_response))
                allowed_api = asyncio.run(self.api.enforce_local_origin_and_session(self._request('/api/overview', cookie=cookie), next_response))
        self.assertEqual(denied_api.status_code, 401)
        self.assertEqual(denied_output.status_code, 401)
        self.assertEqual(allowed_api.status_code, 204)

    def test_api_and_output_are_available_without_session_when_auth_is_disabled(self):
        async def next_response(_request):
            return Response(status_code=204)
        with patch.dict(os.environ, {"NEXUS_AUTH_ENABLED": "false"}):
            api_response = asyncio.run(self.api.enforce_local_origin_and_session(self._request('/api/overview'), next_response))
            output_response = asyncio.run(self.api.enforce_local_origin_and_session(self._request('/output/preview.mp4'), next_response))
        self.assertEqual(api_response.status_code, 204)
        self.assertEqual(output_response.status_code, 204)

    def test_authentication_is_disabled_by_default_and_opt_in_fails_closed(self):
        async def next_response(_request):
            return Response(status_code=204)
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(self.api, "API_PASSWORD", ""), patch.object(self.api, "SESSION_SECRET", ""):
                response = asyncio.run(self.api.enforce_local_origin_and_session(self._request('/api/overview'), next_response))
                self.assertEqual(response.status_code, 204)
                self.assertFalse(self.api.auth_is_required())
                status = self.api.session_status(self._request('/api/session/status'))
                self.assertFalse(status["required"])
                self.assertTrue(status["authenticated"])
        with patch.dict(os.environ, {"NEXUS_AUTH_ENABLED": "true"}, clear=True):
            with patch.object(self.api, "API_PASSWORD", ""), patch.object(self.api, "SESSION_SECRET", ""):
                response = asyncio.run(self.api.enforce_local_origin_and_session(self._request('/api/overview'), next_response))
                self.assertEqual(response.status_code, 503)
                self.assertTrue(self.api.auth_is_required())

    def test_explicit_local_opt_out_is_supported(self):
        with patch.dict(os.environ, {"NEXUS_AUTH_ENABLED": "false"}):
            self.assertFalse(self.api.auth_is_required())

    def test_session_status_is_public_and_foreign_mutations_are_blocked(self):
        async def next_response(_request):
            return Response(status_code=204)
        status = asyncio.run(self.api.enforce_local_origin_and_session(self._request('/api/session/status'), next_response))
        foreign = asyncio.run(self.api.enforce_local_origin_and_session(self._request('/api/queue', method='POST', origin='https://attacker.example'), next_response))
        cookie = self.api.create_session_cookie(now=1_800_000_000)
        with patch.object(self.api.time, 'time', return_value=1_800_000_001):
            allowed_api_port = asyncio.run(self.api.enforce_local_origin_and_session(
                self._request('/api/queue', method='POST', origin='http://127.0.0.1:28503', cookie=cookie),
                next_response,
            ))
            allowed_streamlit_port = asyncio.run(self.api.enforce_local_origin_and_session(
                self._request('/api/queue', method='POST', origin='http://localhost:28502', cookie=cookie),
                next_response,
            ))
        self.assertEqual(status.status_code, 204)
        self.assertEqual(foreign.status_code, 403)
        self.assertEqual(allowed_api_port.status_code, 204)
        self.assertEqual(allowed_streamlit_port.status_code, 204)
    def test_auth_fails_closed_without_configuration(self):
        with patch.object(self.api, "API_PASSWORD", ""), patch.object(self.api, "SESSION_SECRET", ""):
            self.assertFalse(self.api.auth_is_configured())
            self.assertFalse(self.api.verify_session_cookie("forged.cookie.value"))


    def test_hosted_mode_blocks_legacy_single_operator_routes_and_verifies_bearer(self):
        seen_requests = []
        async def next_response(_request):
            seen_requests.append(_request)
            return Response(status_code=204)
        with patch.dict(os.environ, {"NEXUS_HOSTED_AUTH_ENABLED": "true"}):
            blocked = asyncio.run(self.api.enforce_local_origin_and_session(
                self._request('/api/overview'), next_response
            ))
            blocked_media = asyncio.run(self.api.enforce_local_origin_and_session(
                self._request('/output/video.mp4'), next_response
            ))
            with patch.object(self.api, "verify_access_token", return_value={
                "user_id": "11111111-1111-4111-8111-111111111111",
                "email": "member@example.test",
                "role": "authenticated",
            }):
                allowed = asyncio.run(self.api.enforce_local_origin_and_session(
                    self._request('/api/hosted/session', authorization='Bearer valid.jwt.token'),
                    next_response,
                ))
            with patch.object(self.api, "verify_access_token", side_effect=self.api.HostedAuthError("invalid")):
                denied = asyncio.run(self.api.enforce_local_origin_and_session(
                    self._request('/api/hosted/session', authorization='Bearer invalid.jwt.token'),
                    next_response,
                ))
        self.assertEqual(blocked.status_code, 503)
        self.assertEqual(blocked_media.status_code, 503)
        self.assertEqual(allowed.status_code, 204)
        self.assertEqual(seen_requests[0].state.hosted_user["role"], "authenticated")
        self.assertEqual(denied.status_code, 401)

    def test_hosted_auth_config_is_public_but_legacy_auth_is_not_reused(self):
        async def next_response(_request):
            return Response(status_code=204)
        with patch.dict(os.environ, {"NEXUS_HOSTED_AUTH_ENABLED": "true"}):
            response = asyncio.run(self.api.enforce_local_origin_and_session(
                self._request('/api/hosted/auth-config'), next_response
            ))
            health = asyncio.run(self.api.enforce_local_origin_and_session(
                self._request('/api/session/status'), next_response
            ))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(health.status_code, 204)


    def test_hosted_signup_page_is_served_from_api(self):
        response = self.api.signup_page()
        self.assertEqual(response.path, "signup.html")
        self.assertTrue(response.media_type.startswith("text/html"))


    def test_hosted_workspace_routes_use_verified_user_jwt_and_workspace_filters(self):
        request = types.SimpleNamespace(state=types.SimpleNamespace(
            hosted_user={"user_id": "11111111-1111-4111-8111-111111111111", "role": "authenticated"},
            hosted_access_token="verified.user.jwt",
        ))
        with patch.object(self.api, "SupabaseRestClient") as client_type:
            client_type.return_value.select.side_effect = [
                [{"workspace_id": "wsp_11111111-1111-4111-8111-111111111111", "workspace_name": "Personal"}],
                [{"workspace_id": "wsp_11111111-1111-4111-8111-111111111111", "role": "owner"}],
                [{"job_id": "job-1"}],
            ]
            result = self.api.hosted_workspaces(request)
            self.assertEqual(result["items"][0]["workspace_id"], "wsp_11111111-1111-4111-8111-111111111111")
            self.assertEqual(result["items"][0]["member_role"], "owner")
            self.assertEqual(client_type.call_args.args[0], "verified.user.jwt")
            jobs = self.api.hosted_workspace_jobs("wsp_11111111-1111-4111-8111-111111111111", request)
            self.assertEqual(jobs["items"][0]["job_id"], "job-1")
            self.assertEqual(
                client_type.return_value.select.call_args.args[1]["workspace_id"],
                "eq.wsp_11111111-1111-4111-8111-111111111111",
            )

    def test_hosted_job_creation_uses_verified_identity_and_server_defaults(self):
        request = types.SimpleNamespace(state=types.SimpleNamespace(
            hosted_user={"user_id": "11111111-1111-4111-8111-111111111111", "role": "authenticated"},
            hosted_access_token="verified.user.jwt",
        ))
        payload = self.api.HostedJobCreateReq(
            channel_id="22222222-2222-4222-8222-222222222222",
            topic="New topic",
            title="Draft title",
            script="Draft script",
        )
        with patch.object(self.api, "SupabaseRestClient") as client_type:
            client_type.return_value.insert.return_value = [{"job_id": "job-1", "privacy_status": "private"}]
            result = self.api.hosted_create_job(
                "wsp_11111111-1111-4111-8111-111111111111", payload, request
            )
        inserted = client_type.return_value.insert.call_args.args[1]
        self.assertEqual(inserted["created_by"], "11111111-1111-4111-8111-111111111111")
        self.assertNotIn("owner_id", inserted)
        self.assertNotIn("approval_status", inserted)
        self.assertNotIn("privacy_status", inserted)
        self.assertNotIn("stage", inserted)
        self.assertEqual(result["job"]["privacy_status"], "private")

    def test_hosted_job_approval_is_attributed_to_verified_user(self):
        request = types.SimpleNamespace(state=types.SimpleNamespace(
            hosted_user={"user_id": "11111111-1111-4111-8111-111111111111", "role": "authenticated"},
            hosted_access_token="verified.user.jwt",
        ))
        with patch.object(self.api, "SupabaseRestClient") as client_type:
            client_type.return_value.update.return_value = [{"job_id": "job-1", "approval_status": "approved"}]
            result = self.api.hosted_approve_job(
                self.api.UUID("22222222-2222-4222-8222-222222222222"), request
            )
        params, payload = client_type.return_value.update.call_args.args[1:]
        self.assertEqual(params["job_id"], "eq.22222222-2222-4222-8222-222222222222")
        self.assertEqual(payload["approved_by"], "11111111-1111-4111-8111-111111111111")
        self.assertEqual(payload["approval_status"], "approved")
        self.assertEqual(result["job"]["approval_status"], "approved")

    def test_hosted_workspace_ids_are_validated_before_data_access(self):
        request = types.SimpleNamespace(state=types.SimpleNamespace(
            hosted_user={"user_id": "11111111-1111-4111-8111-111111111111"},
            hosted_access_token="verified.user.jwt",
        ))
        with self.assertRaises(self.api.HTTPException) as raised:
            self.api.hosted_workspace_jobs("not-a-workspace", request)
        self.assertEqual(raised.exception.status_code, 404)

    def test_hosted_mutations_allow_same_origin_but_reject_foreign_origins(self):
        async def next_response(_request):
            return Response(status_code=204)
        with patch.dict(os.environ, {"NEXUS_HOSTED_AUTH_ENABLED": "true"}):
            with patch.object(self.api, "verify_access_token", return_value={
                "user_id": "11111111-1111-4111-8111-111111111111",
                "role": "authenticated",
            }):
                same_origin = asyncio.run(self.api.enforce_local_origin_and_session(
                    self._request(
                        "/api/hosted/workspaces", method="POST",
                        origin="http://testserver", authorization="Bearer valid.jwt.token",
                    ), next_response
                ))
                foreign = asyncio.run(self.api.enforce_local_origin_and_session(
                    self._request(
                        "/api/hosted/workspaces", method="POST",
                        origin="https://attacker.example", authorization="Bearer valid.jwt.token",
                    ), next_response
                ))
        self.assertEqual(same_origin.status_code, 204)
        self.assertEqual(foreign.status_code, 403)


    def test_youtube_connect_requires_workspace_admin_and_stores_one_time_pkce_state(self):
        request = types.SimpleNamespace(state=types.SimpleNamespace(
            hosted_user={"user_id": "11111111-1111-4111-8111-111111111111"},
            hosted_access_token="verified.user.jwt",
        ))
        config = types.SimpleNamespace(
            redirect_uri="https://api.example.test/api/hosted/youtube/callback",
            app_url="https://app.example.test",
            authorization_url=Mock(return_value="https://accounts.google.com/oauth"),
        )
        with patch.object(self.api, "SupabaseRestClient") as client_type, \
             patch.object(self.api, "SupabaseAdminRestClient") as admin_type, \
             patch.object(self.api.GoogleOAuthConfig, "from_env", return_value=config), \
             patch.object(self.api, "create_oauth_state", return_value=("raw-state", "a" * 64)), \
             patch.object(self.api, "create_pkce_pair", return_value=("verifier-value", "challenge-value")):
            client_type.return_value.select.return_value = [{"role": "owner"}]
            result = self.api.hosted_youtube_connect(
                "wsp_11111111-1111-4111-8111-111111111111", request
            )
        self.assertEqual(result["authorization_url"], "https://accounts.google.com/oauth")
        stored = admin_type.return_value.store_oauth_state.call_args.args
        self.assertEqual(stored[0], "a" * 64)
        self.assertEqual(stored[1], "11111111-1111-4111-8111-111111111111")
        self.assertEqual(stored[2], "wsp_11111111-1111-4111-8111-111111111111")
        self.assertEqual(stored[5], "verifier-value")

    def test_youtube_connect_rejects_editor_role(self):
        request = types.SimpleNamespace(state=types.SimpleNamespace(
            hosted_user={"user_id": "11111111-1111-4111-8111-111111111111"},
            hosted_access_token="verified.user.jwt",
        ))
        with patch.object(self.api, "SupabaseRestClient") as client_type:
            client_type.return_value.select.return_value = [{"role": "editor"}]
            with self.assertRaises(self.api.HTTPException) as raised:
                self.api.hosted_youtube_connect(
                    "wsp_11111111-1111-4111-8111-111111111111", request
                )
        self.assertEqual(raised.exception.status_code, 403)

    def test_youtube_callback_consumes_state_and_encrypts_refresh_token(self):
        admin_state = {
            "user_id": "11111111-1111-4111-8111-111111111111",
            "workspace_id": "wsp_11111111-1111-4111-8111-111111111111",
            "provider": "youtube",
            "redirect_uri": "https://api.example.test/api/hosted/youtube/callback",
            "return_uri": "https://app.example.test/signup",
            "code_verifier": "pkce-verifier",
        }
        config = types.SimpleNamespace(
            redirect_uri=admin_state["redirect_uri"],
            app_url="https://app.example.test",
            exchange_code=Mock(return_value={
                "access_token": "temporary-access",
                "refresh_token": "refresh-secret",
                "scope": "youtube.upload youtube.readonly",
                "expires_in": 3600,
            }),
            fetch_channel=Mock(return_value={"channel_id": "UC123", "title": "NEXUS"}),
        )
        with patch.object(self.api, "SupabaseAdminRestClient") as admin_type, \
             patch.object(self.api.GoogleOAuthConfig, "from_env", return_value=config), \
             patch.object(self.api, "encrypt_refresh_token", return_value={"ciphertext_hex": "aabb", "key_version": "v1"}):
            admin_type.return_value.consume_oauth_state.return_value = admin_state
            admin_type.return_value.upsert_connection.return_value = [{"connection_id": "33333333-3333-4333-8333-333333333333"}]
            response = self.api.hosted_youtube_callback(code="google-code", state="raw-state")
        self.assertEqual(response.status_code, 303)
        self.assertIn("youtube=connected", response.headers["location"])
        config.exchange_code.assert_called_once_with("google-code", "pkce-verifier")
        admin_type.return_value.upsert_credential.assert_called_once()

    def test_youtube_callback_rejects_replayed_or_unknown_state(self):
        with patch.object(self.api, "SupabaseAdminRestClient") as admin_type:
            admin_type.return_value.consume_oauth_state.return_value = None
            with self.assertRaises(self.api.HTTPException) as raised:
                self.api.hosted_youtube_callback(code="code", state="unknown")
        self.assertEqual(raised.exception.status_code, 400)

    def test_youtube_disconnect_revokes_provider_token_before_deleting_credential(self):
        request = types.SimpleNamespace(state=types.SimpleNamespace(
            hosted_user={"user_id": "11111111-1111-4111-8111-111111111111"},
            hosted_access_token="verified.user.jwt",
        ))
        config = types.SimpleNamespace(revoke_refresh_token=Mock())
        with patch.object(self.api, "SupabaseRestClient") as client_type, \
             patch.object(self.api, "SupabaseAdminRestClient") as admin_type, \
             patch.object(self.api.GoogleOAuthConfig, "from_env", return_value=config), \
             patch.object(self.api, "decrypt_refresh_token", return_value="refresh-secret"):
            client_type.return_value.select.side_effect = [
                [{"role": "owner"}],
                [{"connection_id": "33333333-3333-4333-8333-333333333333", "status": "connected"}],
            ]
            admin_type.return_value.get_credential.return_value = {
                "encrypted_refresh_token_hex": "aabb", "encryption_key_version": "v1"
            }
            admin_type.return_value.update_connection.return_value = [{"status": "disconnected"}]
            result = self.api.hosted_youtube_disconnect(
                "wsp_11111111-1111-4111-8111-111111111111",
                self.api.UUID("33333333-3333-4333-8333-333333333333"),
                request,
            )
        config.revoke_refresh_token.assert_called_once_with("refresh-secret")
        admin_type.return_value.delete_credential.assert_called_once()
        self.assertEqual(result["status"], "disconnected")

    def test_youtube_callback_is_public_but_state_protected_in_hosted_mode(self):
        async def next_response(_request):
            return Response(status_code=204)
        with patch.dict(os.environ, {"NEXUS_HOSTED_AUTH_ENABLED": "true"}):
            response = asyncio.run(self.api.enforce_local_origin_and_session(
                self._request("/api/hosted/youtube/callback", method="GET"), next_response
            ))
        self.assertEqual(response.status_code, 204)


    def test_oauth_callback_access_log_redacts_query_parameters(self):
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 1, "%s - %s %s %s %s",
            ("127.0.0.1", "GET", "/api/hosted/youtube/callback?code=code123&state=state123", "1.1", 200),
            None,
        )
        filter_instance = self.api.OAuthCallbackLogFilter()
        self.assertTrue(filter_instance.filter(record))
        self.assertEqual(record.args[2], "/api/hosted/youtube/callback?[REDACTED]")
        self.assertNotIn("code123", str(record.args))
        self.assertNotIn("state123", str(record.args))


if __name__ == "__main__":
    unittest.main()
