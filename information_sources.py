"""Public-feed adapters for AI Flow's non-YouTube information sources."""

from __future__ import annotations

import hashlib
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


FOLLOW_BUILDERS_X_URL = (
    "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-x.json"
)
FOLLOW_BUILDERS_BLOGS_URL = (
    "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-blogs.json"
)
FOLLOW_BUILDERS_PODCASTS_URL = (
    "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-podcasts.json"
)
AI_NEWS_RADAR_URL = (
    "https://raw.githubusercontent.com/LearnPrompt/ai-news-radar/master/data/daily-brief.json"
)
QMREADER_ENTRIES_URL = "https://rss.qiaomu.ai/api/entries"

REQUEST_HEADERS = {
    "User-Agent": "AI-Flow/1.0 (+https://github.com/Suda202/AI-flow)",
    "Accept": "application/json",
}
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
}


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: object, default: float = 0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _parse_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_recent(value: object, *, now: datetime, hours: int) -> bool:
    parsed = _parse_datetime(value)
    if not parsed:
        return False
    now = now.astimezone(timezone.utc)
    return now - timedelta(hours=max(1, hours)) <= parsed <= now + timedelta(minutes=10)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _title_from_text(text: str, limit: int = 96) -> str:
    text = _clean_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def canonicalize_url(raw_url: object) -> str:
    raw = str(raw_url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return raw

    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    try:
        port = parsed.port
    except ValueError:
        return raw
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))


def youtube_video_id_from_url(raw_url: object) -> str:
    """Extract a concrete YouTube video ID for video/podcast cross-source deduplication."""
    raw = str(raw_url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    candidate = ""
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        path_parts = [part for part in parsed.path.split("/") if part]
        if parsed.path.rstrip("/") == "/watch":
            candidate = dict(parse_qsl(parsed.query, keep_blank_values=True)).get("v", "")
        elif len(path_parts) >= 2 and path_parts[0] in {"embed", "live", "shorts"}:
            candidate = path_parts[1]
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,}", candidate or "") else ""


def information_history_key(item: dict) -> str:
    basis = canonicalize_url(item.get("url"))
    if not basis:
        basis = f"{item.get('content_type', '')}:{item.get('id', '')}:{item.get('title', '')}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    return f"info:{digest}"


