#!/usr/bin/env python3
"""Generate one stable, cacheable DataHot brief per Beijing calendar day."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


TZ = timezone(timedelta(hours=8))
SCHEMA_VERSION = 1
PROMPT_VERSION = "daily-brief-v1"
MIN_ITEMS = 8
MAX_ITEMS = 10
CATEGORY_LABELS = {
    "agent": "Data Agent",
    "platform": "AI 数据平台",
    "bi": "BI 与可视化",
    "product": "数据产品",
}


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path, default):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _event_datetime(event):
    value = event.get("first_seen") or event.get("published")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(TZ)


def select_daily_events(events, target_date, limit=MAX_ITEMS):
    """Return 8-10 high-value events from one Beijing calendar date."""
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)
    candidates = []
    for event in events:
        seen_at = _event_datetime(event)
        event_id = str(event.get("event_id") or "")
        if seen_at is None or seen_at.date() != target_date or len(event_id) != 12:
            continue
        candidates.append(event)
    candidates.sort(
        key=lambda event: (
            int(event.get("heat") or 0),
            int(event.get("importance") or 0),
            len(event.get("items") or []),
            _event_datetime(event) or datetime.min.replace(tzinfo=TZ),
            str(event.get("event_id") or ""),
        ),
        reverse=True,
    )

    # Give each active category one seat, then fill by score. This avoids a
    # single high-volume feed turning a daily brief into ten near-identical rows.
    selected, selected_ids = [], set()
    for category in CATEGORY_LABELS:
        match = next((event for event in candidates if event.get("category") == category), None)
        if match is not None:
            selected.append(match)
            selected_ids.add(match["event_id"])
    for event in candidates:
        if len(selected) >= max(MIN_ITEMS, min(MAX_ITEMS, int(limit or MAX_ITEMS))):
            break
        if event["event_id"] not in selected_ids:
            selected.append(event)
            selected_ids.add(event["event_id"])
    selected.sort(
        key=lambda event: (
            int(event.get("heat") or 0), int(event.get("importance") or 0),
            str(event.get("event_id") or ""),
        ),
        reverse=True,
    )
    return selected


def brief_input_hash(events):
    canonical = [
        {
            "event_id": str(event.get("event_id") or ""),
            "summary": str(event.get("zh_summary") or "").strip(),
        }
        for event in events
    ]
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def brief_cache_key(target_date, input_hash, prompt_version=PROMPT_VERSION, model=""):
    material = {
        "date": str(target_date),
        "input_hash": str(input_hash),
        "prompt_version": str(prompt_version),
        "model": str(model or "rule"),
    }
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clean_text(value, maximum):
    return " ".join(str(value or "").split())[:maximum]


def _stable_items(events):
    items = []
    for event in events:
        sources = [
            str(item.get("source") or "").strip()
            for item in event.get("items", []) if item.get("source")
        ]
        items.append({
            "event_id": event["event_id"],
            "title": _clean_text(event.get("zh_title") or event.get("title"), 160),
            "summary": _clean_text(event.get("zh_summary"), 360),
            "category": event.get("category") if event.get("category") in CATEGORY_LABELS else "platform",
            "source": _clean_text(sources[0] if sources else "", 80),
            "heat": max(0, min(100, int(event.get("heat") or 0))),
        })
    return items


def _category_overview(events):
    counts = Counter(
        event.get("category") if event.get("category") in CATEGORY_LABELS else "platform"
        for event in events
    )
    return [
        {"category": category, "label": label, "count": counts.get(category, 0)}
        for category, label in CATEGORY_LABELS.items() if counts.get(category, 0)
    ]


def _rule_copy(events):
    overview = _category_overview(events)
    category_text = "、".join(f"{row['label']} {row['count']} 条" for row in overview)
    changes = []
    for event in events[:4]:
        title = _clean_text(event.get("zh_title") or event.get("title"), 110)
        if title:
            changes.append(f"重点关注：{title}")
    return {
        "headline": "今日数据领域高价值动态",
        "overview": f"今日筛选 {len(events)} 条高价值事件，覆盖{category_text}。以下按热度、重要性与多信源信号整理。",
        "key_changes": changes,
    }


def _prompt(events, target_date):
    input_rows = [
        {
            "event_id": event["event_id"],
            "title": _clean_text(event.get("zh_title") or event.get("title"), 160),
            "summary": _clean_text(event.get("zh_summary"), 320),
            "category": event.get("category"),
            "source": _clean_text((event.get("items") or [{}])[0].get("source"), 80),
            "heat": int(event.get("heat") or 0),
        }
        for event in events
    ]
    return (
        "你是 DataHot 的每日简报编辑。只依据给定标题和摘要，用中文提炼今日重点；不得补充外部事实，"
        "不得复制长段正文。输出严格 JSON："
        '{"headline":"不超过30字","overview":"不超过180字","key_changes":["每条不超过80字，2到4条"]}。'
        f"\n日期：{target_date}\n提示词版本：{PROMPT_VERSION}\n事件："
        + json.dumps(input_rows, ensure_ascii=False, separators=(",", ":"))
    )


def _valid_brief(brief, target_date=None):
    if not isinstance(brief, dict) or brief.get("schema_version") != SCHEMA_VERSION:
        return False
    if target_date is not None and brief.get("date") != str(target_date):
        return False
    items = brief.get("items")
    return (
        isinstance(items, list) and MIN_ITEMS <= len(items) <= MAX_ITEMS
        and all(isinstance(item, dict) and len(str(item.get("event_id") or "")) == 12 for item in items)
    )


def _merge_ai_copy(rule_copy, response):
    if not isinstance(response, dict):
        return None
    headline = _clean_text(response.get("headline"), 60)
    overview = _clean_text(response.get("overview"), 360)
    changes = response.get("key_changes")
    changes = [
        _clean_text(value, 180) for value in changes[:4]
        if _clean_text(value, 180)
    ] if isinstance(changes, list) else []
    if not headline or not overview or len(changes) < 2:
        return None
    return {"headline": headline, "overview": overview, "key_changes": changes}


def generate_daily_brief(
    events,
    *,
    now,
    model="",
    llm_generate=None,
    cache_path,
    output_path,
    force=False,
):
    """Return ``(brief, status)`` and persist at most one normal brief per day."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_now = now.astimezone(TZ)
    target_date = local_now.date()
    selected = select_daily_events(events, target_date)
    if len(selected) < MIN_ITEMS:
        return None, "insufficient_items"

    input_hash = brief_input_hash(selected)
    key = brief_cache_key(target_date, input_hash, PROMPT_VERSION, model)
    cache = _load_json(cache_path, {"version": 1, "days": {}, "entries": {}})
    days = cache.setdefault("days", {})
    entries = cache.setdefault("entries", {})

    # The normal four-runs-per-day pipeline publishes one immutable edition.
    # Force mode is the explicit recovery path for a bad edition.
    existing_key = days.get(str(target_date))
    existing = entries.get(existing_key) if existing_key else None
    if not force and _valid_brief(existing, target_date):
        _atomic_json(output_path, existing)
        return existing, "daily_cache_hit"

    rule_copy = _rule_copy(selected)
    copy = rule_copy
    mode = "rule"
    fallback_reason = "llm_unconfigured"
    if model and llm_generate is not None:
        try:
            response = llm_generate(_prompt(selected, target_date), item_id=str(target_date))
            ai_copy = _merge_ai_copy(rule_copy, response)
            if ai_copy is not None:
                copy, mode, fallback_reason = ai_copy, "ai", ""
            else:
                fallback_reason = "invalid_llm_response"
        except Exception as exc:  # Budget exhaustion and provider errors both degrade safely.
            fallback_reason = type(exc).__name__[:80]

    brief = {
        "schema_version": SCHEMA_VERSION,
        "date": str(target_date),
        "generated_at": local_now.isoformat(),
        "mode": mode,
        "ai_assisted": mode == "ai",
        "fallback_reason": fallback_reason,
        "cache_key": key,
        "input_hash": input_hash,
        "prompt_version": PROMPT_VERSION,
        "model": str(model or "rule"),
        "headline": copy["headline"],
        "overview": copy["overview"],
        "key_changes": copy["key_changes"],
        "category_overview": _category_overview(selected),
        "items": _stable_items(selected),
    }
    entries[key] = brief
    days[str(target_date)] = key
    keep_days = sorted(days)[-14:]
    keep_keys = {days[day] for day in keep_days}
    cache["days"] = {day: days[day] for day in keep_days}
    cache["entries"] = {entry_key: entries[entry_key] for entry_key in keep_keys if entry_key in entries}
    cache["updated_at"] = local_now.isoformat()
    _atomic_json(cache_path, cache)
    _atomic_json(output_path, brief)
    return brief, "generated_ai" if mode == "ai" else "generated_rule"
