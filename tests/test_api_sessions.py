import importlib
import os
import sys
import types
import unittest
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

    def test_auth_fails_closed_without_configuration(self):
        with patch.object(self.api, "API_PASSWORD", ""), patch.object(self.api, "SESSION_SECRET", ""):
            self.assertFalse(self.api.auth_is_configured())
            self.assertFalse(self.api.verify_session_cookie("forged.cookie.value"))


if __name__ == "__main__":
    unittest.main()
