"""Pure preference-learning state transitions for daily recommendation feedback."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone


UTC = timezone.utc
FACET_GROUPS = ("topics", "formats", "values", "sources")
REACTION_WEIGHT = {"like": 1.0, "dislike": -1.0}
DAILY_DECAY = 0.9
WEEKLY_DECAY = 0.95
STABLE_MIN_NET = 2.0
STABLE_MIN_DISTINCT_CONTENT = 2
MAX_REACTIONS_PER_CONTENT = 3
MAX_WEEKLY_SNAPSHOTS = 8
PROCESSED_EVENT_RETENTION_DAYS = 90


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def default_state() -> dict:
    return {
        "schema_version": 1,
        "processed_events": {},
        "short_term": {},
        "long_term": {},
        "last_daily_run": None,
        "last_weekly_run": None,
        "weekly_snapshots": [],
    }


def normalize_state(state: dict | None) -> dict:
    normalized = default_state()
    if isinstance(state, dict):
        for key in normalized:
            if key in state:
                normalized[key] = copy.deepcopy(state[key])
    if not isinstance(normalized["processed_events"], dict):
        normalized["processed_events"] = {}
    if not isinstance(normalized["short_term"], dict):
        normalized["short_term"] = {}
    if not isinstance(normalized["long_term"], dict):
        normalized["long_term"] = {}
    if not isinstance(normalized["weekly_snapshots"], list):
        normalized["weekly_snapshots"] = []
    return normalized


def stable_event_id(content_id: str, reaction: str, timestamp: str) -> str:
    raw = json.dumps([content_id, reaction, timestamp], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_feedback_events(feedback: dict) -> list[dict]:
    events = []
    if not isinstance(feedback, dict):
        return events

    for key, entry in feedback.items():
        if not isinstance(entry, dict):
            continue
        legacy = entry.get("video_meta") if isinstance(entry.get("video_meta"), dict) else {}
        meta = entry.get("content_meta") if isinstance(entry.get("content_meta"), dict) else {}
        content_id = str(meta.get("content_id") or key)
        content_type = str(
            meta.get("content_type")
            or ("aihot" if content_id.startswith("aihot:") else "youtube")
        )
        title = str(meta.get("title") or legacy.get("title") or "")
        creator = str(meta.get("creator") or legacy.get("author") or "")
        url = str(meta.get("url") or legacy.get("url") or "")
        category = str(meta.get("category") or "")
        selection_tags = [
            str(tag).strip()
            for tag in (meta.get("selection_tags") or [])
            if str(tag).strip()
        ][:5]

        reactions = entry.get("reactions") if isinstance(entry.get("reactions"), list) else []
        for reaction_data in reactions[-MAX_REACTIONS_PER_CONTENT:]:
            if not isinstance(reaction_data, dict):
                continue
            reaction = str(reaction_data.get("reaction") or "")
            timestamp = str(reaction_data.get("timestamp") or "")
            if reaction not in REACTION_WEIGHT or not parse_iso(timestamp):
                continue
            event_id = str(
                reaction_data.get("event_id")
                or stable_event_id(content_id, reaction, timestamp)
            )
            events.append({
                "event_id": event_id,
                "content_id": content_id,
                "content_type": content_type,
                "title": title,
                "creator": creator,
                "url": url,
                "category": category,
                "selection_tags": selection_tags,
                "reaction": reaction,
                "timestamp": timestamp,
            })

    return sorted(events, key=lambda event: (event["timestamp"], event["event_id"]))


def _ensure_facet_group(container: dict, group: str) -> dict:
    value = container.get(group)
    if not isinstance(value, dict):
        value = {}
        container[group] = value
    return value


def _decay_facets(container: dict, factor: float) -> None:
    for group in FACET_GROUPS:
        facets = _ensure_facet_group(container, group)
        for label in list(facets):
            record = facets[label]
            if not isinstance(record, dict):
                del facets[label]
                continue
            record["net"] = round(float(record.get("net", 0)) * factor, 6)
            if abs(record["net"]) < 0.01:
                del facets[label]


def _elapsed_days(last_run: str | None, now: datetime) -> int:
    parsed = parse_iso(last_run)
    if not parsed:
        return 0
    return max(0, (now.astimezone(UTC).date() - parsed.date()).days)


def _apply_facet(
    container: dict,
    group: str,
    label: str,
    weight: float,
    content_id: str,
    timestamp: str,
) -> None:
    clean_label = str(label).strip()
    if not clean_label:
        return
    facets = _ensure_facet_group(container, group)
    record = facets.setdefault(clean_label, {
        "net": 0.0,
        "evidence_count": 0,
        "content_ids": [],
        "last_seen": timestamp,
    })
    record["net"] = round(float(record.get("net", 0)) + weight, 6)
    record["evidence_count"] = int(record.get("evidence_count", 0)) + 1
    content_ids = [str(value) for value in record.get("content_ids", [])]
    if content_id not in content_ids:
        content_ids.append(content_id)
    record["content_ids"] = content_ids[-50:]
    record["last_seen"] = timestamp


def _prune_processed_events(state: dict, now: datetime) -> None:
    cutoff = now.astimezone(UTC) - timedelta(days=PROCESSED_EVENT_RETENTION_DAYS)
    kept = {}
    for event_id, timestamp in state["processed_events"].items():
        parsed = parse_iso(timestamp)
        if not parsed or parsed >= cutoff:
            kept[str(event_id)] = timestamp
    state["processed_events"] = kept


def apply_daily_feedback(state: dict, classified_events: list[dict], now: datetime) -> dict:
    result = normalize_state(state)
    now = now.astimezone(UTC)
    days = _elapsed_days(result.get("last_daily_run"), now)
    if days:
        _decay_facets(result["short_term"], DAILY_DECAY ** days)

    for event in classified_events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id") or "")
        reaction = str(event.get("reaction") or "")
        content_id = str(event.get("content_id") or "")
        timestamp = str(event.get("timestamp") or utc_iso(now))
        if not event_id or event_id in result["processed_events"]:
            continue
        if reaction not in REACTION_WEIGHT or not content_id:
            continue

        has_facets = False
        for group in FACET_GROUPS:
            labels = event.get(group)
            if not isinstance(labels, list):
                continue
            for label in dict.fromkeys(str(value).strip() for value in labels if str(value).strip()):
                _apply_facet(
                    result["short_term"],
                    group,
                    label,
                    REACTION_WEIGHT[reaction],
                    content_id,
                    timestamp,
                )
                has_facets = True
        if has_facets:
            result["processed_events"][event_id] = timestamp

    result["last_daily_run"] = utc_iso(now)
    _prune_processed_events(result, now)
    return result


def should_run_weekly(state: dict, now: datetime) -> bool:
    normalized = normalize_state(state)
    last_run = parse_iso(normalized.get("last_weekly_run"))
    if not last_run:
        return True
    return now.astimezone(UTC) - last_run >= timedelta(days=7)


def consolidate_weekly(state: dict, now: datetime) -> dict:
    result = normalize_state(state)
    now = now.astimezone(UTC)
    _decay_facets(result["long_term"], WEEKLY_DECAY)

    for group in FACET_GROUPS:
        short_facets = _ensure_facet_group(result["short_term"], group)
        for label, record in short_facets.items():
            if not isinstance(record, dict):
                continue
            net = float(record.get("net", 0))
            content_ids = list(dict.fromkeys(str(value) for value in record.get("content_ids", [])))
            if abs(net) < STABLE_MIN_NET or len(content_ids) < STABLE_MIN_DISTINCT_CONTENT:
                continue
            long_facets = _ensure_facet_group(result["long_term"], group)
            target = long_facets.setdefault(label, {
                "net": 0.0,
                "evidence_count": 0,
                "content_ids": [],
                "last_seen": record.get("last_seen") or utc_iso(now),
            })
            target["net"] = round(float(target.get("net", 0)) + net, 6)
            target["evidence_count"] = int(target.get("evidence_count", 0)) + int(
                record.get("evidence_count", len(content_ids))
            )
            target["content_ids"] = list(dict.fromkeys(
                [str(value) for value in target.get("content_ids", [])] + content_ids
            ))[-100:]
            target["last_seen"] = record.get("last_seen") or utc_iso(now)

    snapshot = {
        "created_at": utc_iso(now),
        "long_term": copy.deepcopy(result["long_term"]),
    }
    result["weekly_snapshots"] = (result["weekly_snapshots"] + [snapshot])[-MAX_WEEKLY_SNAPSHOTS:]
    result["short_term"] = {}
    result["last_weekly_run"] = utc_iso(now)
    return result


def _labels_with_sign(container: dict, positive: bool) -> list[tuple[str, float]]:
    labels = []
    for group in ("topics", "formats", "values"):
        facets = container.get(group) if isinstance(container.get(group), dict) else {}
        for label, record in facets.items():
            if not isinstance(record, dict):
                continue
            net = float(record.get("net", 0))
            if (positive and net > 0) or (not positive and net < 0):
                labels.append((str(label), net))
    return sorted(labels, key=lambda item: abs(item[1]), reverse=True)


def _format_hint(prefix: str, labels: list[tuple[str, float]]) -> str | None:
    if not labels:
        return None
    unique = list(dict.fromkeys(label for label, _ in labels))[:8]
    return f"{prefix}：{'、'.join(unique)}"


def build_ranking_hints(state: dict) -> str:
    normalized = normalize_state(state)
    lines = ["基于近期一键反馈，额外调整："]
    candidates = [
        _format_hint("近期偏好", _labels_with_sign(normalized["short_term"], True)),
        _format_hint("近期回避", _labels_with_sign(normalized["short_term"], False)),
        _format_hint("稳定偏好", _labels_with_sign(normalized["long_term"], True)),
        _format_hint("稳定回避", _labels_with_sign(normalized["long_term"], False)),
    ]
    lines.extend(line for line in candidates if line)
    return "\n".join(lines) if len(lines) > 1 else ""
