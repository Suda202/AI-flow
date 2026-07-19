import unittest
from datetime import datetime, timezone

from information_sources import (
    canonicalize_url,
    dedupe_information_items,
    fetch_external_information_items,
    information_history_key,
    parse_ai_news_radar_payload,
    parse_follow_builders_payloads,
    parse_qmreader_payload,
)


NOW = datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)


class InformationSourceTests(unittest.TestCase):
    def test_follow_builders_uses_x_and_blogs_but_not_podcasts(self):
        x_payload = {
            "generatedAt": "2026-07-19T07:00:00Z",
            "x": [{
                "name": "Swyx",
                "handle": "swyx",
                "bio": "AI engineer",
                "tweets": [{
                    "id": "tweet-1",
                    "text": "AEO will become a meaningful revenue channel.",
                    "createdAt": "2026-07-19T06:00:00Z",
                    "url": "https://x.com/swyx/status/tweet-1",
                    "likes": 12,
                    "retweets": 2,
                    "replies": 3,
                }],
            }],
            "podcasts": [{"title": "must not be consumed"}],
        }
        blogs_payload = {
            "generatedAt": "2026-07-19T07:00:00Z",
            "blogs": [{
                "name": "Anthropic Engineering",
                "title": "Building reliable agents",
                "url": "https://example.com/reliable-agents",
                "publishedAt": "2026-07-19T05:00:00Z",
                "description": "An engineering note about agent reliability.",
                "content": "Long body that should not be copied into the card.",
            }],
        }

        items = parse_follow_builders_payloads(x_payload, blogs_payload, now=NOW, hours=24)

        self.assertEqual([item["content_type"] for item in items], ["follow_builders", "follow_builders"])
        self.assertEqual(items[0]["creator"], "Swyx")
        self.assertEqual(items[1]["summary"], "An engineering note about agent reliability.")
        self.assertNotIn("Long body", items[1]["summary"])
        self.assertTrue(all("podcast" not in item["category"] for item in items))

    def test_follow_builders_rejects_stale_or_url_less_items(self):
        payload = {
            "generatedAt": "2026-07-19T07:00:00Z",
            "x": [{
                "name": "Builder",
                "tweets": [
                    {"id": "stale", "text": "old", "createdAt": "2026-07-17T06:00:00Z", "url": "https://x.com/a"},
                    {"id": "no-url", "text": "missing url", "createdAt": "2026-07-19T06:00:00Z"},
                ],
            }],
        }

        self.assertEqual(parse_follow_builders_payloads(payload, {}, now=NOW, hours=24), [])

    def test_ai_news_radar_keeps_story_evidence_and_rejects_stale_snapshot(self):
        payload = {
            "generated_at": "2026-07-19T07:00:00Z",
            "items": [{
                "story_id": "story-1",
                "title": "Coding agents learn to repair CI failures",
                "url": "https://example.com/story?utm_source=radar",
                "latest_at": "2026-07-19T06:30:00Z",
                "score": 0.81,
                "source_count": 3,
                "primary_item": {"summary": "Three sources describe the same agent workflow."},
            }],
        }

        items = parse_ai_news_radar_payload(payload, now=NOW, hours=24)

        self.assertEqual(items[0]["content_type"], "ai_news_radar")
        self.assertEqual(items[0]["source_count"], 3)
        self.assertEqual(items[0]["score"], 81)
        stale = {**payload, "generated_at": "2026-07-16T07:00:00Z"}
        self.assertEqual(parse_ai_news_radar_payload(stale, now=NOW, hours=24), [])

    def test_qmreader_uses_public_metadata_not_style_rewrite(self):
        payload = {"entries": [{
            "id": "entry-1",
            "sourceId": "simonwillison",
            "title": "A new agent workflow",
            "titleZh": "一种新的 Agent 工作流",
            "link": "https://example.com/agent-workflow",
            "published": "2026-07-19T06:00:00Z",
            "summary": "Original feed summary.",
            "assets": {"preview": {"type": "rewrite", "text": "第三方风格改写，不应使用"}},
            "stats": {"viewCount": 20, "likeCount": 2},
        }]}

        items = parse_qmreader_payload(payload, now=NOW, hours=24)

        self.assertEqual(items[0]["title"], "一种新的 Agent 工作流")
        self.assertEqual(items[0]["summary"], "Original feed summary.")
        self.assertNotIn("第三方风格", str(items[0]))
        self.assertEqual(items[0]["content_type"], "qmreader")

    def test_dedupe_uses_canonical_url_and_prefers_multi_source_story(self):
        items = [
            {
                "id": "direct",
                "title": "Agent update",
                "summary": "One source.",
                "url": "https://example.com/post?utm_source=x#top",
                "content_type": "follow_builders",
                "source_count": 1,
                "score": 80,
            },
            {
                "id": "story",
                "title": "Agent update confirmed",
                "summary": "Three independent sources.",
                "url": "https://example.com/post",
                "content_type": "ai_news_radar",
                "source_count": 3,
                "score": 76,
            },
        ]

        deduped = dedupe_information_items(items)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["id"], "story")
        self.assertEqual(deduped[0]["source_types"], ["ai_news_radar", "follow_builders"])
        self.assertEqual(information_history_key(items[0]), information_history_key(items[1]))

    def test_source_failure_is_isolated(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        def fake_get(url, **_kwargs):
            if "feed-x" in url:
                return Response({
                    "x": [{
                        "name": "Builder",
                        "tweets": [{
                            "id": "1",
                            "text": "AI agent workflow update",
                            "createdAt": "2026-07-19T07:00:00Z",
                            "url": "https://x.com/builder/status/1",
                        }],
                    }],
                })
            if "feed-blogs" in url:
                return Response({"blogs": []})
            raise TimeoutError("qmreader unavailable")

        logs = []
        items = fetch_external_information_items(
            hours=24,
            follow_builders_enabled=True,
            ai_news_radar_enabled=False,
            qmreader_enabled=True,
            get=fake_get,
            now=NOW,
            logger=logs.append,
        )

        self.assertEqual([item["content_type"] for item in items], ["follow_builders"])
        self.assertTrue(any("QMReader 拉取失败" in line for line in logs))

    def test_candidate_limit_applies_to_every_public_source(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        def fake_get(url, **_kwargs):
            if "feed-x" in url:
                return Response({"x": [{
                    "name": "Builder",
                    "tweets": [{
                        "id": str(index),
                        "text": f"AI agent update {index}",
                        "createdAt": "2026-07-19T07:00:00Z",
                        "url": f"https://x.com/builder/status/{index}",
                        "likes": index,
                    } for index in range(5)],
                }]})
            if "feed-blogs" in url:
                return Response({"blogs": []})
            raise AssertionError(f"unexpected URL: {url}")

        items = fetch_external_information_items(
            hours=24,
            candidate_limit=2,
            follow_builders_enabled=True,
            ai_news_radar_enabled=False,
            qmreader_enabled=False,
            get=fake_get,
            now=NOW,
            logger=lambda _message: None,
        )

        self.assertEqual(len(items), 2)
        self.assertEqual([item["engagement"] for item in items], [4, 3])

    def test_malformed_numeric_metadata_does_not_break_source(self):
        payload = {"entries": [{
            "id": "entry-1",
            "sourceId": "feed",
            "title": "Agent update",
            "link": "https://example.com/update",
            "published": "2026-07-19T06:00:00Z",
            "stats": {"viewCount": "unknown", "likeCount": "NaN"},
        }]}

        items = parse_qmreader_payload(payload, now=NOW, hours=24)

        self.assertEqual(items[0]["view_count"], 0)
        self.assertEqual(items[0]["score"], 58)

    def test_canonical_url_keeps_content_query_and_drops_tracking(self):
        canonical = canonicalize_url(
            "HTTPS://Example.COM:443/post/?source=docs&utm_campaign=daily#section"
        )

        self.assertEqual(canonical, "https://example.com/post?source=docs")
        self.assertEqual(canonicalize_url("https://example.com:bad/post"), "https://example.com:bad/post")


if __name__ == "__main__":
    unittest.main()
