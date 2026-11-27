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


    def test_ownership_transfer_rpc_uses_verified_user_jwt_and_allowlist(self):
        http = Mock()
        response = Mock(status_code=204)
        http.return_value = response
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=http)
        result = client.rpc("transfer_workspace_ownership", {
            "p_workspace_id": "wsp_11111111-1111-4111-8111-111111111111",
            "p_new_owner_id": "22222222-2222-4222-8222-222222222222",
        })
        self.assertIsNone(result)
        args, kwargs = http.call_args
        self.assertEqual(args[0], "POST")
        self.assertTrue(args[1].endswith("/rest/v1/rpc/transfer_workspace_ownership"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer verified.user.jwt")
        self.assertEqual(kwargs["json"]["p_workspace_id"], "wsp_11111111-1111-4111-8111-111111111111")
        with self.assertRaises(ValueError):
            client.rpc("delete_auth_user", {"p_user_id": "any"})

    def test_network_errors_become_safe_gateway_errors(self):
        http = Mock(side_effect=requests.Timeout("private connection details"))
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=http)
        with self.assertRaises(SupabaseRestError) as raised:
            client.select("shorts_jobs", {"select": "*"})
        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn("private connection details", raised.exception.public_message)

    def test_count_uses_head_exact_count_with_verified_user_jwt_and_filters(self):
        http = Mock()
        response = Mock(status_code=200)
        response.headers = {"Content-Range": "0-0/1234"}
        http.return_value = response
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=http)
        count = client.count("shorts_jobs", {
            "workspace_id": "eq.wsp_1",
            "stage": "eq.published",
        })
        self.assertEqual(count, 1234)
        args, kwargs = http.call_args
        self.assertEqual(args[0], "HEAD")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer verified.user.jwt")
        self.assertEqual(kwargs["headers"]["Prefer"], "count=exact")
        self.assertEqual(kwargs["headers"]["Range"], "0-0")
        self.assertEqual(kwargs["params"]["workspace_id"], "eq.wsp_1")
        self.assertEqual(kwargs["params"]["stage"], "eq.published")

    def test_count_handles_empty_and_rejects_missing_exact_content_range(self):
        http = Mock()
        empty = Mock(status_code=200)
        empty.headers = {"Content-Range": "*/0"}
        http.return_value = empty
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=http)
        self.assertEqual(client.count("shorts_jobs", {"workspace_id": "eq.wsp_1"}), 0)
        missing = Mock(status_code=200)
        missing.headers = {}
        http.return_value = missing
        with self.assertRaises(SupabaseRestError) as raised:
            client.count("shorts_jobs", {"workspace_id": "eq.wsp_1"})
        self.assertEqual(raised.exception.status_code, 502)

    def test_count_rejects_unsupported_tables(self):
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=Mock())
        with self.assertRaises(ValueError):
            client.count("private.youtube_oauth_credentials", {"select": "*"})


    def test_shared_trend_tables_are_readable_with_verified_user_jwt(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{"topic": "AI"}]
        http.return_value = response
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=http)
        rows = client.select("public_trend_signals", {
            "select": "topic",
            "period_type": "eq.daily",
        })
        self.assertEqual(rows, [{"topic": "AI"}])
        self.assertEqual(http.call_args.kwargs["headers"]["Authorization"], "Bearer verified.user.jwt")
    def test_topic_queue_delete_is_allowed_and_uses_user_jwt(self):
        http = Mock()
        http.return_value = Mock(status_code=204)
        client = SupabaseRestClient("verified.user.jwt", env=ENV, http_request=http)
        result = client.delete("shorts_topic_queue", {
            "topic_id": "eq.11111111-1111-4111-8111-111111111111",
            "workspace_id": "eq.wsp_11111111-1111-4111-8111-111111111111",
            "user_id": "eq.22222222-2222-4222-8222-222222222222",
        })
        self.assertIsNone(result)
        args, kwargs = http.call_args
        self.assertEqual(args[0], "DELETE")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer verified.user.jwt")
        self.assertEqual(kwargs["params"]["workspace_id"], "eq.wsp_11111111-1111-4111-8111-111111111111")
        self.assertEqual(kwargs["params"]["user_id"], "eq.22222222-2222-4222-8222-222222222222")



if __name__ == "__main__":
    unittest.main()
