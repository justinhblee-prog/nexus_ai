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


if __name__ == "__main__":
    unittest.main()
