import unittest
from unittest.mock import patch

import youtube_analytics


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeReports:
    def __init__(self, result):
        self.result = result
        self.kwargs = None

    def query(self, **kwargs):
        self.kwargs = kwargs
        return FakeRequest(self.result)


class FakeAnalytics:
    def __init__(self, result):
        self.report = FakeReports(result)

    def reports(self):
        return self.report


class FakeChannelList:
    def list(self, **kwargs):
        return FakeRequest({
            "items": [{"statistics": {"subscriberCount": "1500", "hiddenSubscriberCount": False}}]
        })


class FakeYouTube:
    def channels(self):
        return FakeChannelList()


class FakeCredentials:
    expired = False
    refresh_token = "refresh-token"

    def __init__(self, scopes=True):
        self.scopes = scopes

    def has_scopes(self, _scopes):
        return self.scopes


class YouTubeAnalyticsTests(unittest.TestCase):
    def setUp(self):
        youtube_analytics.clear_platform_metrics_cache()

    def test_missing_token_returns_null_metrics_without_estimating(self):
        with patch.object(youtube_analytics, "get_channel_token_path", return_value="missing-token.json"), \
             patch.object(youtube_analytics.os.path, "isfile", return_value=False):
            result = youtube_analytics.get_platform_metrics(["Future Leak"], force_refresh=True)

        self.assertEqual(result["status"], "not_connected")
        self.assertIsNone(result["views"])
        self.assertIsNone(result["subscriber_count"])
        self.assertIsNone(result["revenue"])
        self.assertEqual(result["revenue_status"], "monetary_scope_not_requested")

    def test_old_upload_only_token_requests_read_only_analytics_consent(self):
        credentials = FakeCredentials(scopes=False)
        with patch.object(youtube_analytics, "get_channel_token_path", return_value="old-token.json"), \
             patch.object(youtube_analytics.os.path, "isfile", return_value=True), \
             patch.object(youtube_analytics, "_load_credentials", return_value=credentials), \
             patch.object(youtube_analytics, "_build_clients") as build_clients:
            result = youtube_analytics.get_platform_metrics(["Money Glitch"], force_refresh=True)

        self.assertEqual(result["status"], "scope_required")
        self.assertEqual(result["channels"][0]["status"], "scope_required")
        build_clients.assert_not_called()

    def test_connected_channel_aggregates_actual_provider_metrics(self):
        headers = [
            "views", "estimatedMinutesWatched", "averageViewDuration",
            "likes", "comments", "shares", "subscribersGained", "subscribersLost",
        ]
        report = {
            "columnHeaders": [{"name": name} for name in headers],
            "rows": [[1000, 500, 30, 100, 20, 10, 15, 3]],
        }
        analytics = FakeAnalytics(report)
        youtube = FakeYouTube()
        with patch.object(youtube_analytics, "get_channel_token_path", return_value="channel-token.json"), \
             patch.object(youtube_analytics.os.path, "isfile", return_value=True), \
             patch.object(youtube_analytics, "_load_credentials", return_value=FakeCredentials()), \
             patch.object(youtube_analytics, "_build_clients", return_value=(analytics, youtube)):
            result = youtube_analytics.get_platform_metrics(["Brain Glitch"], force_refresh=True)

        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["subscriber_count"], 1500)
        self.assertEqual(result["views"], 1000)
        self.assertEqual(result["views_28d"], 1000)
        self.assertEqual(result["watch_minutes_28d"], 500)
        self.assertEqual(result["subscribers_gained_28d"], 15)
        self.assertEqual(result["subscribers_lost_28d"], 3)
        self.assertAlmostEqual(result["engagement_rate"], 13.0)
        self.assertIsNone(result["revenue"])
        self.assertEqual(analytics.report.kwargs["ids"], "channel==MINE")
        self.assertEqual(analytics.report.kwargs["metrics"], ",".join(youtube_analytics._METRICS))
        self.assertEqual(result["channels"][0]["status"], "connected")

    def test_cached_provider_metrics_are_reused_until_explicit_refresh(self):
        headers = [{"name": "views"}]
        analytics = FakeAnalytics({"columnHeaders": headers, "rows": [[42]]})
        youtube = FakeYouTube()
        with patch.object(youtube_analytics, "get_channel_token_path", return_value="channel-token.json"), \
             patch.object(youtube_analytics.os.path, "isfile", return_value=True), \
             patch.object(youtube_analytics, "_load_credentials", return_value=FakeCredentials()), \
             patch.object(youtube_analytics, "_build_clients", return_value=(analytics, youtube)) as build_clients:
            first = youtube_analytics.get_platform_metrics(["Brain Glitch"], force_refresh=True)
            second = youtube_analytics.get_platform_metrics(["Brain Glitch"])

        self.assertEqual(first["views"], 42)
        self.assertEqual(second["views"], 42)
        self.assertEqual(build_clients.call_count, 1)


if __name__ == "__main__":
    unittest.main()
