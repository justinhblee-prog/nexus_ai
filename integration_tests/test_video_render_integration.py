"""End-to-end local renderer smoke test; external AI and TTS providers are stubbed."""
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageFont

import video_maker
from video_qa import validate_video


class VideoRenderIntegrationTests(unittest.TestCase):
    def test_manual_script_renders_a_real_vertical_mp4_without_external_credentials(self):
        script = "첫 번째 핵심 사실을 확인합니다. 두 번째 배경을 살펴봅니다. 세 번째 근거를 비교합니다. 마지막으로 확인된 결론을 정리합니다."

        def offline_audio(_text, _channel, output_path):
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-t", "1.2", "-codec:a", "libmp3lame", "-q:a", "9", output_path,
                ],
                check=True,
                capture_output=True,
            )

        with tempfile.TemporaryDirectory() as workspace:
            previous = os.getcwd()
            os.chdir(workspace)
            try:
                with patch.object(video_maker, "create_cinematic_bg", return_value=Image.new("RGB", (1200, 2133), (12, 24, 42))), \
                     patch.object(video_maker, "generate_announcer_audio", side_effect=offline_audio), \
                     patch.object(video_maker, "get_korean_font", return_value=ImageFont.load_default()):
                    video_path, title, rendered_script = video_maker.render_pro_short(
                        "NEXUS Test", "테스트", "통합 렌더 테스트", script_override=script,
                        title_override="NEXUS 렌더 검증",
                    )

                self.assertTrue(os.path.isfile(video_path))
                self.assertGreater(os.path.getsize(video_path), 1024)
                self.assertEqual(title, "NEXUS 렌더 검증")
                self.assertEqual(rendered_script, script)
                qa = validate_video(video_path)
                self.assertTrue(qa["ok"], msg=str(qa["errors"]))
                self.assertEqual(qa["metadata"]["width"], 1080)
                self.assertEqual(qa["metadata"]["height"], 1920)
                self.assertEqual(qa["metadata"]["video_codec"], "h264")
                self.assertEqual(qa["metadata"]["audio_codec"], "aac")
                self.assertGreaterEqual(qa["metadata"]["duration_seconds"], 4.0)
                leftovers = [name for name in os.listdir("output") if name.endswith((".mp3", ".png"))]
                self.assertEqual(leftovers, [])
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
