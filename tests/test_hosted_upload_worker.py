import unittest
from unittest.mock import Mock

from hosted_upload_worker import process_one_upload


JOB = {
    "job_id": "22222222-2222-4222-8222-222222222222",
    "workspace_id": "wsp_11111111-1111-4111-8111-111111111111",
    "channel_id": "33333333-3333-4333-8333-333333333333",
    "connection_id": "44444444-4444-4444-8444-444444444444",
    "provider_channel_id": "UC123",
    "topic": "NEXUS Shorts",
    "title": "Private upload test",
    "script": "A short script",
    "output_storage_key": "wsp_11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222/" + "a" * 32 + ".mp4",
    "lease_token": "upload-lease-token",
    "provider_video_id": None,
}


class HostedUploadWorkerTests(unittest.TestCase):
    def test_approved_job_uploads_private_to_exactly_connected_channel(self):
        admin = Mock()
        admin.claim_next_approved_shorts_job.return_value = JOB
        admin.get_credential.return_value = {
            "encrypted_refresh_token_hex": "aabb",
            "encryption_key_version": "v1",
        }
        admin.download_storage_object.return_value = b"rendered-mp4"
        admin.record_shorts_upload_video_id.return_value = True
        admin.finish_shorts_upload.return_value = "published"
        config = Mock()
        config.refresh_access_token.return_value = "fresh-access"
        config.upload_private_video.return_value = {
            "video_id": "video-123",
            "channel_id": "UC123",
            "privacy_status": "private",
        }
        result = process_one_upload(
            admin, "upload-worker", oauth_config_factory=lambda: config,
            decrypt_token=lambda ciphertext, version: "refresh-token",
        )
        self.assertTrue(result)
        config.refresh_access_token.assert_called_once_with("refresh-token")
        config.upload_private_video.assert_called_once()
        self.assertEqual(config.upload_private_video.call_args.args[4], "UC123")
        admin.record_shorts_upload_video_id.assert_called_once()
        admin.finish_shorts_upload.assert_called_once()
        self.assertTrue(admin.finish_shorts_upload.call_args.args[2])

    def test_retry_with_recorded_video_id_does_not_upload_duplicate(self):
        admin = Mock()
        admin.claim_next_approved_shorts_job.return_value = {**JOB, "provider_video_id": "video-123"}
        admin.finish_shorts_upload.return_value = "published"
        config_factory = Mock()
        result = process_one_upload(admin, "upload-worker", oauth_config_factory=config_factory)
        self.assertTrue(result)
        config_factory.assert_not_called()
        admin.download_storage_object.assert_not_called()
        admin.finish_shorts_upload.assert_called_once_with(
            JOB["job_id"], JOB["lease_token"], True, video_id="video-123",
            max_attempts=DEFAULT_MAX_ATTEMPTS,
        )

    def test_no_approved_jobs_does_not_refresh_or_upload(self):
        admin = Mock()
        admin.claim_next_approved_shorts_job.return_value = None
        config_factory = Mock()
        self.assertFalse(process_one_upload(admin, "upload-worker", oauth_config_factory=config_factory))
        config_factory.assert_not_called()

    def test_upload_failure_is_recorded_without_public_fallback(self):
        admin = Mock()
        admin.claim_next_approved_shorts_job.return_value = JOB
        admin.get_credential.return_value = {
            "encrypted_refresh_token_hex": "aabb",
            "encryption_key_version": "v1",
        }
        admin.download_storage_object.return_value = b"rendered-mp4"
        config = Mock()
        config.refresh_access_token.return_value = "fresh-access"
        config.upload_private_video.side_effect = RuntimeError("private upload rejected")
        result = process_one_upload(
            admin, "upload-worker", oauth_config_factory=lambda: config,
            decrypt_token=lambda ciphertext, version: "refresh-token",
        )
        self.assertTrue(result)
        admin.finish_shorts_upload.assert_called_once()
        self.assertFalse(admin.finish_shorts_upload.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
