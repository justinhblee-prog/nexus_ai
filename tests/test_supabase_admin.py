import base64
import json
import unittest
from unittest.mock import Mock

from supabase_admin import SupabaseAdminError, SupabaseAdminRestClient


def service_key():
    payload = base64.urlsafe_b64encode(json.dumps({"role": "service_role"}).encode()).decode().rstrip("=")
    return "header." + payload + ".signature"


ENV = {
    "NEXUS_SUPABASE_URL": "https://example-project.supabase.co",
    "NEXUS_SUPABASE_SERVICE_ROLE_KEY": service_key(),
}


class SupabaseAdminClientTests(unittest.TestCase):
    def test_requires_server_side_service_role_jwt(self):
        with self.assertRaises(SupabaseAdminError):
            SupabaseAdminRestClient({"NEXUS_SUPABASE_URL": ENV["NEXUS_SUPABASE_URL"]})
        with self.assertRaises(SupabaseAdminError):
            SupabaseAdminRestClient({**ENV, "NEXUS_SUPABASE_SERVICE_ROLE_KEY": "sb_publishable_not_admin"})

    def test_rpc_uses_service_role_and_only_allowlisted_functions(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{"user_id": "user-1"}]
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        result = client.consume_oauth_state("a" * 64)
        self.assertEqual(result["user_id"], "user-1")
        self.assertEqual(http.call_args.args[0], "POST")
        self.assertEqual(http.call_args.kwargs["headers"]["Authorization"], "Bearer " + ENV["NEXUS_SUPABASE_SERVICE_ROLE_KEY"])
        with self.assertRaises(ValueError):
            client.rpc("drop_everything", {})

    def test_upsert_credential_encodes_ciphertext_as_bytea_hex(self):
        http = Mock()
        response = Mock(status_code=204)
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        client.upsert_credential("connection-1", "wsp_1", "aabbcc", "v1", ["youtube.upload"], None)
        payload = http.call_args.kwargs["json"]
        self.assertEqual(payload["p_encrypted_refresh_token"], "\\xaabbcc")


if __name__ == "__main__":
    unittest.main()
