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


    def test_render_worker_rpc_and_private_storage_upload_use_service_role(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{
            "job_id": "22222222-2222-4222-8222-222222222222",
            "workspace_id": "wsp_11111111-1111-4111-8111-111111111111",
            "lease_token": "lease-token",
        }]
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        job = client.claim_next_shorts_job("worker-1")
        self.assertEqual(job["lease_token"], "lease-token")
        self.assertIn("/rpc/claim_next_shorts_job", http.call_args.args[1])
        media_response = Mock(status_code=200)
        http.return_value = media_response
        key = "wsp_11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/" + "a" * 32 + ".mp4"
        client.upload_storage_object(key, b"video-bytes")
        self.assertIn("/storage/v1/object/nexus-shorts/", http.call_args.args[1])
        self.assertEqual(http.call_args.kwargs["data"], b"video-bytes")
        self.assertEqual(http.call_args.kwargs["headers"]["Authorization"], "Bearer " + ENV["NEXUS_SUPABASE_SERVICE_ROLE_KEY"])

    def test_storage_object_paths_are_tenant_scoped_and_canonical(self):
        client = SupabaseAdminRestClient(ENV, http_request=Mock())
        with self.assertRaises(ValueError):
            client.upload_storage_object("../../other-workspace/video.mp4", b"bad")
        with self.assertRaises(ValueError):
            client.create_signed_url("wsp_11111111-1111-4111-8111-111111111111/other/video.mp4")




    def test_account_deletion_queue_rpc_methods_validate_and_use_service_role(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{"status": "pending", "phase": "queued", "attempt_count": 0}]
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        queued = client.enqueue_account_deletion(
            "11111111-1111-4111-8111-111111111111",
            {"preflight_clear": True, "workspaces": []},
        )
        self.assertEqual(queued["status"], "pending")
        self.assertIn("/rpc/enqueue_account_deletion", http.call_args.args[1])
        self.assertEqual(http.call_args.kwargs["json"]["p_preflight_snapshot"]["preflight_clear"], True)
        response.json.return_value = [{
            "user_id": "11111111-1111-4111-8111-111111111111",
            "status": "running", "phase": "claimed", "attempt_count": 1,
        }]
        claimed = client.claim_next_account_deletion_request("worker-1")
        self.assertEqual(claimed["phase"], "claimed")
        self.assertIn("/rpc/claim_next_account_deletion_request", http.call_args.args[1])
        response.json.return_value = True
        self.assertTrue(client.update_account_deletion_request(
            "11111111-1111-4111-8111-111111111111", "worker-1", "retry", "storage_cleanup",
            "storage_unavailable", 120,
        ))
        self.assertIn("/rpc/update_account_deletion_request", http.call_args.args[1])
        response.json.return_value = True
        response.json.return_value = True
        self.assertTrue(client.heartbeat_account_deletion_worker("worker-1"))
        self.assertIn("/rpc/heartbeat_account_deletion_worker", http.call_args.args[1])
        self.assertTrue(client.is_account_deletion_worker_online())
        self.assertIn("/rpc/is_account_deletion_worker_online", http.call_args.args[1])
        self.assertTrue(client.mark_account_deletion_sessions_revoked("11111111-1111-4111-8111-111111111111"))
        self.assertIn("/rpc/mark_account_deletion_sessions_revoked", http.call_args.args[1])
        self.assertTrue(client.heartbeat_account_deletion_request("11111111-1111-4111-8111-111111111111", "worker-1"))
        self.assertIn("/rpc/heartbeat_account_deletion_request", http.call_args.args[1])
        with self.assertRaises(ValueError):
            client.enqueue_account_deletion("../../user", {})
        with self.assertRaises(ValueError):
            client.update_account_deletion_request(
                "11111111-1111-4111-8111-111111111111", "worker-1", "done", "complete"
            )

    def test_existing_account_deletion_request_lookup_is_service_role_only(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{
            "status": "pending", "phase": "queued", "attempt_count": 0, "sessions_revoked": False,
        }]
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        request = client.get_account_deletion_request("11111111-1111-4111-8111-111111111111")
        self.assertEqual(request["sessions_revoked"], False)
        self.assertIn("/rpc/get_account_deletion_request", http.call_args.args[1])
        self.assertEqual(http.call_args.kwargs["json"]["p_user_id"], "11111111-1111-4111-8111-111111111111")
        response.json.return_value = []
        self.assertIsNone(client.get_account_deletion_request("11111111-1111-4111-8111-111111111111"))
        with self.assertRaises(ValueError):
            client.get_account_deletion_request("../../user")

    def test_account_deletion_tombstone_uses_allowlisted_service_rpc(self):
        http = Mock()
        response = Mock(status_code=204)
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        self.assertIsNone(client.mark_account_deletion_tombstone("11111111-1111-4111-8111-111111111111"))
        self.assertIn("/rpc/mark_account_deletion_tombstone", http.call_args.args[1])
        with self.assertRaises(ValueError):
            client.rpc("remove_tombstone", {})

    def test_active_account_deletion_leases_use_service_role_rpc_and_validate_workspace_ids(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{"workspace_id": "wsp_11111111-1111-4111-8111-111111111111", "lease_kind": "render"}]
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        rows = client.list_account_deletion_active_leases(["wsp_11111111-1111-4111-8111-111111111111"])
        self.assertEqual(rows[0]["lease_kind"], "render")
        self.assertIn("/rpc/list_account_deletion_active_leases", http.call_args.args[1])
        with self.assertRaises(ValueError):
            client.list_account_deletion_active_leases(["../../other-workspace"])

    def test_provider_grant_usage_is_checked_outside_all_deletion_workspaces(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{"connection_id": "other-connection"}]
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        self.assertTrue(client.has_active_connection_outside_workspaces(
            "google-account",
            ["wsp_11111111-1111-4111-8111-111111111111"],
        ))
        params = http.call_args.kwargs["params"]
        self.assertEqual(params["workspace_id"], "not.in.(wsp_11111111-1111-4111-8111-111111111111)")
        with self.assertRaises(ValueError):
            client.has_active_connection_outside_workspaces("google-account", ["bad-id"])

    def test_youtube_connection_inventory_is_workspace_scoped_and_excludes_tokens(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{
            "connection_id": "33333333-3333-4333-8333-333333333333",
            "workspace_id": "wsp_11111111-1111-4111-8111-111111111111",
            "provider": "youtube",
            "provider_account_id": "google-account",
            "status": "connected",
        }]
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        rows = client.list_youtube_connections_for_workspaces(["wsp_11111111-1111-4111-8111-111111111111"])
        self.assertEqual(rows[0]["provider"], "youtube")
        self.assertNotIn("encrypted_refresh_token", rows[0])
        self.assertIn("youtube_connections", http.call_args.args[1])
        self.assertEqual(http.call_args.kwargs["params"]["workspace_id"], "in.(wsp_11111111-1111-4111-8111-111111111111)")
        with self.assertRaises(ValueError):
            client.list_youtube_connections_for_workspaces(["../../workspace"])

    def test_account_storage_inventory_uses_allowlisted_service_rpc(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{
            "bucket_id": "nexus-shorts",
            "name": "wsp_11111111-1111-4111-8111-111111111111/video.mp4",
            "owner_id": "11111111-1111-4111-8111-111111111111",
            "owner": "11111111-1111-4111-8111-111111111111",
        }]
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        rows = client.list_account_deletion_storage_objects("11111111-1111-4111-8111-111111111111", limit=500, offset=0, workspace_ids=["wsp_11111111-1111-4111-8111-111111111111"])
        self.assertEqual(len(rows), 1)
        self.assertIn("/rpc/list_account_deletion_storage_objects", http.call_args.args[1])
        self.assertEqual(http.call_args.kwargs["json"]["p_limit"], 500)
        self.assertEqual(http.call_args.kwargs["json"]["p_workspace_ids"], ["wsp_11111111-1111-4111-8111-111111111111"])

    def test_global_session_revocation_accepts_documented_already_revoked_responses(self):
        for status_code in (200, 204, 401, 403, 404):
            http = Mock()
            http.return_value = Mock(status_code=status_code)
            client = SupabaseAdminRestClient(ENV, http_request=http)
            self.assertTrue(client.revoke_user_sessions("verified.user.jwt"))
            self.assertEqual(http.call_args.kwargs["params"], {"scope": "global"})
            self.assertEqual(
                http.call_args.kwargs["headers"]["Authorization"],
                "Bearer verified.user.jwt",
            )

    def test_auth_and_storage_deletes_are_idempotent_on_not_found(self):
        http = Mock()
        http.return_value = Mock(status_code=404)
        client = SupabaseAdminRestClient(ENV, http_request=http)
        self.assertTrue(client.delete_auth_user("11111111-1111-4111-8111-111111111111"))
        self.assertTrue(client.delete_storage_object_in_bucket(
            "nexus-shorts",
            "wsp_11111111-1111-4111-8111-111111111111/job/" + "a" * 32 + ".mp4",
        ))

    def test_shared_legacy_generation_job_authorship_includes_null_workspace_rows(self):
        http = Mock()
        http.return_value = Mock(status_code=204)
        client = SupabaseAdminRestClient(ENV, http_request=http)
        client.anonymize_account_authorship(
            "11111111-1111-4111-8111-111111111111",
            ["wsp_22222222-2222-4222-8222-222222222222"],
        )
        calls = [call for call in http.call_args_list if call.args[1].endswith("/generation_jobs")]
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0].kwargs["params"]["or"],
            "(workspace_id.is.null,workspace_id.not.in.(wsp_22222222-2222-4222-8222-222222222222))",
        )

    def test_account_storage_delete_uses_storage_api_and_rejects_unsafe_paths(self):
        http = Mock()
        http.return_value = Mock(status_code=200)
        client = SupabaseAdminRestClient(ENV, http_request=http)
        self.assertTrue(client.delete_storage_object_in_bucket("acs-assets", "workspace/file.png"))
        self.assertIn("/storage/v1/object/acs-assets", http.call_args.args[1])
        self.assertEqual(http.call_args.kwargs["json"], {"prefixes": ["workspace/file.png"]})
        for bucket, path in (
            ("unknown-bucket", "file.png"),
            ("acs-assets", "../file.png"),
            ("acs-assets", "/file.png"),
            ("acs-assets", "folder\\\\file.png"),
            ("acs-assets", "folder//file.png"),
        ):
            with self.assertRaises(ValueError):
                client.delete_storage_object_in_bucket(bucket, path)

    def test_auth_user_deletion_uses_admin_endpoint_and_server_role(self):
        http = Mock()
        http.return_value = Mock(status_code=200)
        client = SupabaseAdminRestClient(ENV, http_request=http)
        self.assertTrue(client.delete_auth_user("11111111-1111-4111-8111-111111111111"))
        self.assertIn("/auth/v1/admin/users/11111111-1111-4111-8111-111111111111", http.call_args.args[1])
        self.assertEqual(http.call_args.kwargs["headers"]["Authorization"], "Bearer " + ENV["NEXUS_SUPABASE_SERVICE_ROLE_KEY"])

    def test_global_session_revocation_uses_the_user_token_not_service_role(self):
        http = Mock()
        http.return_value = Mock(status_code=204)
        client = SupabaseAdminRestClient(ENV, http_request=http)
        self.assertTrue(client.revoke_user_sessions("verified.user.jwt"))
        self.assertEqual(http.call_args.args[0], "POST")
        self.assertEqual(http.call_args.kwargs["params"], {"scope": "global"})
        self.assertEqual(http.call_args.kwargs["headers"]["Authorization"], "Bearer verified.user.jwt")

    def test_approved_upload_claim_and_private_storage_download(self):
        http = Mock()
        claim_response = Mock(status_code=200)
        claim_response.json.return_value = [{"job_id": "job-1", "provider_channel_id": "UC123"}]
        media_response = Mock(status_code=200)
        media_response.content = b"private-mp4"
        http.side_effect = [claim_response, media_response]
        client = SupabaseAdminRestClient(ENV, http_request=http)
        job = client.claim_next_approved_shorts_job("upload-worker", daily_limit=3)
        self.assertEqual(job["provider_channel_id"], "UC123")
        key = "wsp_11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/" + "c" * 32 + ".mp4"
        content = client.download_storage_object(key)
        self.assertEqual(content, b"private-mp4")
        self.assertIn("/rpc/claim_next_approved_shorts_job", http.call_args_list[0].args[1])
        self.assertIn("/storage/v1/object/authenticated/nexus-shorts/", http.call_args_list[1].args[1])


    def test_account_deletion_oauth_state_rpc_methods_are_allowlisted_and_validate_fingerprint(self):
        http = Mock()
        response = Mock(status_code=200)
        response.json.return_value = [{"state": "revoked"}]
        http.return_value = response
        client = SupabaseAdminRestClient(ENV, http_request=http)
        user_id = "11111111-1111-4111-8111-111111111111"
        fingerprint = "a" * 64

        self.assertEqual(client.get_account_deletion_oauth_state(user_id, fingerprint), "revoked")
        self.assertIn("/rpc/get_account_deletion_oauth_state", http.call_args.args[1])
        self.assertEqual(http.call_args.kwargs["json"]["p_provider_account_hash"], fingerprint)
        self.assertEqual(client.set_account_deletion_oauth_state(user_id, fingerprint, "revoked"), "revoked")
        self.assertIn("/rpc/set_account_deletion_oauth_state", http.call_args.args[1])
        self.assertEqual(http.call_args.kwargs["json"]["p_state"], "revoked")
        with self.assertRaises(ValueError):
            client.get_account_deletion_oauth_state(user_id, "not-a-fingerprint")
        with self.assertRaises(ValueError):
            client.set_account_deletion_oauth_state(user_id, fingerprint, "refresh-token")


if __name__ == "__main__":
    unittest.main()
