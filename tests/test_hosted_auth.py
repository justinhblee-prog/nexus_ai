import base64
import json
import unittest
from unittest.mock import Mock

from hosted_auth import (
    HostedAuthConfigurationError,
    HostedAuthError,
    extract_bearer_token,
    public_auth_config,
    verify_access_token,
)


ENV = {
    "NEXUS_HOSTED_AUTH_ENABLED": "true",
    "NEXUS_SUPABASE_URL": "https://example-project.supabase.co",
    "NEXUS_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test_key",
}


class HostedAuthConfigTests(unittest.TestCase):
    def test_public_config_contains_only_browser_safe_values(self):
        result = public_auth_config(ENV)
        self.assertEqual(result["supabase_url"], ENV["NEXUS_SUPABASE_URL"])
        self.assertEqual(result["publishable_key"], ENV["NEXUS_SUPABASE_PUBLISHABLE_KEY"])
        self.assertEqual(set(result), {"supabase_url", "publishable_key"})

    def test_disabled_or_missing_configuration_fails_closed(self):
        with self.assertRaises(HostedAuthConfigurationError):
            public_auth_config({"NEXUS_HOSTED_AUTH_ENABLED": "false"})
        with self.assertRaises(HostedAuthConfigurationError):
            public_auth_config({**ENV, "NEXUS_SUPABASE_URL": "http://example.test"})
        with self.assertRaises(HostedAuthConfigurationError):
            public_auth_config({**ENV, "NEXUS_SUPABASE_PUBLISHABLE_KEY": "sb_secret_do_not_expose"})
        legacy_service_role = "header." + base64.urlsafe_b64encode(
            json.dumps({"role": "service_role"}).encode()
        ).decode().rstrip("=") + ".signature"
        with self.assertRaises(HostedAuthConfigurationError):
            public_auth_config({**ENV, "NEXUS_SUPABASE_PUBLISHABLE_KEY": legacy_service_role})

    def test_bearer_header_is_parsed_strictly(self):
        self.assertEqual(extract_bearer_token("Bearer abc.def"), "abc.def")
        with self.assertRaises(HostedAuthError):
            extract_bearer_token(None)
        with self.assertRaises(HostedAuthError):
            extract_bearer_token("Basic abc")


class HostedAuthTokenTests(unittest.TestCase):
    def _verify(self, claims):
        jwt_module = Mock()
        jwt_module.PyJWKClient.return_value.get_signing_key_from_jwt.return_value.key = "verified-key"
        jwt_module.decode.return_value = claims
        token = "header.payload.signature"
        result = verify_access_token(token, ENV, jwt_module=jwt_module)
        return result, jwt_module

    def test_verified_identity_is_normalized_and_minimized(self):
        user_id = "11111111-1111-4111-8111-111111111111"
        claims = {
            "sub": user_id, "email": "member@example.test", "role": "authenticated",
            "iss": "https://example-project.supabase.co/auth/v1", "aud": "authenticated",
            "exp": 2_000_000_000, "iat": 1_900_000_000,
            "user_metadata": {"is_admin": True},
        }
        result, jwt_module = self._verify(claims)
        self.assertEqual(result, {"user_id": user_id, "email": "member@example.test", "role": "authenticated"})
        kwargs = jwt_module.decode.call_args.kwargs
        self.assertEqual(kwargs["algorithms"], ["ES256", "RS256", "EdDSA"])
        self.assertEqual(kwargs["audience"], "authenticated")
        self.assertEqual(kwargs["issuer"], "https://example-project.supabase.co/auth/v1")
        self.assertIn("sub", kwargs["options"]["require"])

    def test_invalid_subject_or_role_is_rejected(self):
        base = {
            "sub": "not-a-uuid", "role": "authenticated",
            "iss": "https://example-project.supabase.co/auth/v1",
        }
        jwt_module = Mock()
        jwt_module.PyJWKClient.return_value.get_signing_key_from_jwt.return_value.key = "verified-key"
        jwt_module.decode.return_value = base
        with self.assertRaises(HostedAuthError):
            verify_access_token("token", ENV, jwt_module=jwt_module)

        claims = {**base, "sub": "11111111-1111-4111-8111-111111111111", "role": "anon"}
        jwt_module = Mock()
        jwt_module.PyJWKClient.return_value.get_signing_key_from_jwt.return_value.key = "verified-key"
        jwt_module.decode.return_value = claims
        with self.assertRaises(HostedAuthError):
            verify_access_token("token", ENV, jwt_module=jwt_module)


if __name__ == "__main__":
    unittest.main()
