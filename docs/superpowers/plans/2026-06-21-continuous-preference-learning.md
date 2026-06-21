# Continuous Preference Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-click AI HOT feedback and a daily/weekly, incremental preference-learning loop that improves both AI HOT and YouTube recommendations without overfitting a single click.

**Architecture:** Reuse the existing Feishu callback Worker and GitHub `data` branch. Store raw feedback in the existing `feedback.json`, keep idempotent learning state in a new `preference_state.json`, update short-term weights daily and stable weights every seven days, then feed generated `ranking_hints.txt` into both selectors. Keep AI HOT selection quality-gated with dedicated Agent, frontier-trend, and business-value lanes.

**Tech Stack:** Python 3.12, `unittest`, DeepSeek OpenAI-compatible API, Feishu interactive cards, Cloudflare Worker JavaScript, GitHub Actions, JSON files on the `data` branch.

## Global Constraints

- Feedback interaction is binary only: 👍 or 👎, with no reason picker and no free text.
- A single click is a weak short-term signal and must not directly become a long-term preference.
- Stable preference requires at least two distinct content items and an absolute net signal of at least two.
- Agent-related practical tutorials are eligible; generic install/API/code-along tutorials are not.
- AI HOT keeps Agent, Silicon Valley frontier-trend, and business-value lanes; maximum seven items and zero is allowed.
- The automation must never edit `~/.agent/USER.md`.
- Preserve existing uncommitted changes in `worker/src/index.js` and `worker/src/vercel-handler.js`; stage only task-specific hunks.
- Do not add a database, vector store, or new service.

---

## File Map

- Create `preference_learning.py`: pure normalization, idempotence, decay, daily update, weekly consolidation, and ranking-hint functions.
- Create `tests/test_preference_learning.py`: deterministic regression coverage for incremental and weekly learning.
- Modify `update_preferences.py`: file I/O and DeepSeek classification CLI around `preference_learning.py`.
- Modify `main.py`: AI HOT quality selector, preference hints, feedback buttons, and channel-specific card building.
- Modify `tests/test_aihot_integration.py`: Agent/trend quality fixtures and AI HOT feedback-card tests.
- Modify `worker/src/index.js`: accept generic content metadata and persist event IDs in Cloudflare Worker.
- Modify `worker/src/vercel-handler.js`: keep Vercel callback behavior in parity.
- Modify `.github/workflows/digest.yml`: restore/save `preference_state.json` and expose DeepSeek to preference analysis.
- Modify `README.md`: document feedback learning and new runtime data file.

---

### Task 1: Pure Incremental Preference State

**Files:**
- Create: `preference_learning.py`
- Create: `tests/test_preference_learning.py`

**Interfaces:**
- Produces: `normalize_feedback_events(feedback: dict) -> list[dict]`
- Produces: `apply_daily_feedback(state: dict, classified_events: list[dict], now: datetime) -> dict`
- Produces: `should_run_weekly(state: dict, now: datetime) -> bool`
- Produces: `consolidate_weekly(state: dict, now: datetime) -> dict`
- Produces: `build_ranking_hints(state: dict) -> str`

- [ ] **Step 1: Write failing event-normalization tests**

```python
def test_normalizes_legacy_and_generic_feedback_without_duplicate_events():
    feedback = {
        "video-1": {
            "video_meta": {"title": "Agent workflow", "author": "AI Engineer"},
            "reactions": [{"reaction": "like", "timestamp": "2026-06-20T01:00:00Z"}],
        },
        "aihot:item-1": {
            "content_meta": {
                "content_id": "aihot:item-1",
                "content_type": "aihot",
                "title": "Loop Engineering",
                "creator": "Addy Osmani",
                "selection_tags": ["Loop Engineering", "前沿趋势"],
            },
            "reactions": [{"event_id": "evt-1", "reaction": "like", "timestamp": "2026-06-20T02:00:00Z"}],
        },
    }
    events = normalize_feedback_events(feedback)
    assert [event["content_type"] for event in events] == ["youtube", "aihot"]
    assert len({event["event_id"] for event in events}) == 2
```

- [ ] **Step 2: Run the normalization test and verify RED**

Run: `python3 -m unittest tests.test_preference_learning.PreferenceLearningTests.test_normalizes_legacy_and_generic_feedback_without_duplicate_events -v`

Expected: import or missing-function failure.

