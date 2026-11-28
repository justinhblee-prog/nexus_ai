import unittest

from social_platforms import get_social_platform_catalog


class SocialPlatformCatalogTests(unittest.TestCase):
    def test_youtube_is_connectable_only_with_complete_server_oauth_configuration(self):
        env = {
            "NEXUS_GOOGLE_OAUTH_CLIENT_ID": "configured",
            "NEXUS_GOOGLE_OAUTH_CLIENT_SECRET": "configured",
            "NEXUS_GOOGLE_OAUTH_REDIRECT_URI": "https://example.test/api/hosted/youtube/callback",
            "NEXUS_HOSTED_APP_URL": "https://example.test",
        }
        items = get_social_platform_catalog(env)
        youtube = next(item for item in items if item["id"] == "youtube")
        self.assertEqual(youtube["status"], "ready")
        self.assertTrue(youtube["connectable"])
        self.assertTrue(youtube["multiple_accounts"])

    def test_missing_youtube_oauth_configuration_is_not_misreported_as_ready(self):
        youtube = next(item for item in get_social_platform_catalog({}) if item["id"] == "youtube")
        self.assertEqual(youtube["status"], "setup_required")
        self.assertFalse(youtube["connectable"])

    def test_platform_catalog_distinguishes_configured_and_future_connectors(self):
        items = get_social_platform_catalog({})
        self.assertEqual(
            {item["id"] for item in items},
            {"youtube", "tiktok", "instagram", "facebook", "linkedin"},
        )
        for provider in items:
            self.assertTrue(provider["multiple_accounts"])
        tiktok = next(item for item in items if item["id"] == "tiktok")
        self.assertEqual(tiktok["status"], "setup_required")
        self.assertFalse(tiktok["connectable"])
        for provider in items:
            if provider["id"] in {"instagram", "facebook", "linkedin"}:
                self.assertEqual(provider["status"], "coming_soon")
                self.assertFalse(provider["connectable"])

    def test_tiktok_is_connectable_after_server_credentials_are_configured(self):
        env = {
            "NEXUS_TIKTOK_CLIENT_KEY": "configured",
            "NEXUS_TIKTOK_CLIENT_SECRET": "configured",
            "NEXUS_TIKTOK_OAUTH_REDIRECT_URI": "https://example.test/api/hosted/tiktok/callback",
            "NEXUS_HOSTED_APP_URL": "https://example.test",
        }
        tiktok = next(item for item in get_social_platform_catalog(env) if item["id"] == "tiktok")
        self.assertEqual(tiktok["status"], "ready")
        self.assertTrue(tiktok["connectable"])
        self.assertIn("video.publish", tiktok["detail"])


if __name__ == "__main__":
    unittest.main()
