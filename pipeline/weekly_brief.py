#!/usr/bin/env python3
"""Generate one stable, cacheable DataHot brief per completed Beijing week."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from lite_data import event_timestamp, is_list_eligible


TZ = timezone(timedelta(hours=8))
SCHEMA_VERSION = 2
PROMPT_VERSION = "weekly-brief-v1"
MIN_ITEMS = 10
MAX_ITEMS = 15
WEEKLY_SOURCE_CAP = 2
PUBLISH_HOUR = 8
CACHE_WEEKS = 26
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
    parsed = event_timestamp(event)
    return parsed.astimezone(TZ) if parsed else None


def completed_week(value):
    """Return the most recently completed Monday-Sunday Beijing week."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        local_date = value.astimezone(TZ).date()
    elif isinstance(value, date):
        local_date = value
    else:
        local_date = date.fromisoformat(str(value))
    current_monday = local_date - timedelta(days=local_date.weekday())
    period_end = current_monday - timedelta(days=1)
    period_start = period_end - timedelta(days=6)
    iso = period_end.isocalendar()
    return {
        "week_id": f"{iso.year}-W{iso.week:02d}",
        "period_start": period_start,
        "period_end": period_end,
    }


def _publication_ready(local_now):
    """Wait for Monday's 08:17 scheduled run before publishing the new issue."""
    if local_now.weekday() != 0:
        return True
    ready_at = datetime.combine(local_now.date(), time(PUBLISH_HOUR), tzinfo=TZ)
    return local_now >= ready_at