- [ ] **Step 3: Implement normalized events and default state**

```python
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

def stable_event_id(content_id: str, reaction: str, timestamp: str) -> str:
    raw = json.dumps([content_id, reaction, timestamp], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def normalize_feedback_events(feedback: dict) -> list[dict]:
    events = []
    for key, entry in feedback.items():
        legacy = entry.get("video_meta") or {}
        meta = entry.get("content_meta") or {
            "content_id": key,
            "content_type": "aihot" if str(key).startswith("aihot:") else "youtube",
            "title": legacy.get("title", ""),
            "creator": legacy.get("author", ""),
            "url": legacy.get("url", ""),
            "category": "",
            "selection_tags": [],
        }
        content_id = str(meta.get("content_id") or key)
        for reaction in (entry.get("reactions") or [])[-3:]:
            timestamp = str(reaction.get("timestamp") or "")
            action = str(reaction.get("reaction") or "")
            if action not in {"like", "dislike"} or not timestamp:
                continue
            events.append({
                "event_id": reaction.get("event_id") or stable_event_id(content_id, action, timestamp),
                "content_id": content_id,
                "content_type": meta.get("content_type") or "youtube",
                "title": meta.get("title") or "",
                "creator": meta.get("creator") or "",
                "url": meta.get("url") or "",
                "category": meta.get("category") or "",
                "selection_tags": list(meta.get("selection_tags") or [])[:5],
                "reaction": action,
                "timestamp": timestamp,
            })
    return sorted(events, key=lambda event: (event["timestamp"], event["event_id"]))
```

- [ ] **Step 4: Add failing daily idempotence and weak-signal tests**

```python
def test_daily_feedback_is_idempotent_and_one_click_stays_short_term():
    now = datetime(2026, 6, 21, tzinfo=timezone.utc)
    event = {
        "event_id": "evt-1",
        "content_id": "aihot:1",
        "reaction": "like",
        "timestamp": "2026-06-21T01:00:00Z",
        "topics": ["Loop Engineering"],
        "formats": ["实战教程"],
        "values": ["前沿趋势", "实用方法"],
        "sources": ["Addy Osmani"],
    }
    first = apply_daily_feedback(default_state(), [event], now)
    second = apply_daily_feedback(first, [event], now)
    assert second == first
    assert first["short_term"]["topics"]["Loop Engineering"]["net"] == 1
    assert "Loop Engineering" not in first["long_term"].get("topics", {})
```

- [ ] **Step 5: Run daily tests and verify RED**

Run: `python3 -m unittest tests.test_preference_learning.PreferenceLearningTests.test_daily_feedback_is_idempotent_and_one_click_stays_short_term -v`

Expected: missing `apply_daily_feedback` failure.

- [ ] **Step 6: Implement daily update and 0.9/day decay**

Implementation requirements:

```python
REACTION_WEIGHT = {"like": 1.0, "dislike": -1.0}
DAILY_DECAY = 0.9
MAX_REACTIONS_PER_CONTENT = 3
```

Each facet record must contain `net`, `evidence_count`, `content_ids`, and `last_seen`. Mark an event processed only after its classified facets were applied.

- [ ] **Step 7: Add failing weekly consolidation tests**

```python
def test_weekly_consolidation_requires_two_distinct_items_and_net_two():
    state = default_state()
    state["short_term"] = {
        "topics": {
            "Loop Engineering": {
                "net": 2.0,
                "evidence_count": 2,
                "content_ids": ["aihot:1", "aihot:2"],
                "last_seen": "2026-06-27T01:00:00Z",
            }
        }
    }
    result = consolidate_weekly(state, datetime(2026, 6, 28, tzinfo=timezone.utc))
    assert result["long_term"]["topics"]["Loop Engineering"]["net"] > 0

def test_disliking_tutorial_format_does_not_reduce_agent_parent_topic():
    state = default_state()
    state["short_term"] = {
        "topics": {
            "Agent": {
                "net": 1.0,
                "evidence_count": 1,
                "content_ids": ["1"],
                "last_seen": "2026-06-27T01:00:00Z",
            }
        },
        "formats": {
            "入门教程": {
                "net": -2.0,
                "evidence_count": 2,
                "content_ids": ["1", "2"],
                "last_seen": "2026-06-27T01:00:00Z",
            }
        },
    }
    result = consolidate_weekly(state, datetime(2026, 6, 28, tzinfo=timezone.utc))
    assert result["long_term"]["formats"]["入门教程"]["net"] < 0
    assert result["long_term"].get("topics", {}).get("Agent", {}).get("net", 0) >= 0
```