def parse_follow_builders_payloads(
    x_payload: dict | None,
    blogs_payload: dict | None,
    podcasts_payload: dict | None = None,
    *,
    now: datetime | None = None,
    hours: int = 24,
) -> list[dict]:
    """Normalize Follow Builders X, first-party blogs, and transcript-backed podcasts."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    items: list[dict] = []
    x_payload = x_payload if isinstance(x_payload, dict) else {}
    blogs_payload = blogs_payload if isinstance(blogs_payload, dict) else {}
    podcasts_payload = podcasts_payload if isinstance(podcasts_payload, dict) else {}

    for builder in x_payload.get("x", []):
        if not isinstance(builder, dict):
            continue
        creator = _clean_text(builder.get("name") or builder.get("handle"))
        handle = _clean_text(builder.get("handle"))
        for tweet in builder.get("tweets", []):
            if not isinstance(tweet, dict):
                continue
            text = _clean_text(tweet.get("text"))
            url = _clean_text(tweet.get("url"))
            published = tweet.get("createdAt")
            if not text or not url or not _is_recent(published, now=now, hours=hours):
                continue
            engagement = sum(max(0, _safe_int(tweet.get(key))) for key in ("likes", "retweets", "replies"))
            score = min(92, round(68 + math.log10(engagement + 1) * 8, 1))
            items.append({
                "id": _clean_text(tweet.get("id")) or information_history_key({"url": url}),
                "title": f"{creator}：{_title_from_text(text)}" if creator else _title_from_text(text),
                "summary": text,
                "url": url,
                "source": f"{creator} (@{handle})" if creator and handle else creator or "Follow Builders",
                "creator": creator or handle or "Follow Builders",
                "publishedAt": _iso_z(_parse_datetime(published)),
                "category": "builder-x",
                "content_type": "follow_builders",
                "score": score,
                "engagement": engagement,
            })

    generated_at = blogs_payload.get("generatedAt")
    for blog in blogs_payload.get("blogs", []):
        if not isinstance(blog, dict):
            continue
        title = _clean_text(blog.get("title"))
        url = _clean_text(blog.get("url"))
        published = blog.get("publishedAt") or generated_at
        if not title or not url or not _is_recent(published, now=now, hours=hours):
            continue
        source = _clean_text(blog.get("name")) or "Follow Builders Blog"
        items.append({
            "id": _clean_text(blog.get("id")) or information_history_key({"url": url}),
            "title": title,
            "summary": _clean_text(blog.get("description")),
            "url": url,
            "source": source,
            "creator": _clean_text(blog.get("author")) or source,
            "publishedAt": _iso_z(_parse_datetime(published)),
            "category": "builder-blog",
            "content_type": "follow_builders",
            "score": 74,
        })

    podcast_hours = max(hours, 14 * 24)
    for podcast in podcasts_payload.get("podcasts", []):
        if not isinstance(podcast, dict):
            continue
        title = _clean_text(podcast.get("title"))
        url = _clean_text(podcast.get("url"))
        published = podcast.get("publishedAt") or podcasts_payload.get("generatedAt")
        transcript = str(podcast.get("transcript") or "").strip()
        if (
            not title
            or not url
            or len(transcript) < 100
            or not _is_recent(published, now=now, hours=podcast_hours)
        ):
            continue
        source = _clean_text(podcast.get("name")) or "Follow Builders Podcast"
        items.append({
            "id": _clean_text(podcast.get("guid")) or information_history_key({"url": url}),
            "title": title,
            "summary": _title_from_text(transcript, limit=1800),
            "url": url,
            "source": source,
            "creator": source,
            "publishedAt": _iso_z(_parse_datetime(published)),
            "category": "builder-podcast",
            "content_type": "follow_builders_podcast",
            "score": 84,
            "transcript": transcript,
            "youtube_video_id": youtube_video_id_from_url(url),
        })
    return items


def parse_ai_news_radar_payload(
    payload: dict | None,
    *,
    now: datetime | None = None,
    hours: int = 24,
) -> list[dict]:
    """Normalize AI News Radar's event-level daily brief."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = payload if isinstance(payload, dict) else {}
    generated_at = payload.get("generated_at") or payload.get("generatedAt")
    snapshot_hours = max(48, hours * 2)
    if not _is_recent(generated_at, now=now, hours=snapshot_hours):
        return []

    items: list[dict] = []
    for story in payload.get("items", []):
        if not isinstance(story, dict):
            continue
        title = _clean_text(story.get("title"))
        url = _clean_text(story.get("primary_url") or story.get("url"))
        primary = story.get("primary_item") if isinstance(story.get("primary_item"), dict) else {}
        published = (
            story.get("latest_at")
            or primary.get("published_at")
            or generated_at
        )
        if not title or not url or not _is_recent(published, now=now, hours=hours):
            continue
        raw_score = story.get("score") or story.get("importance") or 0
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0
        if score <= 1:
            score *= 100
        summary = _clean_text(
            story.get("recommend_reason_zh")
            or primary.get("recommend_reason_zh")
            or primary.get("summary")
        )
        source_count = max(1, _safe_int(story.get("source_count"), 1))
        items.append({
            "id": _clean_text(story.get("story_id")) or information_history_key({"url": url}),
            "title": title,
            "summary": summary,
            "url": url,
            "source": "AI News Radar",
            "creator": _clean_text(story.get("source")) or "AI News Radar",
            "publishedAt": _iso_z(_parse_datetime(published)),
            "category": _clean_text(story.get("category")) or "radar-story",
            "content_type": "ai_news_radar",
            "score": round(score, 2),
            "source_count": source_count,
            "source_names": story.get("source_names") or [],
        })
    return items


