import unittest

from upload_safety import classify_upload_response


class UploadSafetyTests(unittest.TestCase):
    def test_confirms_only_private_video_with_id(self):
        self.assertEqual(
            classify_upload_response({"id": "abc123", "status": {"privacyStatus": "private"}}),
            ("private", "abc123", "private"),
        )

    def test_flags_non_private_or_missing_privacy_status(self):
        self.assertEqual(
            classify_upload_response({"id": "abc123", "status": {"privacyStatus": "public"}}),
            ("privacy_unverified", "abc123", "public"),
        )
        self.assertEqual(
            classify_upload_response({"id": "abc123", "status": {}}),
            ("privacy_unverified", "abc123", None),
        )

    def test_rejects_missing_video_id_and_invalid_payload(self):
        self.assertEqual(classify_upload_response({"status": {"privacyStatus": "private"}}),
                         ("missing_video_id", None, None))
        self.assertEqual(classify_upload_response(None), ("invalid_response", None, None))


if __name__ == "__main__":
    unittest.main()
