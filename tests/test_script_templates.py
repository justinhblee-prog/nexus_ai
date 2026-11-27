import unittest

from script_templates import fallback_script, normalize_script_payload, split_manual_script


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

    def test_manual_script_is_split_into_four_to_eight_sentences(self):
        script = "첫째 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다."
        self.assertEqual(len(split_manual_script(script)), 4)

    def test_manual_script_rejects_too_few_sentences_and_oversized_text(self):
        with self.assertRaises(ValueError):
            split_manual_script("한 문장입니다.")
        with self.assertRaises(ValueError):
            split_manual_script("가" * 20001)

    def test_valid_model_payload_is_bounded_and_normalized(self):
        data = {"title": "  Topic title  ", "sentences": [" one ", "two", "three", "four"], "image_prompt": " scene "}
        self.assertEqual(
            normalize_script_payload(data, "Future Leak", "topic"),
            ("Topic title", ["one", "two", "three", "four"], "scene"),
        )


if __name__ == "__main__":
    unittest.main()
