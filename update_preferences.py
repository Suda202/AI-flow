"""Turn raw one-click feedback into incremental recommendation preferences."""

from __future__ import annotations

import argparse
import json
import os
import re
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from preference_learning import (
    FACET_GROUPS,
    apply_daily_feedback,
    build_ranking_hints,
    consolidate_weekly,
    default_state,
    normalize_feedback_events,
    normalize_state,
    should_run_weekly,
    utc_iso,
)


FEEDBACK_FILE = os.environ.get("FEEDBACK_FILE", "feedback.json")
PROFILE_FILE = os.environ.get("PROFILE_FILE", "profile.json")
PREFERENCE_STATE_FILE = os.environ.get("PREFERENCE_STATE_FILE", "preference_state.json")
RANKING_HINTS_FILE = os.environ.get("RANKING_HINTS_FILE", "ranking_hints.txt")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_BASE = (os.environ.get("DEEPSEEK_API_BASE") or "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash"

MAX_FACETS_PER_GROUP = 4
VALUE_TAGS = {"前沿趋势", "实用方法", "方法论", "商业价值", "深度洞察", "硅谷热点"}
FORMAT_TAGS = {"实战教程", "入门教程", "深度分析", "案例拆解", "产品发布", "观点访谈"}


def load_json(path: str | Path, default: dict | None = None) -> dict:
    path = Path(path)
    if not path.exists():
        return default.copy() if isinstance(default, dict) else {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default.copy() if isinstance(default, dict) else {}
    return data if isinstance(data, dict) else (default.copy() if isinstance(default, dict) else {})


def save_json(path: str | Path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _clean_labels(value) -> list[str]:
    if not isinstance(value, list):
        return []
    labels = []
    for item in value:
        label = str(item).strip()
        if label and label not in labels:
            labels.append(label)
    return labels[:MAX_FACETS_PER_GROUP]


def parse_classification_response(raw: str | None, expected_event_ids: set[str]) -> dict[str, dict]:
    """Parse a model response into validated facets keyed by feedback event id."""
    if not raw:
        return {}
    text = str(raw).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}

    rows = payload.get("events", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {}

    parsed = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or "")
        if event_id not in expected_event_ids:
            continue
        facets = {group: _clean_labels(row.get(group)) for group in FACET_GROUPS}
        if any(facets.values()):
            parsed[event_id] = facets
    return parsed


def deterministic_classify_event(event: dict) -> dict[str, list[str]]:
    """Conservative fallback used when the model is unavailable or returns invalid JSON."""
    title = str(event.get("title") or "")
    content_type = str(event.get("content_type") or "")
    creator = str(event.get("creator") or "")
    category = str(event.get("category") or "")
    tags = [str(tag).strip() for tag in event.get("selection_tags", []) if str(tag).strip()]
    text = " ".join([title, creator, category, *tags]).lower()

    topics = []
    formats = []
    values = []

    if content_type == "follow_builders_podcast" or category == "builder-podcast":
        formats.append("播客访谈")
        values.append("一手观点")
    elif content_type == "follow_builders" and category == "builder-blog":
        formats.append("官方博客")
        values.append("一手信息")
    elif content_type == "follow_builders":
        formats.append("Builder 短观点")
    elif content_type == "ai_news_radar":
        formats.append("多源事件")
        values.append("多源确认")
    elif content_type == "qmreader":
        formats.append("文章")

    for tag in tags:
        if tag in VALUE_TAGS:
            values.append(tag)
        elif tag in FORMAT_TAGS:
            formats.append(tag)
        else:
            topics.append(tag)

    agent_terms = (
        "agent", "agentic", "coding agent", "deep agents", "harness",
        "智能体", "代理工程", "上下文工程",
    )
    if any(term in text for term in agent_terms):
        topics.append("Agent")
    if "loop engineering" in text or "循环工程" in text:
        topics.append("Loop Engineering")
    if any(term in text for term in ("agentic engineering", "coding agent", "harness", "代理工程")):
        topics.append("Agentic Engineering")
    if "deep agents" in text:
        topics.append("Deep Agents")

    tutorial_terms = ("tutorial", "guide", "how to", "hands-on", "实战", "教程", "指南")
    generic_terms = ("getting started", "beginner", "install", "setup", "api 入门", "快速上手")
    if any(term in text for term in tutorial_terms):
        formats.append("入门教程" if any(term in text for term in generic_terms) else "实战教程")
    if any(term in text for term in ("deep dive", "analysis", "拆解", "深度", "复盘")):
        formats.append("深度分析")

    if any(term in text for term in ("silicon valley", "硅谷", "a16z", "sequoia", "前沿", "趋势", "hot")):
        values.extend(["前沿趋势", "硅谷热点"])
    if any(term in text for term in ("practical", "hands-on", "实战", "方法", "workflow", "工程")):
        values.append("实用方法")
    if any(term in text for term in ("business", "revenue", "pricing", "商业", "营收", "定价")):
        values.append("商业价值")

    return {
        "topics": _clean_labels(topics),
        "formats": _clean_labels(formats),
        "values": _clean_labels(values),
        "sources": _clean_labels([creator] if creator else []),
    }


def _classification_prompt(events: list[dict]) -> str:
    compact_events = [{
        key: event.get(key)
        for key in (
            "event_id", "content_type", "title", "creator", "category",
            "selection_tags", "reaction",
        )
    } for event in events]
    return f"""你在为一个个人 AI 信息流分析一键反馈。请只识别内容本身的属性，不要把 dislike 解释成相反偏好。

为每条事件提取四组简洁中文标签，每组最多 4 个：
- topics：内容主题，例如 Agent、Loop Engineering、AI 产品、商业化
- formats：内容形态，例如播客访谈、官方博客、Builder 短观点、多源事件、文章、实战教程、深度分析
- values：用户可能获得的价值，例如一手观点、多源确认、前沿趋势、实用方法、商业价值、深度洞察
- sources：作者、机构或媒体名称

只返回 JSON，不要解释：
{{"events":[{{"event_id":"...","topics":[],"formats":[],"values":[],"sources":[]}}]}}

事件：
{json.dumps(compact_events, ensure_ascii=False)}
"""


def call_llm(prompt: str) -> str | None:
    if not DEEPSEEK_API_KEY:
        return None
    try:
        response = requests.post(
            f"{DEEPSEEK_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        data = response.json()
        if data.get("error") or response.status_code >= 400:
            return None
        choices = data.get("choices", [])
        if not choices:
            return None
        content = choices[0].get("message", {}).get("content")
        return content.strip() if isinstance(content, str) else None
    except Exception as error:
        print(f"  ⚠️ DeepSeek 偏好分类失败，使用本地兜底: {error}")
        return None


def classify_events(
    events: list[dict],
    model_call: Callable[[str], str | None] | None = None,
) -> list[dict]:
    if not events:
        return []
    model_call = model_call or call_llm
    expected_ids = {str(event.get("event_id") or "") for event in events}
    try:
        raw = model_call(_classification_prompt(events))
    except Exception as error:
        print(f"  ⚠️ 偏好分类调用异常，使用本地兜底: {error}")
        raw = None
    model_facets = parse_classification_response(raw, expected_ids)

    classified = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        facets = model_facets.get(event_id) or deterministic_classify_event(event)
        classified.append({**event, **facets})
    return classified


def _compact_facets(container: dict) -> dict:
    compact = {}
    for group in FACET_GROUPS:
        records = container.get(group) if isinstance(container.get(group), dict) else {}
        if not records:
            continue
        compact[group] = {
            label: {
                "net": record.get("net", 0),
                "evidence_count": record.get("evidence_count", 0),
            }
            for label, record in records.items()
            if isinstance(record, dict)
        }
    return compact


def sync_profile(profile: dict, state: dict, now: datetime) -> dict:
    profile = dict(profile) if isinstance(profile, dict) else {}
    profile["inferred_preferences"] = {
        "schema_version": 2,
        "last_updated": utc_iso(now),
        "recent": _compact_facets(state.get("short_term", {})),
        "stable": _compact_facets(state.get("long_term", {})),
    }
    return profile


def run_preference_update(
    *,
    feedback_path: str | Path = FEEDBACK_FILE,
    profile_path: str | Path = PROFILE_FILE,
    state_path: str | Path = PREFERENCE_STATE_FILE,
    hints_path: str | Path = RANKING_HINTS_FILE,
    now: datetime | None = None,
    model_call: Callable[[str], str | None] | None = None,
) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    feedback = load_json(feedback_path)
    profile = load_json(profile_path)
    state = normalize_state(load_json(state_path, default_state()))

    all_events = normalize_feedback_events(feedback)
    new_events = [
        event for event in all_events
        if event["event_id"] not in state["processed_events"]
    ]
    state = apply_daily_feedback(state, classify_events(new_events, model_call), now)

    weekly_ran = False
    if not state.get("last_weekly_run"):
        state["last_weekly_run"] = utc_iso(now)
    elif should_run_weekly(state, now):
        state = consolidate_weekly(state, now)
        weekly_ran = True

    hints = build_ranking_hints(state)
    profile = sync_profile(profile, state, now)
    save_json(state_path, state)
    save_json(profile_path, profile)
    Path(hints_path).write_text(hints + ("\n" if hints else ""))
    return {
        "feedback_count": len(all_events),
        "new_event_count": len(new_events),
        "weekly_ran": weekly_ran,
        "ranking_hints": hints,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="保留兼容参数")
    parser.parse_args()

    result = run_preference_update()
    print(
        f"📊 共读取 {result['feedback_count']} 次反馈，"
        f"本次处理 {result['new_event_count']} 次新反馈"
    )
    if result["weekly_ran"]:
        print("🧭 已完成本周偏好归纳")
    print(result["ranking_hints"] or "暂无足够强的动态偏好信号")


if __name__ == "__main__":
    main()
