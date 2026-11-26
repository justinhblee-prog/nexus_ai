import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from video_qa import validate_video


class VideoQATests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "sample.mp4")
        with open(self.path, "wb") as handle:
            handle.write(b"x" * 2048)

    def tearDown(self):
        self.temp.cleanup()

    def test_accepts_valid_vertical_h264_aac_short(self):
        payload = {
            "format": {"duration": "28.5"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }
        with patch("video_qa.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload))):
            result = validate_video(self.path, ffprobe_bin="ffprobe")
        self.assertTrue(result["ok"])
        self.assertEqual(result["metadata"]["duration_seconds"], 28.5)

    def test_rejects_wrong_dimensions_missing_audio_and_long_duration(self):
        payload = {
            "format": {"duration": "240"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
            ],
        }
        with patch("video_qa.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload))):
            result = validate_video(self.path, ffprobe_bin="ffprobe")
        self.assertFalse(result["ok"])
        self.assertIn("vertical_1080x1920", result["errors"])
        self.assertIn("audio_stream_present", result["errors"])
        self.assertIn("duration_in_shorts_range", result["errors"])

    def test_missing_file_fails_without_running_ffprobe(self):
        with patch("video_qa.subprocess.run") as probe:
            result = validate_video(self.path + ".missing")
        self.assertFalse(result["ok"])
        self.assertIn("video_file_missing", result["errors"])
        probe.assert_not_called()

    def test_ffprobe_unavailable_fails_closed(self):
        with patch("video_qa.subprocess.run", side_effect=FileNotFoundError):
            result = validate_video(self.path, ffprobe_bin="ffprobe")
        self.assertFalse(result["ok"])
        self.assertIn("ffprobe_not_installed", result["errors"])


if __name__ == "__main__":
    unittest.main()
