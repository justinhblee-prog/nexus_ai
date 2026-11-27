import unittest
from unittest.mock import Mock

import requests

from supabase_rest import SupabaseRestClient, SupabaseRestError


ENV = {
    "NEXUS_HOSTED_AUTH_ENABLED": "true",
    "NEXUS_SUPABASE_URL": "https://example-project.supabase.co",
    "NEXUS_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test_key",
}


class SupabaseRestClientTests(unittest.TestCase):
    def test_select_uses_user_jwt_and_publishable_key_not_service_role(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{"workspace_id": "wsp_1"}]
        http.return_value = response
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=http)
        result = client.select("workspaces", {"select": "workspace_id"})
        self.assertEqual(result, [{"workspace_id": "wsp_1"}])
        args, kwargs = http.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer verified.user.jwt")
        self.assertEqual(kwargs["headers"]["apikey"], ENV["NEXUS_SUPABASE_PUBLISHABLE_KEY"])
        self.assertNotIn("service_role", str(kwargs["headers"]).lower())

    def test_mutations_are_scoped_to_explicit_workspace_filters(self):
        http = Mock()
        response = Mock(status_code=201)
        response.json.return_value = [{"job_id": "job-1"}]
        http.return_value = response
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=http)
        result = client.update("shorts_jobs", {"job_id": "eq.job-1", "workspace_id": "eq.wsp_1"}, {"title": "Updated"})
        self.assertEqual(result[0]["job_id"], "job-1")
        self.assertEqual(http.call_args.kwargs["params"]["workspace_id"], "eq.wsp_1")
        self.assertEqual(http.call_args.kwargs["headers"]["Prefer"], "return=representation")

    def test_unsupported_tables_and_missing_user_tokens_fail_closed(self):
        with self.assertRaises(ValueError):
            SupabaseRestClient("", env=ENV)
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=Mock())
        with self.assertRaises(ValueError):
            client.select("private.youtube_oauth_credentials", {"select": "*"})

    def test_rls_errors_are_sanitized(self):
        http = Mock()
        response = Mock(status_code=403)
        http.return_value = response
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=http)
        with self.assertRaises(SupabaseRestError) as raised:
            client.select("shorts_jobs", {"select": "*"})
        self.assertEqual(raised.exception.status_code, 403)
        self.assertIn("RLS", raised.exception.public_message)
        self.assertNotIn("database password", raised.exception.public_message.lower())

    def test_network_errors_become_safe_gateway_errors(self):
        http = Mock(side_effect=requests.Timeout("private connection details"))
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=http)
        with self.assertRaises(SupabaseRestError) as raised:
            client.select("shorts_jobs", {"select": "*"})
        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn("private connection details", raised.exception.public_message)


if __name__ == "__main__":
    unittest.main()
