import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from starlette.requests import Request
from fastapi import HTTPException

from supabase_rest import SupabaseRestError


USER_ID = "11111111-1111-4111-8111-111111111111"
WORKSPACE_ID = "wsp_22222222-2222-4222-8222-222222222222"
TOPIC_ID = "33333333-3333-4333-8333-333333333333"


class HostedTopicQueueApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env_patch = patch.dict(os.environ, {
            "NEXUS_API_PASSWORD": "unit-test-password-12",
            "NEXUS_SESSION_SECRET": "s" * 48,
            "NEXUS_HOSTED_AUTH_ENABLED": "true",
            "NEXUS_SUPABASE_URL": "https://example-project.supabase.co",
            "NEXUS_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test_key",
        })
        cls.env_patch.start()
        cls.stubs = {
            "video_maker": types.ModuleType("video_maker"),
            "yt_uploader": types.ModuleType("yt_uploader"),
            "trend_radar": types.ModuleType("trend_radar"),
        }
        cls.module_patch = patch.dict(sys.modules, cls.stubs)
        cls.module_patch.start()
        sys.modules.pop("api_server", None)
        cls.api = importlib.import_module("api_server")

    @classmethod
    def tearDownClass(cls):
        cls.module_patch.stop()
        cls.env_patch.stop()
        sys.modules.pop("api_server", None)

    def request(self):
        return Request({
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/hosted/workspaces/topic-queue",
            "raw_path": b"/api/hosted/workspaces/topic-queue",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 443),
            "client": ("127.0.0.1", 12345),
            "state": {
                "hosted_user": {"user_id": USER_ID, "role": "authenticated"},
                "hosted_access_token": "verified.user.jwt",
            },
        })

    def test_list_is_scoped_to_both_workspace_and_verified_user(self):
        client = Mock()
        client.select.return_value = [{"topic_id": TOPIC_ID, "topic": "AI"}]
        with patch.object(self.api, "_hosted_rest_client", return_value=client):
            result = self.api.hosted_topic_queue_list(WORKSPACE_ID, self.request())
        self.assertEqual(result, {"items": [{"topic_id": TOPIC_ID, "topic": "AI"}], "storage": "server"})
        client.select.assert_called_once_with("shorts_topic_queue", {
            "select": "topic_id,topic,source,region,source_name,source_url,created_at",
            "workspace_id": f"eq.{WORKSPACE_ID}",
            "user_id": f"eq.{USER_ID}",
            "order": "created_at.desc,topic_id.desc",
            "limit": "50",
        })

    def test_add_normalizes_topic_and_uses_verified_identity(self):
        client = Mock()
        row = {"topic_id": TOPIC_ID, "topic": "AI workflow"}
        client.insert.return_value = [row]
        req = self.api.HostedTopicQueueCreateReq(
            topic="  AI   workflow  ",
            source="trend_radar",
            region=" KR ",
            source_name=" Google News ",
            source_url=" https://example.test/story ",
        )
        with patch.object(self.api, "_hosted_rest_client", return_value=client):
            result = self.api.hosted_topic_queue_add(WORKSPACE_ID, req, self.request())
        self.assertEqual(result, {"item": row, "storage": "server"})
        client.insert.assert_called_once_with("shorts_topic_queue", {
            "workspace_id": WORKSPACE_ID,
            "user_id": USER_ID,
            "topic": "AI workflow",
            "source": "trend_radar",
            "region": "KR",
            "source_name": "Google News",
            "source_url": "https://example.test/story",
        })

    def test_add_rejects_non_https_source_before_database_access(self):
        req = self.api.HostedTopicQueueCreateReq(topic="AI", source_url="http://example.test/story")
        with patch.object(self.api, "_hosted_rest_client") as make_client:
            with self.assertRaises(HTTPException) as raised:
                self.api.hosted_topic_queue_add(WORKSPACE_ID, req, self.request())
        self.assertEqual(raised.exception.status_code, 422)
        make_client.assert_not_called()

    def test_add_maps_duplicate_to_conflict(self):
        client = Mock()
        client.insert.side_effect = SupabaseRestError(409, "duplicate")
        req = self.api.HostedTopicQueueCreateReq(topic="AI")
        with patch.object(self.api, "_hosted_rest_client", return_value=client):
            with self.assertRaises(HTTPException) as raised:
                self.api.hosted_topic_queue_add(WORKSPACE_ID, req, self.request())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "이미 저장된 주제입니다.")

    def test_missing_topic_queue_migration_is_reported_as_service_unavailable(self):
        client = Mock()
        client.select.side_effect = SupabaseRestError(404, "missing relation")
        with patch.object(self.api, "_hosted_rest_client", return_value=client):
            with self.assertRaises(HTTPException) as raised:
                self.api.hosted_topic_queue_list(WORKSPACE_ID, self.request())
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("마이그레이션", raised.exception.detail)

    def test_delete_is_scoped_to_topic_workspace_and_verified_user(self):
        client = Mock()
        with patch.object(self.api, "_hosted_rest_client", return_value=client):
            result = self.api.hosted_topic_queue_delete(WORKSPACE_ID, TOPIC_ID, self.request())
        self.assertEqual(result, {"deleted": True})
        client.delete.assert_called_once_with("shorts_topic_queue", {
            "topic_id": f"eq.{TOPIC_ID}",
            "workspace_id": f"eq.{WORKSPACE_ID}",
            "user_id": f"eq.{USER_ID}",
        })

    def test_invalid_workspace_is_rejected_before_database_access(self):
        with patch.object(self.api, "_hosted_rest_client") as make_client:
            with self.assertRaises(HTTPException) as raised:
                self.api.hosted_topic_queue_list("not-a-workspace", self.request())
        self.assertEqual(raised.exception.status_code, 404)
        make_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