- [ ] **Step 8: Implement weekly threshold, 0.95 decay, and eight snapshots**

Use exact constants:

```python
WEEKLY_DECAY = 0.95
STABLE_MIN_NET = 2.0
STABLE_MIN_DISTINCT_CONTENT = 2
MAX_WEEKLY_SNAPSHOTS = 8
```

- [ ] **Step 9: Implement and test ranking hints**

Hints must distinguish short-term and stable signals, for example:

```text
近期偏好：Loop Engineering、Agent 实战教程
稳定偏好：Agentic Engineering、GEO
近期回避：节日营销、普通 API 教程
```

Run: `python3 -m unittest tests.test_preference_learning -v`

Expected: all preference-learning tests pass.

- [ ] **Step 10: Commit Task 1**

```bash
git add preference_learning.py tests/test_preference_learning.py
git commit -m "feat: add incremental preference state"
```

---

### Task 2: DeepSeek Classification and CLI Orchestration

**Files:**
- Modify: `update_preferences.py`
- Test: `tests/test_preference_learning.py`

**Interfaces:**
- Consumes: normalized events and pure state functions from Task 1.
- Produces: `classify_events(events: list[dict]) -> list[dict]`
- Produces: CLI that updates `profile.json`, `preference_state.json`, and `ranking_hints.txt`.

- [ ] **Step 1: Write failing classifier parsing and retry tests**

```python
def test_classifier_maps_binary_feedback_to_granular_facets():
    result = parse_classification_response(
        '[{"event_id":"evt-1","topics":["Loop Engineering","Agent"],'
        '"formats":["实战教程"],"values":["前沿趋势","实用方法"]}]',
        expected_event_ids={"evt-1"},
    )
    assert result[0]["topics"] == ["Loop Engineering", "Agent"]

def test_invalid_llm_output_keeps_event_unprocessed():
    assert parse_classification_response("not json", {"evt-1"}) == []
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_preference_learning -v`

Expected: missing parser/classifier failure.

- [ ] **Step 3: Implement one batched DeepSeek call with deterministic fallback**

The prompt must:

- Classify topics, formats, values, and source traits.
- Allow new topic labels such as Loop Engineering.
- Keep Agent practical tutorials separate from generic beginner/API tutorials.
- Return a JSON array only.

If DeepSeek is missing or invalid, call the existing deterministic `infer_topics` mapping and add format/value keyword rules. Events with no reliable facets remain unprocessed.

- [ ] **Step 4: Replace repeated full-history accumulation**

The CLI flow must be:

```python
feedback = load_json(FEEDBACK_FILE)
state = load_json(PREFERENCE_STATE_FILE) or default_state()
events = normalize_feedback_events(feedback)
new_events = [e for e in events if e["event_id"] not in state["processed_events"]]
classified = classify_events(new_events)
state = apply_daily_feedback(state, classified, now)
if should_run_weekly(state, now):
    state = consolidate_weekly(state, now)
ranking_hints = build_ranking_hints(state)
```

Do not append the same historical feedback to `profile.inferred_preferences.history` on every run. Keep compatibility fields synchronized from stable state only.

- [ ] **Step 5: Run full Python tests**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add update_preferences.py tests/test_preference_learning.py
git commit -m "feat: analyze feedback incrementally"
```

---

### Task 3: Generic Worker Feedback Metadata

**Files:**
- Modify: `worker/src/index.js`
- Modify: `worker/src/vercel-handler.js`

**Interfaces:**
- Consumes: old `video_id` or new `content_id` action values.
- Produces: `content_meta` plus reaction `event_id` in `feedback.json`.

- [ ] **Step 1: Add generic action extraction in both Worker implementations**

Use this compatibility shape:

```javascript
const contentId = value.content_id || value.contentId || value.video_id || value.videoId;
const contentType = value.content_type || value.contentType ||
  (String(contentId).startsWith("aihot:") ? "aihot" : "youtube");

