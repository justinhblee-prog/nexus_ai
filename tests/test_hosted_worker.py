import os
import tempfile
import unittest
from unittest.mock import Mock

from hosted_worker import process_one_job


JOB = {
    "job_id": "22222222-2222-4222-8222-222222222222",
    "workspace_id": "wsp_11111111-1111-4111-8111-111111111111",
    "lease_token": "lease-token",
    "topic": "AI creator workflow",
    "title": "",
    "script": "",
    "channel_name": "NEXUS Channel",
    "persona": "전문가 톤",
}


class HostedWorkerTests(unittest.TestCase):
    def test_successful_render_uses_free_fallback_and_stops_for_human_review(self):
        admin = Mock()
        admin.claim_next_shorts_job.return_value = JOB
        admin.get_job_creator.return_value = "11111111-1111-4111-8111-111111111111"
        admin.create_asset.return_value = [{"asset_id": "asset-1"}]
        admin.finish_shorts_job.return_value = "review_pending"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as handle:
            handle.write(b"x" * 2048)
            path = handle.name
        renderer = Mock(return_value=(path, "Generated title", "Generated script"))
        validator = Mock(return_value={"ok": True, "errors": []})
        try:
            processed = process_one_job(admin, "worker-test", renderer=renderer, validator=validator)
        finally:
            if os.path.exists(path):
                os.remove(path)
        self.assertTrue(processed)
        self.assertEqual(renderer.call_args.kwargs["openai_key"], "")
        admin.upload_storage_object.assert_called_once()
        admin.create_asset.assert_called_once()
        admin.finish_shorts_job.assert_called_once()
        finish_args, finish_kwargs = admin.finish_shorts_job.call_args
        self.assertTrue(finish_args[2])
        self.assertTrue(finish_kwargs["output_storage_key"].startswith(JOB["workspace_id"] + "/"))
        self.assertEqual(finish_kwargs["title"], "Generated title")

    def test_no_available_jobs_does_not_start_renderer(self):
        admin = Mock()
        admin.claim_next_shorts_job.return_value = None
        renderer = Mock()
        self.assertFalse(process_one_job(admin, "worker-test", renderer=renderer))
        renderer.assert_not_called()

    def test_quality_failure_is_reported_and_never_uploaded(self):
        admin = Mock()
        admin.claim_next_shorts_job.return_value = JOB
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as handle:
            handle.write(b"x" * 2048)
            path = handle.name
        renderer = Mock(return_value=(path, "Title", "Script"))
        validator = Mock(return_value={"ok": False, "errors": ["h264_video"]})
        try:
            processed = process_one_job(admin, "worker-test", renderer=renderer, validator=validator)
        finally:
            if os.path.exists(path):
                os.remove(path)
        self.assertTrue(processed)
        admin.upload_storage_object.assert_not_called()
        admin.finish_shorts_job.assert_called_once()
        self.assertFalse(admin.finish_shorts_job.call_args.args[2])
        self.assertEqual(admin.finish_shorts_job.call_args.kwargs["error"], "RenderQualityError")

    def test_worker_lease_loss_prevents_media_upload(self):
        admin = Mock()
        admin.claim_next_shorts_job.return_value = JOB
        admin.heartbeat_shorts_job.return_value = False
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as handle:
            handle.write(b"x" * 2048)
            path = handle.name
        renderer = Mock(return_value=(path, "Title", "Script"))
        validator = Mock(return_value={"ok": True, "errors": []})
        try:
            processed = process_one_job(admin, "worker-test", renderer=renderer, validator=validator, lease_seconds=60)
        finally:
            if os.path.exists(path):
                os.remove(path)
        self.assertTrue(processed)
        admin.upload_storage_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()
