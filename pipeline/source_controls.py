#!/usr/bin/env python3
"""Per-source scheduling and deterministic prefilters for DataHot."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _number(value, default, minimum=0):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _parse_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _keyword_matches(keyword, text):
    if keyword.isascii() and len(keyword) <= 3 and keyword.isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
    return keyword in text


def source_due(source, state, now, environ=None):
    """Return whether a source is due and an auditable reason."""
    environ = environ if environ is not None else os.environ
    interval_hours = _number(source.get("fetch_interval_hours", 6), 6)
    if _truthy(environ.get("FORCE_SOURCE_FETCH")) or interval_hours == 0:
        return True, "forced" if _truthy(environ.get("FORCE_SOURCE_FETCH")) else "every_run"
    if _number(state.get("fails", 0), 0) > 0:
        return True, "retry_after_failure"
    last_value = (
        state.get("last_attempt")
        or state.get("last_fetch")
        or state.get("last_run")
    )
    last_attempt = _parse_datetime(last_value)
    if not last_attempt:
        return True, "never_fetched"
    due_at = last_attempt.astimezone(timezone.utc) + timedelta(hours=interval_hours)
    now_utc = now.astimezone(timezone.utc)
    if now_utc >= due_at:
        return True, "interval_elapsed"
    remaining_minutes = max(1, int((due_at - now_utc).total_seconds() / 60))
    return False, f"frequency_gate:{remaining_minutes}m_remaining"


def source_candidate_limit(source, default=20):
    return int(_number(source.get("max_candidates_per_run", default), default, minimum=1))


def prefilter_entries(entries, source, now):
    """Apply time, path and keyword filters before article fetch or LLM work."""
    lookback_days = _number(source.get("lookback_days", 7), 7)
    cutoff = now - timedelta(days=lookback_days)
    require_published = bool(source.get("require_published", False))
    include_paths = source.get("path_include", [])
    exclude_paths = source.get("path_exclude", [])
    include_keywords = source.get("include_keywords", [])
    exclude_keywords = source.get("exclude_keywords", [])
    if isinstance(include_paths, str):
        include_paths = [include_paths]
    if isinstance(exclude_paths, str):
        exclude_paths = [exclude_paths]
    if isinstance(include_keywords, str):
        include_keywords = [include_keywords]
    if isinstance(exclude_keywords, str):
        exclude_keywords = [exclude_keywords]
    include_keywords = [str(value).casefold() for value in include_keywords if str(value).strip()]
    exclude_keywords = [str(value).casefold() for value in exclude_keywords if str(value).strip()]

    kept = []
    dropped = {"time": 0, "missing_date": 0, "path": 0, "keyword": 0, "excluded": 0}
    for entry in entries:
        published = entry.get("published")
        if require_published and not published:
            dropped["missing_date"] += 1
            continue
        if published:
            pub = published if published.tzinfo else published.replace(tzinfo=timezone.utc)
            if pub < cutoff:
                dropped["time"] += 1
                continue
        link = str(entry.get("link") or "")
        if include_paths and not any(path in link for path in include_paths):
            dropped["path"] += 1
            continue
        if exclude_paths and any(path in link for path in exclude_paths):
            dropped["path"] += 1
            continue
        haystack = " ".join(
            str(entry.get(key) or "") for key in ("title", "summary", "link")
        ).casefold()
        if include_keywords and not any(_keyword_matches(keyword, haystack) for keyword in include_keywords):
            dropped["keyword"] += 1
            continue
        if exclude_keywords and any(_keyword_matches(keyword, haystack) for keyword in exclude_keywords):
            dropped["excluded"] += 1
            continue
        kept.append(entry)

    floor = datetime.min.replace(tzinfo=timezone.utc)
    def sort_key(entry):
        published = entry.get("published")
        if not published:
            return floor
        if not published.tzinfo:
            published = published.replace(tzinfo=timezone.utc)
        return published.astimezone(timezone.utc)
    kept.sort(key=sort_key, reverse=True)
    stats = {
        "fetched": len(entries),
        "eligible": len(kept),
        "prefiltered": len(entries) - len(kept),
        "dropped": dropped,
    }
    return kept, stats


def source_control_snapshot(source):
    focus_categories = source.get("focus_categories") or []
    if isinstance(focus_categories, str):
        focus_categories = [focus_categories]
    return {
        "tier": source.get("tier", "default"),
        "fetch_interval_hours": _number(source.get("fetch_interval_hours", 6), 6),
        "max_candidates_per_run": source_candidate_limit(source),
        "lookback_days": _number(source.get("lookback_days", 7), 7),
        "require_published": bool(source.get("require_published", False)),
        "has_keyword_filter": bool(source.get("include_keywords") or source.get("exclude_keywords")),
        "focus_categories": [
            value for value in focus_categories
            if value in {"agent", "platform", "bi", "product", "insight"}
        ],
    }


def accepted_categories_by_source(events, accepted_item_ids):
    """Attribute accepted candidates to their final clustered category."""
    accepted_item_ids = set(accepted_item_ids)
    result = {}
    for event in events:
        category = str(event.get("category") or "platform")
        for item in event.get("items") or []:
            if item.get("id") not in accepted_item_ids:
                continue
            source = str(item.get("source") or "")
            if not source:
                continue
            categories = result.setdefault(source, {})
            categories[category] = categories.get(category, 0) + 1
    return result