return {
  videoId: contentId,
  contentId,
  contentType,
  reaction,
  reason: null,
  cardState: value.card_state || value.cardState || null,
  feedbackState: value.feedback_state || value.feedbackState || {},
  contentMeta: {
    content_id: contentId,
    content_type: contentType,
    title: value.title || "",
    creator: value.creator || value.author || "",
    url: value.url || "",
    category: value.category || "",
    selection_tags: Array.isArray(value.selection_tags) ? value.selection_tags.slice(0, 5) : [],
  },
  videoMeta: {
    title: value.title || "",
    author: value.author || value.creator || "",
    url: value.url || "",
  },
};
```

- [ ] **Step 2: Add event IDs and content metadata on persistence**

Each appended reaction must include:

```javascript
{
  event_id: globalThis.crypto.randomUUID(),
  reaction: feedbackData.reaction,
  reason: null,
  timestamp: new Date().toISOString(),
}
```

Write `content_meta` for new and existing entries while retaining `video_meta` for backward compatibility.

- [ ] **Step 3: Verify JavaScript syntax**

Run:

```bash
node --check worker/src/index.js
node --check worker/src/vercel-handler.js
```

Expected: both commands exit 0.

- [ ] **Step 4: Review staged hunks against pre-existing dirty changes**

Use `git diff` and interactive staging. Do not include the pre-existing internal-reasoning sanitization hunks in this task's commit.

- [ ] **Step 5: Commit Task 3**

```bash
git add -p worker/src/index.js worker/src/vercel-handler.js
git commit -m "feat: record generic content feedback"
```

---

### Task 4: AI HOT Feedback Card and Quality Selector

**Files:**
- Modify: `main.py`
- Modify: `tests/test_aihot_integration.py`

**Interfaces:**
- Produces: `build_aihot_card_elements(items, enable_feedback=False)`.
- Produces: `select_aihot_items_for_profile(items, profile, ranking_hints, take) -> list[dict]`.

- [ ] **Step 1: Write failing card-action tests**

```python
def test_aihot_card_has_one_click_feedback_actions():
    elements = main.build_aihot_card_elements([{
        "id": "item-1",
        "title": "Loop Engineering",
        "summary": "把提示 Agent 转为设计自动循环。",
        "url": "https://example.com/loop-engineering",
        "source": "Addy Osmani",
        "category": "tip",
        "match_tags": ["Loop Engineering", "Agent"],
    }], enable_feedback=True)
    labels = [a["text"]["content"] for e in elements if e.get("tag") == "action" for a in e["actions"]]
    assert labels == ["查看原文", "👍 有用", "👎 不想看"]
    feedback_values = [a["value"] for e in elements if e.get("tag") == "action" for a in e["actions"] if "value" in a]
    assert feedback_values[0]["content_id"].startswith("aihot:")
    assert feedback_values[0]["content_type"] == "aihot"
```

- [ ] **Step 2: Verify card test RED**

Run: `python3 -m unittest tests.test_aihot_integration.AihotIntegrationTests.test_aihot_card_has_one_click_feedback_actions -v`

Expected: missing parameter/buttons failure.

- [ ] **Step 3: Implement AI HOT buttons and correct channel fallback cards**

- Build app-bot cards with feedback enabled for YouTube and AI HOT.
- If app sending fails, rebuild the webhook card with feedback disabled before fallback.
- Keep AI HOT text format unchanged: title, paragraph-formatted summary, then actions.

- [ ] **Step 4: Write failing quality-selection fixtures**

```python
def test_quality_selector_keeps_agent_frontier_and_rejects_filler():
    items = [
        {"id": "1", "title": "Loop Engineering", "summary": "设计自动循环。", "url": "https://example.com/1", "score": 80, "match_tags": ["Loop Engineering", "Agent"]},
        {"id": "2", "title": "Deep Agents 实战", "summary": "完整 Agent 工作流。", "url": "https://example.com/2", "score": 75, "match_tags": ["Agent", "实战教程"]},
        {"id": "3", "title": "普通 API 入门教程", "summary": "安装并调用 API。", "url": "https://example.com/3", "score": 90, "match_tags": ["入门教程"]},
        {"id": "4", "title": "父亲节合影活动", "summary": "节日营销活动。", "url": "https://example.com/4", "score": 64, "match_tags": ["浅层宣传"]},
        {"id": "5", "title": "模型转售传闻", "summary": "二手信源行业转述。", "url": "https://example.com/5", "score": 75, "match_tags": ["无关行业新闻"]},
    ]
    profile = {
        "description": "AI 产品经理，关注 Agent、硅谷 AI 趋势、GEO 和广告创意",
        "favorite_content": "Agent 工作流、前沿趋势、产品判断和实用方法",
        "deprioritize_topics": ["入门教程", "浅层宣传", "无关行业新闻"],
    }
    selected = select_aihot_items_for_profile(items, profile, "", take=7)
    assert [x["title"] for x in selected] == ["Loop Engineering", "Deep Agents 实战"]
