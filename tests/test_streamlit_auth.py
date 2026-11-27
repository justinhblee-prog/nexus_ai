import os
import unittest
from unittest.mock import patch

from streamlit_auth import auth_enabled, configured_password, is_auth_configured, verify_streamlit_password


class StreamlitAuthTests(unittest.TestCase):
    def test_authentication_is_disabled_by_default_and_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(auth_enabled())
        with patch.dict(os.environ, {"NEXUS_AUTH_ENABLED": "true"}, clear=True):
            self.assertTrue(auth_enabled())
        with patch.dict(os.environ, {"NEXUS_AUTH_ENABLED": "0"}, clear=True):
            self.assertFalse(auth_enabled())

    def test_requires_minimum_password_length(self):
        self.assertEqual(configured_password("short"), "")
        self.assertEqual(configured_password("long-enough-password"), "long-enough-password")

    def test_missing_configuration_fails_closed(self):
        with patch.dict(os.environ, {"NEXUS_API_PASSWORD": ""}):
            self.assertFalse(is_auth_configured())
            self.assertFalse(verify_streamlit_password("anything"))

    def test_password_comparison(self):
        self.assertTrue(verify_streamlit_password("a-secure-test-password", "a-secure-test-password"))
        self.assertFalse(verify_streamlit_password("wrong-password", "a-secure-test-password"))
        self.assertFalse(verify_streamlit_password(None, "a-secure-test-password"))


if __name__ == "__main__":
    unittest.main()
