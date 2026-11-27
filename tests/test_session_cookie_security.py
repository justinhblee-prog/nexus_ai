import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch

from starlette.requests import Request


class SessionCookieSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
        sys.modules.pop("api_server", None)

    def _request(self, scheme):
        return Request({
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": scheme,
            "path": "/api/session/login",
            "raw_path": b"/api/session/login",
            "query_string": b"",
            "headers": [],
            "server": ("nexus.local", 443 if scheme == "https" else 80),
            "client": ("127.0.0.1", 12345),
        })

    def setUp(self):
        self.old_password = self.api.API_PASSWORD
        self.old_secret = self.api.SESSION_SECRET
        self.api.API_PASSWORD = "nexus-test-password"
        self.api.SESSION_SECRET = "s" * 48

    def tearDown(self):
        self.api.API_PASSWORD = self.old_password
        self.api.SESSION_SECRET = self.old_secret

    def test_https_session_cookie_is_secure_by_default(self):
        with patch.dict(os.environ, {"NEXUS_COOKIE_SECURE": "auto"}):
            response = self.api.session_login(
                self.api.LoginReq(password="nexus-test-password"), self._request("https")
            )
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertIn("secure", cookie)

    def test_local_http_session_cookie_remains_usable_without_secure_flag(self):
        with patch.dict(os.environ, {"NEXUS_COOKIE_SECURE": "auto"}):
            response = self.api.session_login(
                self.api.LoginReq(password="nexus-test-password"), self._request("http")
            )
        self.assertNotIn("secure", response.headers["set-cookie"].lower())

    def test_explicit_secure_override_is_respected(self):
        with patch.dict(os.environ, {"NEXUS_COOKIE_SECURE": "true"}):
            response = self.api.session_login(
                self.api.LoginReq(password="nexus-test-password"), self._request("http")
            )
        self.assertIn("secure", response.headers["set-cookie"].lower())


if __class__ == "__main__":
    unittest.main()
