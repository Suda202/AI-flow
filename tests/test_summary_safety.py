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
        self.assertEqual(kwargs["json"]["thinking"], {"type": "disabled"})

    def test_call_llm_can_explicitly_enable_thinking(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": "answer"}}]
        }

        with (
            patch.object(main, "DEEPSEEK_API_KEY", "test-key"),
            patch("main.requests.post", return_value=response) as post,
        ):
            self.assertEqual(main.call_llm("prompt", thinking=True), "answer")

        self.assertEqual(post.call_args.kwargs["json"]["thinking"], {"type": "enabled"})

    def test_call_llm_retries_once_after_reasoning_only_response(self):
        reasoning_only = Mock(status_code=200)
        reasoning_only.json.return_value = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "internal reasoning",
                    },
                }
            ],
            "usage": {"prompt_tokens": 800, "completion_tokens": 1200},
        }
        completed = Mock(status_code=200)
        completed.json.return_value = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "1|值得观看"},
                }
            ]
        }

        with (
            patch.object(main, "DEEPSEEK_API_KEY", "test-key"),
            patch("main.requests.post", side_effect=[reasoning_only, completed]) as post,
            patch("builtins.print") as output,
        ):
            result = main.call_llm("prompt", max_tokens=1200, empty_response_retries=1)

        self.assertEqual(result, "1|值得观看")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["max_tokens"], 1200)
        logs = "\n".join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn("finish_reason=length", logs)
        self.assertIn("reasoning_content=present", logs)
        self.assertIn("重试 1/1", logs)

    def test_call_llm_does_not_retry_api_error(self):
        response = Mock(status_code=401)
        response.json.return_value = {"error": {"message": "invalid credentials"}}

        with (
            patch.object(main, "DEEPSEEK_API_KEY", "test-key"),
            patch("main.requests.post", return_value=response) as post,
        ):
            result = main.call_llm("prompt", empty_response_retries=1)

        self.assertIsNone(result)
        post.assert_called_once()

    def test_rank_candidates_uses_larger_budget_and_empty_response_retry(self):
        candidates = [
            {
                "author": "Example",
                "title": "AI product strategy",
                "duration_str": "20:00",
                "view_count": 5000,
                "description": "A detailed product strategy discussion.",
            }
        ]

        with patch.object(main, "call_llm", return_value="1|产品策略复盘") as call_llm:
            result = main.rank_candidates(candidates, 1, {})

        self.assertEqual(result, [{"index": 0, "reason": "产品策略复盘"}])
        call_llm.assert_called_once()
        self.assertEqual(call_llm.call_args.kwargs["max_tokens"], main.RANKING_MAX_TOKENS)
        self.assertEqual(call_llm.call_args.kwargs["empty_response_retries"], 1)


if __name__ == "__main__":
    unittest.main()
