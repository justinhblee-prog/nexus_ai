import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

import api_server
from supabase_rest import SupabaseRestError


WORKSPACE_ID = "wsp_11111111-1111-4111-8111-111111111111"


class FakeCountClient:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def count(self, table, params):
        self.calls.append((table, dict(params)))
        if self.fail:
            raise SupabaseRestError(403, "Workspace access denied by Supabase RLS")
        key = (table, tuple(sorted(params.items())))
        values = {
            ("shorts_channels", (("workspace_id", f"eq.{WORKSPACE_ID}"),)): 12,
            ("shorts_channels", (("is_active", "eq.true"), ("workspace_id", f"eq.{WORKSPACE_ID}"))): 9,
            ("shorts_jobs", (("workspace_id", f"eq.{WORKSPACE_ID}"),)): 1234,
            ("shorts_jobs", (("stage", "eq.queued"), ("workspace_id", f"eq.{WORKSPACE_ID}"))): 25,
            ("shorts_jobs", (("approval_status", "eq.pending"), ("workspace_id", f"eq.{WORKSPACE_ID}"))): 7,
            ("shorts_jobs", (("stage", "eq.published"), ("workspace_id", f"eq.{WORKSPACE_ID}"))): 900,
        }
        return values[key]


def hosted_request():
    return SimpleNamespace(state=SimpleNamespace(
        hosted_access_token="verified-user-jwt",
        hosted_user={"user_id": "11111111-1111-4111-8111-111111111111"},
    ))


class HostedWorkspaceMetricsTests(unittest.TestCase):
    def test_overview_uses_exact_workspace_filtered_counts_without_page_caps(self):
        client = FakeCountClient()
        with patch.object(api_server, "_hosted_rest_client", return_value=client):
            result = api_server.hosted_workspace_overview(WORKSPACE_ID, hosted_request())

        self.assertEqual(result, {
            "workspace_id": WORKSPACE_ID,
            "channel_count": 12,
            "active_channel_count": 9,
            "job_count": 1234,
            "queued_count": 25,
            "review_pending_count": 7,
            "published_count": 900,
        })
        self.assertEqual(len(client.calls), 6)
        self.assertTrue(all(params["workspace_id"] == f"eq.{WORKSPACE_ID}" for _, params in client.calls))
        self.assertFalse(any(params.get("limit") for _, params in client.calls))

    def test_overview_fails_closed_when_supabase_rls_denies_count(self):
        client = FakeCountClient(fail=True)
        with patch.object(api_server, "_hosted_rest_client", return_value=client):
            with self.assertRaises(HTTPException) as raised:
                api_server.hosted_workspace_overview(WORKSPACE_ID, hosted_request())
        self.assertEqual(raised.exception.status_code, 403)

    def test_overview_rejects_malformed_workspace_identifier_before_database_access(self):
        client = FakeCountClient()
        with patch.object(api_server, "_hosted_rest_client", return_value=client):
            with self.assertRaises(HTTPException) as raised:
                api_server.hosted_workspace_overview("not-a-workspace", hosted_request())
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
