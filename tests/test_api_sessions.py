import importlib
import asyncio
import os
import sys
import types
import unittest
from starlette.requests import Request
from starlette.responses import Response
from unittest.mock import patch


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

    def _request(self, path, method='GET', cookie=None, origin=None):
        headers = []
        if cookie:
            headers.append((b'cookie', f'nexus_session={cookie}'.encode('ascii')))
        if origin:
            headers.append((b'origin', origin.encode('ascii')))
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

    def test_auth_is_required_by_default_and_missing_secrets_fail_closed(self):
        async def next_response(_request):
            return Response(status_code=204)
        with patch.dict(os.environ, {"NEXUS_AUTH_ENABLED": ""}):
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


if __name__ == "__main__":
    unittest.main()