def parse_qmreader_payload(
    payload: dict | None,
    *,
    now: datetime | None = None,
    hours: int = 24,
) -> list[dict]:
    """Normalize QMReader public entry metadata without consuming style rewrites."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = payload if isinstance(payload, dict) else {}
    items: list[dict] = []
    for entry in payload.get("entries", []):
        if not isinstance(entry, dict):
            continue
        title = _clean_text(entry.get("titleZh") or entry.get("title"))
        url = _clean_text(entry.get("link"))
        published = entry.get("published") or entry.get("publishedTs")
        if not title or not url or not _is_recent(published, now=now, hours=hours):
            continue
        stats = entry.get("stats") if isinstance(entry.get("stats"), dict) else {}
        views = max(0, _safe_int(stats.get("viewCount")))
        likes = max(0, _safe_int(stats.get("likeCount")))
        score = min(82, round(58 + math.log10(views + likes * 4 + 1) * 7, 1))
        source_id = _clean_text(entry.get("sourceId")) or "qmreader"
        items.append({
            "id": _clean_text(entry.get("id")) or information_history_key({"url": url}),
            "title": title,
            "summary": _clean_text(entry.get("summaryZh") or entry.get("summary")),
            "url": url,
            "source": f"QMReader · {source_id}",
            "creator": _clean_text(entry.get("author")) or source_id,
            "publishedAt": _iso_z(_parse_datetime(published)),
            "category": "rss-reading",
            "content_type": "qmreader",
            "score": score,
            "source_id": source_id,
            "view_count": views,
        })
    return items


def _dedupe_priority(item: dict) -> tuple[float, float, int, int]:
    source_count = _safe_float(item.get("source_count"), 1)
    score = _safe_float(item.get("score"))
    summary_length = len(_clean_text(item.get("summary")))
    source_priority = {
        "follow_builders_podcast": 5,
        "ai_news_radar": 4,
        "aihot": 3,
        "follow_builders": 2,
        "qmreader": 1,
    }.get(str(item.get("content_type") or ""), 0)
    return source_count, score, summary_length, source_priority


def dedupe_information_items(items: list[dict]) -> list[dict]:
    """Deduplicate cross-source items by canonical URL, preserving evidence provenance."""
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = canonicalize_url(item.get("url"))
        if not key:
            continue
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(item)

    deduped = []
    for key in order:
        group = grouped[key]
        selected = max(group, key=_dedupe_priority)
        source_types = sorted({
            str(item.get("content_type") or "")
            for item in group
            if item.get("content_type")
        })
        deduped.append({
            **selected,
            "canonical_url": key,
            "source_types": source_types,
        })
    return deduped


def _get_json(
    url: str,
    *,
    get: Callable = requests.get,
    timeout: int = 15,
    params: dict | None = None,
) -> dict:
    response = get(url, headers=REQUEST_HEADERS, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("JSON payload is not an object")
    return payload


def fetch_follow_builders_items(
    *,
    hours: int = 24,
    get: Callable = requests.get,
    now: datetime | None = None,
    x_url: str = FOLLOW_BUILDERS_X_URL,
    blogs_url: str = FOLLOW_BUILDERS_BLOGS_URL,
    podcasts_url: str = FOLLOW_BUILDERS_PODCASTS_URL,
) -> list[dict]:
    x_payload: dict = {}
    blogs_payload: dict = {}
    podcasts_payload: dict = {}
    errors = []
    try:
        x_payload = _get_json(x_url, get=get)
    except Exception as error:  # partial source failure must not hide blogs
        errors.append(f"X: {error}")
    try:
        blogs_payload = _get_json(blogs_url, get=get)
    except Exception as error:
        errors.append(f"blogs: {error}")
    try:
        podcasts_payload = _get_json(podcasts_url, get=get)
    except Exception as error:
        errors.append(f"podcasts: {error}")
    if errors and not x_payload and not blogs_payload and not podcasts_payload:
        raise RuntimeError("; ".join(errors))
    return parse_follow_builders_payloads(
        x_payload,
        blogs_payload,
        podcasts_payload,
        now=now,
        hours=hours,
    )


def fetch_ai_news_radar_items(
    *,
    hours: int = 24,
    get: Callable = requests.get,
    now: datetime | None = None,
    url: str = AI_NEWS_RADAR_URL,
) -> list[dict]:
    return parse_ai_news_radar_payload(_get_json(url, get=get), now=now, hours=hours)


def fetch_qmreader_items(
    *,
    hours: int = 24,
    candidate_limit: int = 40,
    get: Callable = requests.get,
    now: datetime | None = None,
    url: str = QMREADER_ENTRIES_URL,
) -> list[dict]:
    payload = _get_json(
        url,
        get=get,
        params={"limit": max(1, min(100, candidate_limit))},
    )
    return parse_qmreader_payload(payload, now=now, hours=hours)


def fetch_external_information_items(
    *,
    hours: int = 24,
    candidate_limit: int = 40,
    follow_builders_enabled: bool = True,
    ai_news_radar_enabled: bool = True,
    qmreader_enabled: bool = True,
    get: Callable = requests.get,
    now: datetime | None = None,
    logger: Callable[[str], None] = print,
) -> list[dict]:
    """Fetch enabled public sources concurrently; every source fails independently."""
    candidate_limit = max(1, min(100, candidate_limit))
    tasks: list[tuple[str, Callable[[], list[dict]]]] = []
    if follow_builders_enabled:
        tasks.append(("Follow Builders", lambda: fetch_follow_builders_items(hours=hours, get=get, now=now)))
    if ai_news_radar_enabled:
        tasks.append(("AI News Radar", lambda: fetch_ai_news_radar_items(hours=hours, get=get, now=now)))
    if qmreader_enabled:
        tasks.append(("QMReader", lambda: fetch_qmreader_items(
            hours=hours,
            candidate_limit=candidate_limit,
            get=get,
            now=now,
        )))

    items: list[dict] = []
    if not tasks:
        return items
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        future_to_name = {executor.submit(task): name for name, task in tasks}
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                source_items = future.result()
                source_items = sorted(
                    source_items,
                    key=lambda item: (
                        _safe_float(item.get("score")),
                        _parse_datetime(item.get("publishedAt")) or datetime.min.replace(tzinfo=timezone.utc),
                    ),
                    reverse=True,
                )[:candidate_limit]
                items.extend(source_items)
                logger(f"  ✅ {name}: {len(source_items)} 条候选")
            except Exception as error:
                logger(f"  ⚠️ {name} 拉取失败: {error}")
    return dedupe_information_items(items)
