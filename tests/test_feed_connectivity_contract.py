import unittest

from trend_radar import HN_TOP_STORIES_URL, RSS_FEEDS


class FeedConnectivityContractTests(unittest.TestCase):
    def test_configured_sources_cover_four_regions_and_live_hacker_news(self):
        self.assertEqual({region for region, _, _ in RSS_FEEDS}, {"KR", "US", "JP", "GB"})
        self.assertEqual(len(RSS_FEEDS), 5)
        self.assertTrue(all(url.startswith("https://") for _, _, url in RSS_FEEDS))
        self.assertTrue(HN_TOP_STORIES_URL.startswith("https://"))
        self.assertIn("Google News KR", {label for _, label, _ in RSS_FEEDS})
        self.assertIn("Google News US", {label for _, label, _ in RSS_FEEDS})
        self.assertIn("Google News JP", {label for _, label, _ in RSS_FEEDS})
        self.assertIn("Google News UK", {label for _, label, _ in RSS_FEEDS})
        self.assertIn("BBC News", {label for _, label, _ in RSS_FEEDS})


if __name__ == "__main__":
    unittest.main()
