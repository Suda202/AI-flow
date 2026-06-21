import unittest
from unittest.mock import Mock, patch

import main


class SummarySafetyTests(unittest.TestCase):
    def test_hides_prompt_leak(self):
        leaked = """根据以下视频描述，生成一份便于快速判断是否值得观看的中文短摘要。

视频标题：Example
频道：Example Channel

格式要求（纯文本，不要 markdown）：
- 第一行用"结论："开头
"""
        self.assertEqual(main.sanitize_summary_text(leaked), main.SUMMARY_PROMPT_LEAK_FALLBACK)
        self.assertEqual(main.trim_summary(leaked), main.SUMMARY_PROMPT_LEAK_FALLBACK)

    def test_keeps_valid_summary(self):
        summary = "结论：这条视频适合快速了解 AI 产品策略。\n（1）聚焦商业化路径\n适合：做产品规划前观看"
        self.assertEqual(main.sanitize_summary_text(summary), summary)

    def test_hides_internal_reasoning_leak(self):
        leaked = "{'thinking': 'The user asks me to generate a quick judgment summary.', 'signature': 'abc'}"
        self.assertEqual(main.sanitize_summary_text(leaked), main.SUMMARY_PROMPT_LEAK_FALLBACK)
        self.assertEqual(main.trim_summary(leaked), main.SUMMARY_PROMPT_LEAK_FALLBACK)

    def test_call_llm_does_not_stringify_thinking_only_blocks(self):
        response = Mock()
        response.json.return_value = {
            "content": [
                {
                    "type": "thinking",
                    "thinking": "The user asks me to generate a quick judgment summary.",
                    "signature": "abc",
                }
            ]
        }

        with patch.object(main, "DEEPSEEK_API_KEY", "test-key"), patch("main.requests.post", return_value=response):
            self.assertIsNone(main.call_llm("prompt"))

    def test_call_llm_extracts_text_after_thinking_blocks(self):
        response = Mock()
        response.json.return_value = {
            "content": [
                {"type": "thinking", "thinking": "internal reasoning"},
                {"type": "text", "text": "结论：值得看。\n适合：产品判断"},
            ]
        }

        with patch.object(main, "DEEPSEEK_API_KEY", "test-key"), patch("main.requests.post", return_value=response):
            self.assertEqual(main.call_llm("prompt"), "结论：值得看。\n适合：产品判断")

    def test_call_llm_uses_openai_compatible_chat_completions(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "结论：值得看。\n适合：产品判断",
                    }
                }
            ]
        }

        with (
            patch.object(main, "DEEPSEEK_API_KEY", "test-key"),
            patch.object(main, "DEEPSEEK_API_BASE", "https://api.example.test/v1"),
            patch.object(main, "DEEPSEEK_MODEL", "test-model"),
            patch("main.requests.post", return_value=response) as post,
        ):
            self.assertEqual(main.call_llm("prompt"), "结论：值得看。\n适合：产品判断")

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.example.test/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["json"]["model"], "test-model")


if __name__ == "__main__":
    unittest.main()