def select_weekly_events(events, period_start, period_end, limit=MAX_ITEMS):
    """Return 10-15 high-value events from one completed Beijing week."""
    if isinstance(period_start, str):
        period_start = date.fromisoformat(period_start)
    if isinstance(period_end, str):
        period_end = date.fromisoformat(period_end)
    candidates = []
    for event in events:
        published_at = _event_datetime(event)
        event_id = str(event.get("event_id") or "")
        if (
            published_at is None
            or not period_start <= published_at.date() <= period_end
            or len(event_id) != 12
            or not is_list_eligible(event)
        ):
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

    selected, selected_ids, source_counts = [], set(), Counter()

    def primary_source(event):
        items = event.get("items") or []
        return str(items[0].get("source") or "") if items else ""

    def add(event):
        source = primary_source(event)
        if not source or source_counts[source] >= WEEKLY_SOURCE_CAP:
            return False
        selected.append(event)
        selected_ids.add(event["event_id"])
        source_counts[source] += 1
        return True

    # Give each active category one seat before filling the remaining positions
    # by score. This is coverage, not a quota: empty categories are not padded.
    for category in CATEGORY_LABELS:
        match = next((
            event for event in candidates
            if event.get("category") == category
            and source_counts[primary_source(event)] < WEEKLY_SOURCE_CAP
        ), None)
        if match is not None:
            add(match)

    target = max(MIN_ITEMS, min(MAX_ITEMS, int(limit or MAX_ITEMS)))
    for event in candidates:
        if len(selected) >= target:
            break
        if event["event_id"] not in selected_ids:
            add(event)
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
            "title": str(event.get("zh_title") or "").strip(),
            "summary": str(event.get("zh_summary") or "").strip(),
            "category": str(event.get("category") or ""),
            "heat": int(event.get("heat") or 0),
        }
        for event in events
    ]
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def brief_cache_key(week_id, input_hash, prompt_version=PROMPT_VERSION, model=""):
    material = {
        "week_id": str(week_id),
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
        primary = (event.get("items") or [{}])[0]
        items.append({
            "event_id": event["event_id"],
            "title": _clean_text(event.get("zh_title") or event.get("title"), 160),
            "summary": _clean_text(event.get("zh_summary"), 360),
            "category": event.get("category") if event.get("category") in CATEGORY_LABELS else "platform",
            "source": _clean_text(sources[0] if sources else "", 80),
            "source_url": _clean_text(primary.get("link"), 800),
            "published": str(event.get("published") or event.get("first_seen") or ""),
            "heat": max(0, min(100, int(event.get("heat") or 0))),
            "importance": max(0, min(100, int(event.get("importance") or 0))),
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
    for event in events[:3]:
        title = _clean_text(event.get("zh_title") or event.get("title"), 110)
        if title:
            changes.append(f"重点关注：{title}")
    leading = overview[0]["label"] if overview else "数据 AI"
    vendors = Counter(
        vendor for event in events for vendor in (event.get("vendors") or []) if vendor
    )
    vendor_text = "、".join(vendor for vendor, _count in vendors.most_common(3))
    next_watch = [f"继续跟踪 {leading} 相关产品和实践的后续落地。"]
    if vendor_text:
        next_watch.append(f"关注 {vendor_text} 的后续发布与跨信源验证。")
    else:
        next_watch.append("关注高热事件是否出现更多独立信源与真实应用反馈。")
    return {
        "headline": "本周数据 AI 关键进展",
        "overview": f"本期筛选 {len(events)} 条高价值事件，覆盖{category_text}。内容按热度、重要性与多信源信号整理。",
        "key_changes": changes,
        "trend": f"本周高价值信息主要集中在 {leading}，其余栏目按质量门槛择优收录。",
        "next_watch": next_watch,
    }


def _prompt(events, week):
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
        "你是 DataHot 的每周简报编辑。只依据给定标题和摘要，用中文总结这一周的数据 AI 进展；"
        "不得补充外部事实，不得预测未给出的事件，不得复制长段正文。输出严格 JSON："
        '{"headline":"不超过30字","overview":"不超过220字",'
        '"key_changes":["三条本周关键变化，每条不超过90字"],'
        '"trend":"不超过160字，只归纳输入中可验证的共同趋势",'
        '"next_watch":["2到3条下周继续跟踪方向，每条不超过80字"]}。'
        f"\n周期：{week['period_start']} 至 {week['period_end']}（{week['week_id']}）"
        f"\n提示词版本：{PROMPT_VERSION}\n事件："
        + json.dumps(input_rows, ensure_ascii=False, separators=(",", ":"))
    )


def valid_brief(brief, week_id=None):
    if (
        not isinstance(brief, dict)
        or brief.get("schema_version") != SCHEMA_VERSION
        or brief.get("kind") != "weekly"
    ):
        return False
    if week_id is not None and brief.get("week_id") != str(week_id):
        return False
    items = brief.get("items")
    return (
        isinstance(items, list) and MIN_ITEMS <= len(items) <= MAX_ITEMS
        and all(isinstance(item, dict) and len(str(item.get("event_id") or "")) == 12 for item in items)
        and bool(str(brief.get("period_start") or ""))
        and bool(str(brief.get("period_end") or ""))
    )


def _merge_ai_copy(response):
    if not isinstance(response, dict):
        return None
    headline = _clean_text(response.get("headline"), 60)
    overview = _clean_text(response.get("overview"), 440)
    changes = response.get("key_changes")
    changes = [
        _clean_text(value, 180) for value in changes[:3]
        if _clean_text(value, 180)
    ] if isinstance(changes, list) else []
    trend = _clean_text(response.get("trend"), 320)
    next_watch = response.get("next_watch")
    next_watch = [
        _clean_text(value, 160) for value in next_watch[:3]
        if _clean_text(value, 160)
    ] if isinstance(next_watch, list) else []
    if not headline or not overview or len(changes) != 3 or not trend or len(next_watch) < 2:
        return None
    return {
        "headline": headline,
        "overview": overview,
        "key_changes": changes,
        "trend": trend,
        "next_watch": next_watch,
    }


def generate_weekly_brief(
    events,
    *,
    now,
    model="",
    llm_generate=None,
    cache_path,
    output_path,
    archive_dir=None,
    force=False,
):
    """Return ``(brief, status)`` and persist one immutable issue per week."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_now = now.astimezone(TZ)
    if not _publication_ready(local_now):
        return None, "before_publish_time"
    week = completed_week(local_now)
    selected = select_weekly_events(events, week["period_start"], week["period_end"])
    if len(selected) < MIN_ITEMS:
        return None, "insufficient_items"

    week_id = week["week_id"]
    input_hash = brief_input_hash(selected)
    key = brief_cache_key(week_id, input_hash, PROMPT_VERSION, model)
    cache = _load_json(cache_path, {"version": 2, "weeks": {}, "entries": {}})
    weeks = cache.setdefault("weeks", {})
    entries = cache.setdefault("entries", {})
    existing_key = weeks.get(week_id)
    existing = entries.get(existing_key) if existing_key else None
    archive_path = Path(archive_dir) / f"{week_id}.json" if archive_dir else None
    if not force and valid_brief(existing, week_id):
        _atomic_json(output_path, existing)
        if archive_path:
            _atomic_json(archive_path, existing)
        return existing, "weekly_cache_hit"

    copy = _rule_copy(selected)
    mode = "rule"
    fallback_reason = "llm_unconfigured"
    if model and llm_generate is not None:
        try:
            response = llm_generate(_prompt(selected, week), item_id=week_id)
            ai_copy = _merge_ai_copy(response)
            if ai_copy is not None:
                copy, mode, fallback_reason = ai_copy, "ai", ""
            else:
                fallback_reason = "invalid_llm_response"
        except Exception as exc:
            fallback_reason = type(exc).__name__[:80]

    brief = {
        "schema_version": SCHEMA_VERSION,
        "kind": "weekly",
        "week_id": week_id,
        "period_start": str(week["period_start"]),
        "period_end": str(week["period_end"]),
        "generated_at": local_now.isoformat(),
        "mode": mode,
        "ai_assisted": mode == "ai",
        "fallback_reason": fallback_reason,
        # This is a deterministic SHA-256 content fingerprint, not a credential.
        # Keep the public field name explicit so secret scanners do not confuse it
        # with an API key.
        "content_fingerprint": key,
        "input_hash": input_hash,
        "prompt_version": PROMPT_VERSION,
        "model": str(model or "rule"),
        "headline": copy["headline"],
        "overview": copy["overview"],
        "key_changes": copy["key_changes"],
        "trend": copy["trend"],
        "next_watch": copy["next_watch"],
        "category_overview": _category_overview(selected),
        "items": _stable_items(selected),
    }
    entries[key] = brief
    weeks[week_id] = key
    keep_weeks = sorted(weeks)[-CACHE_WEEKS:]
    keep_keys = {weeks[item] for item in keep_weeks}
    cache["weeks"] = {item: weeks[item] for item in keep_weeks}
    cache["entries"] = {
        entry_key: entries[entry_key] for entry_key in keep_keys if entry_key in entries
    }
    cache["updated_at"] = local_now.isoformat()
    _atomic_json(cache_path, cache)
    _atomic_json(output_path, brief)
    if archive_path:
        _atomic_json(archive_path, brief)
    return brief, "generated_ai" if mode == "ai" else "generated_rule"
