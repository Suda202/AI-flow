import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from preference_learning import default_state
import update_preferences
from update_preferences import (
    classify_events,
    parse_classification_response,
    run_preference_update,
)


UTC = timezone.utc


def sample_event(event_id="evt-1", reaction="like"):
    return {
        "event_id": event_id,
        "content_id": "aihot:loop-1",
        "content_type": "aihot",
        "title": "Loop Engineering: a practical guide for coding agents",
        "creator": "Addy Osmani",
        "url": "https://example.com/loop",
        "category": "industry",
        "selection_tags": ["Loop Engineering", "Agent", "前沿趋势"],
        "reaction": reaction,
        "timestamp": "2026-06-21T01:00:00Z",
    }


class PreferenceClassificationTests(unittest.TestCase):
    def test_default_model_call_uses_openai_compatible_deepseek_api(self):
        call_llm = getattr(update_preferences, "call_llm", None)
        self.assertIsNotNone(call_llm, "update_preferences.call_llm should exist")

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": '{"events":[]}'}}]
        }
        with (
            patch.object(update_preferences, "DEEPSEEK_API_KEY", "test-key"),
            patch.object(update_preferences, "DEEPSEEK_API_BASE", "https://api.example.test"),
            patch.object(update_preferences, "DEEPSEEK_MODEL", "deepseek-v4-flash"),
            patch.object(update_preferences.requests, "post", return_value=response) as post,
        ):
            self.assertEqual(call_llm("prompt"), '{"events":[]}')

        _, kwargs = post.call_args
        self.assertEqual(post.call_args.args[0], "https://api.example.test/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["json"]["model"], "deepseek-v4-flash")
        self.assertEqual(kwargs["json"]["thinking"], {"type": "disabled"})

    def test_parses_fenced_json_and_ignores_unknown_events(self):
        raw = """```json
        {"events":[
          {"event_id":"evt-1","topics":["Agent","Loop Engineering"],"formats":["实战教程"],"values":["前沿趋势"],"sources":["Addy Osmani"]},
          {"event_id":"unknown","topics":["无关"],"formats":[],"values":[],"sources":[]}
        ]}
        ```"""

        parsed = parse_classification_response(raw, {"evt-1"})

        self.assertEqual(list(parsed), ["evt-1"])
        self.assertEqual(parsed["evt-1"]["topics"], ["Agent", "Loop Engineering"])

    def test_invalid_model_response_falls_back_to_deterministic_facets(self):
        classified = classify_events(
            [sample_event()],
            model_call=lambda _prompt: "not json",
        )

        self.assertEqual(len(classified), 1)
        self.assertIn("Agent", classified[0]["topics"])
        self.assertIn("Loop Engineering", classified[0]["topics"])
        self.assertIn("实战教程", classified[0]["formats"])
        self.assertIn("前沿趋势", classified[0]["values"])

    def test_model_classification_is_merged_with_original_event(self):
        payload = {
            "events": [{
                "event_id": "evt-1",
                "topics": ["Agentic Engineering"],
                "formats": ["深度分析"],
                "values": ["方法论"],
                "sources": ["Addy Osmani"],
            }]
        }

        classified = classify_events(
            [sample_event()],
            model_call=lambda _prompt: json.dumps(payload, ensure_ascii=False),
        )

        self.assertEqual(classified[0]["reaction"], "like")
        self.assertEqual(classified[0]["topics"], ["Agentic Engineering"])

    def test_fallback_learns_content_format_without_conflating_it_with_topic(self):
        event = {
            **sample_event(),
            "content_type": "follow_builders_podcast",
            "title": "A conversation with an AI product founder",
            "creator": "Training Data",
            "category": "builder-podcast",
            "selection_tags": [],
        }

        classified = classify_events([event], model_call=lambda _prompt: None)

        self.assertIn("播客访谈", classified[0]["formats"])
        self.assertIn("一手观点", classified[0]["values"])
        self.assertNotIn("播客访谈", classified[0]["topics"])


class PreferenceUpdateIntegrationTests(unittest.TestCase):
    def test_update_processes_only_new_events_and_persists_state(self):
        feedback = {
            "aihot:loop-1": {
                "content_meta": {
                    "content_id": "aihot:loop-1",
                    "content_type": "aihot",
                    "title": sample_event()["title"],
                    "creator": "Addy Osmani",
                    "url": "https://example.com/loop",
                    "selection_tags": ["Loop Engineering", "Agent"],
                },
                "reactions": [{
                    "event_id": "evt-1",
                    "reaction": "like",
                    "timestamp": "2026-06-21T01:00:00Z",
                }],
            }
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            feedback_path = base / "feedback.json"
            profile_path = base / "profile.json"
            state_path = base / "preference_state.json"
            hints_path = base / "ranking_hints.txt"
            feedback_path.write_text(json.dumps(feedback, ensure_ascii=False))
            profile_path.write_text("{}")
            state_path.write_text(json.dumps(default_state()))

            first = run_preference_update(
                feedback_path=feedback_path,
                profile_path=profile_path,
                state_path=state_path,
                hints_path=hints_path,
                now=datetime(2026, 6, 21, tzinfo=UTC),
                model_call=lambda _prompt: None,
            )
            second = run_preference_update(
                feedback_path=feedback_path,
                profile_path=profile_path,
                state_path=state_path,
                hints_path=hints_path,
                now=datetime(2026, 6, 21, tzinfo=UTC),
                model_call=lambda _prompt: None,
            )

            self.assertEqual(first["new_event_count"], 1)
            self.assertEqual(second["new_event_count"], 0)
            saved_state = json.loads(state_path.read_text())
            self.assertEqual(
                saved_state["short_term"]["topics"]["Loop Engineering"]["net"],
                1.0,
            )
            self.assertIn("近期偏好：", hints_path.read_text())
            saved_profile = json.loads(profile_path.read_text())
            self.assertEqual(saved_profile["inferred_preferences"]["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()
