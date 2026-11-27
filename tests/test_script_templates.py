import unittest

from script_templates import fallback_script, normalize_script_payload


class ScriptTemplateTests(unittest.TestCase):
    def test_fallback_is_six_nonempty_korean_sentences(self):
        title, sentences, image_prompt = fallback_script("Future Leak", "AI 반도체")
        self.assertIn("AI 반도체", title)
        self.assertEqual(len(sentences), 6)
        self.assertTrue(all(sentence.strip() for sentence in sentences))
        self.assertEqual(image_prompt, "")
        self.assertTrue(any("확인" in sentence for sentence in sentences))

    def test_invalid_model_payload_uses_safe_fallback(self):
        self.assertEqual(
            normalize_script_payload({"title": "", "sentences": []}, "Future Leak", "양자 컴퓨팅"),
            fallback_script("Future Leak", "양자 컴퓨팅"),
        )

    def test_valid_model_payload_is_bounded_and_normalized(self):
        data = {"title": "  Topic title  ", "sentences": [" one ", "two", "three", "four"], "image_prompt": " scene "}
        self.assertEqual(
            normalize_script_payload(data, "Future Leak", "topic"),
            ("Topic title", ["one", "two", "three", "four"], "scene"),
        )


if __name__ == "__main__":
    unittest.main()