```

- [ ] **Step 5: Implement DeepSeek quality gate and conservative fallback**

DeepSeek prompt must expose three independent lanes:

- Agent priority.
- Silicon Valley frontier trend.
- Business value.

It must explicitly allow practical Agent tutorials, reject generic beginner/API/code-along tutorials, and return at most seven indices in JSON. If DeepSeek fails, deterministic fallback requires a strong lane match plus source score at least 70 and excludes known filler patterns. Never return all candidates merely because fewer than seven exist.

- [ ] **Step 6: Run AI HOT and full tests**

Run:

```bash
python3 -m unittest tests.test_aihot_integration -v
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add main.py tests/test_aihot_integration.py
git commit -m "feat: learn from AI HOT feedback"
```

---

### Task 5: Workflow State and Documentation

**Files:**
- Modify: `.github/workflows/digest.yml`
- Modify: `README.md`

**Interfaces:**
- Persists: `preference_state.json` on the `data` branch.
- Supplies: `DEEPSEEK_API_KEY`, `DEEPSEEK_API_BASE`, and `DEEPSEEK_MODEL` to preference analysis.

- [ ] **Step 1: Update workflow restore defaults**

Add `preference_state.json` to the restore/save list and initialize it with `{}` when missing.

- [ ] **Step 2: Add analysis environment**

```yaml
- name: Analyze feedback and update preferences
  env:
    DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
    DEEPSEEK_API_BASE: ${{ secrets.DEEPSEEK_API_BASE }}
    DEEPSEEK_MODEL: ${{ secrets.DEEPSEEK_MODEL }}
  run: python update_preferences.py
```

- [ ] **Step 3: Update README**

Document:

- AI HOT feedback buttons.
- Daily incremental and weekly consolidation behavior.
- Binary-only feedback.
- `preference_state.json` runtime file.
- Agent/frontier/business AI HOT selection lanes.

- [ ] **Step 4: Validate YAML and diff**

Run:

```bash
python3 -c 'import yaml; yaml.safe_load(open(".github/workflows/digest.yml"))'
git diff --check
```

If PyYAML is unavailable, validate by running the pushed workflow before completion.

- [ ] **Step 5: Commit Task 5**

```bash
git add .github/workflows/digest.yml README.md
git commit -m "chore: schedule continuous preference learning"
```

---

### Task 6: End-to-End Verification and Release

**Files:**
- Verify all files from Tasks 1-5.

- [ ] **Step 1: Run complete local verification**

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile main.py update_preferences.py preference_learning.py
node --check worker/src/index.js
node --check worker/src/vercel-handler.js
git diff --check
```

Expected: zero failures and zero syntax errors.

- [ ] **Step 2: Run idempotence simulation**

Use temporary copies of `feedback.json`, `profile.json`, and `preference_state.json`; run `update_preferences.py` twice and assert the second run does not change preference weights.

- [ ] **Step 3: Push current `main` after fetch**

```bash
git fetch origin
git push origin main
```

- [ ] **Step 4: Deploy callback Worker**

Deploy the currently configured Cloudflare Worker using the repository's documented Wrangler command, without modifying secrets.

- [ ] **Step 5: Trigger and watch GitHub Actions**

```bash
gh workflow run digest.yml --ref main
gh run watch <run-id> --exit-status
```

Verify logs show preference analysis, AI HOT quality selection, and successful Feishu sending.

- [ ] **Step 6: Verify the visible card and persisted feedback path**

Confirm the delivered AI HOT card contains “查看原文 / 👍 有用 / 👎 不想看”. Use a non-mutating callback challenge or fixture to verify Worker parsing; leave the real click for the user to perform in Feishu.

- [ ] **Step 7: Final repository check**

```bash
git status --short --branch
git log --oneline --decorate -8
```

Expected: task commits are on `origin/main`; only the two pre-existing unrelated Worker modifications may remain unstaged.
