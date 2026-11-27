import unittest

from oauth_config import ANALYTICS_SCOPES, SCOPES, UPLOAD_SCOPES, get_channel_token_path


class OAuthConfigTests(unittest.TestCase):
    def test_upload_and_read_only_analytics_scopes_are_separate_and_explicit(self):
        self.assertIn("https://www.googleapis.com/auth/youtube.upload", UPLOAD_SCOPES)
        self.assertIn("https://www.googleapis.com/auth/yt-analytics.readonly", ANALYTICS_SCOPES)
        self.assertIn("https://www.googleapis.com/auth/youtube.readonly", ANALYTICS_SCOPES)
        self.assertEqual(SCOPES, UPLOAD_SCOPES + ANALYTICS_SCOPES)

    def test_channel_token_path_cannot_escape_tokens_directory(self):
        self.assertEqual(get_channel_token_path("../Brain Glitch"), "tokens/yt_token_BrainGlitch.json")
        with self.assertRaises(ValueError):
            get_channel_token_path("../..///")


if __name__ == "__main__":
    unittest.main()
