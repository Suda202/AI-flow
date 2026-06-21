import unittest
from datetime import datetime, timezone

from preference_learning import (
    apply_daily_feedback,
    build_ranking_hints,
    consolidate_weekly,
    default_state,
    normalize_feedback_events,
    should_run_weekly,
)


UTC = timezone.utc


def facet(net, content_ids, last_seen="2026-06-27T01:00:00Z"):
    return {
        "net": float(net),
        "evidence_count": len(content_ids),
        "content_ids": list(content_ids),
        "last_seen": last_seen,
    }


class PreferenceLearningTests(unittest.TestCase):
    def test_normalizes_legacy_and_generic_feedback_without_duplicate_events(self):
        feedback = {
            "video-1": {
                "video_meta": {
                    "title": "Agent workflow",
                    "author": "AI Engineer",
                    "url": "https://youtube.com/watch?v=video-1",
                },
                "reactions": [{
                    "reaction": "like",
                    "timestamp": "2026-06-20T01:00:00Z",
                }],
            },
            "aihot:item-1": {
                "content_meta": {
                    "content_id": "aihot:item-1",
                    "content_type": "aihot",
                    "title": "Loop Engineering",
                    "creator": "Addy Osmani",
                    "url": "https://example.com/loop",
                    "category": "tip",
                    "selection_tags": ["Loop Engineering", "前沿趋势"],
                },
                "reactions": [{
                    "event_id": "evt-1",
                    "reaction": "like",
                    "timestamp": "2026-06-20T02:00:00Z",
                }],
            },
        }

        events = normalize_feedback_events(feedback)

        self.assertEqual([event["content_type"] for event in events], ["youtube", "aihot"])
        self.assertEqual(len({event["event_id"] for event in events}), 2)
        self.assertEqual(events[1]["selection_tags"], ["Loop Engineering", "前沿趋势"])

    def test_daily_feedback_is_idempotent_and_one_click_stays_short_term(self):
        now = datetime(2026, 6, 21, tzinfo=UTC)
        event = {
            "event_id": "evt-1",
            "content_id": "aihot:1",
            "reaction": "like",
            "timestamp": "2026-06-21T01:00:00Z",
            "topics": ["Loop Engineering", "Agent"],
            "formats": ["实战教程"],
            "values": ["前沿趋势", "实用方法"],
            "sources": ["Addy Osmani"],
        }

        first = apply_daily_feedback(default_state(), [event], now)
        second = apply_daily_feedback(first, [event], now)

        self.assertEqual(second, first)
        self.assertEqual(first["short_term"]["topics"]["Loop Engineering"]["net"], 1.0)
        self.assertNotIn("Loop Engineering", first["long_term"].get("topics", {}))

    def test_daily_feedback_decays_existing_short_term_signal_once_per_day(self):
        state = default_state()
        state["last_daily_run"] = "2026-06-20T00:00:00Z"
        state["short_term"] = {"topics": {"Agent": facet(2, ["1", "2"], "2026-06-20T00:00:00Z")}}

        result = apply_daily_feedback(state, [], datetime(2026, 6, 21, tzinfo=UTC))

        self.assertAlmostEqual(result["short_term"]["topics"]["Agent"]["net"], 1.8)

    def test_weekly_consolidation_requires_two_distinct_items_and_net_two(self):
        state = default_state()
        state["short_term"] = {
            "topics": {
                "Loop Engineering": facet(2, ["aihot:1", "aihot:2"]),
                "孤立兴趣": facet(1, ["aihot:3"]),
            }
        }

        result = consolidate_weekly(state, datetime(2026, 6, 28, tzinfo=UTC))

        self.assertGreater(result["long_term"]["topics"]["Loop Engineering"]["net"], 0)
        self.assertNotIn("孤立兴趣", result["long_term"]["topics"])

    def test_disliking_tutorial_format_does_not_reduce_agent_parent_topic(self):
        state = default_state()
        state["short_term"] = {
            "topics": {"Agent": facet(1, ["1"])},
            "formats": {"入门教程": facet(-2, ["1", "2"])},
        }

        result = consolidate_weekly(state, datetime(2026, 6, 28, tzinfo=UTC))

        self.assertLess(result["long_term"]["formats"]["入门教程"]["net"], 0)
        self.assertGreaterEqual(result["long_term"].get("topics", {}).get("Agent", {}).get("net", 0), 0)

    def test_weekly_due_after_seven_days(self):
        state = default_state()
        state["last_weekly_run"] = "2026-06-14T00:00:00Z"
        self.assertTrue(should_run_weekly(state, datetime(2026, 6, 21, tzinfo=UTC)))
        self.assertFalse(should_run_weekly(state, datetime(2026, 6, 20, tzinfo=UTC)))

    def test_ranking_hints_separate_recent_and_stable_preferences(self):
        state = default_state()
        state["short_term"] = {
            "topics": {"Loop Engineering": facet(1, ["1"])},
            "formats": {"入门教程": facet(-1, ["2"])},
        }
        state["long_term"] = {
            "topics": {"Agentic Engineering": facet(3, ["3", "4", "5"])},
        }

        hints = build_ranking_hints(state)

        self.assertIn("近期偏好：Loop Engineering", hints)
        self.assertIn("稳定偏好：Agentic Engineering", hints)
        self.assertIn("近期回避：入门教程", hints)


if __name__ == "__main__":
    unittest.main()
