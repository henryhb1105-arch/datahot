#!/usr/bin/env python3
"""Build the small, versioned feed used by polling agents and push adapters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from urllib.parse import urlsplit

from lite_data import is_list_eligible


AGENT_FEED_SCHEMA_VERSION = 1
AGENT_FEED_WINDOW_DAYS = 7
PUSH_POLICY_VERSION = "important-v1"
PUSH_IMPORTANCE_THRESHOLD = 80
PUSH_MULTI_SOURCE_THRESHOLD = 75
PUSH_MAX_AGE_HOURS = 48
PUSH_MAX_PER_RUN = 3
PUSH_MAX_PER_DAY = 5
RECOMMENDED_POLL_SECONDS = 900
EVENT_ID_RE = re.compile(r"[0-9a-f]{12}")
FORBIDDEN_FIELDS = frozenset({
    "full_zh", "content_blocks", "article_blocks", "article_text", "media",
    "fulltext", "body", "raw_html",
})


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _discovered_timestamp(event):
    return _parse_datetime(event.get("first_seen") or event.get("published"))


def _unique_sources(event):
    names = []
    seen = set()
    for item in event.get("items") or []:
        name = " ".join(str(item.get("source") or "").split())
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def recommended_push(event, *, source_count=None):
    """Return the stable server-side importance decision and its reason."""
    source_count = len(_unique_sources(event)) if source_count is None else int(source_count)
    importance = int(event.get("importance") or 0)
    if event.get("pinned"):
        return True, "editor_pinned"
    if importance >= PUSH_IMPORTANCE_THRESHOLD:
        return True, "importance_80"
    if importance >= PUSH_MULTI_SOURCE_THRESHOLD and source_count >= 2:
        return True, "multi_source_importance_75"
    return False, None


def agent_event(event, *, site_base):
    event_id = str(event.get("event_id") or "")
    if not EVENT_ID_RE.fullmatch(event_id):
        raise ValueError(f"invalid event_id: {event_id!r}")
    sources = _unique_sources(event)
    should_push, push_reason = recommended_push(event, source_count=len(sources))
    importance = event.get("importance")
    return {
        "event_id": event_id,
        "title": " ".join(str(event.get("zh_title") or "").split()),
        "summary": " ".join(str(event.get("zh_summary") or "").split()),
        "why_it_matters": " ".join(str(event.get("reason") or "").split()),
        "category": {
            "slug": str(event.get("category") or ""),
            "label": str(event.get("category_label") or ""),
        },
        "topics": list(event.get("topics") or []),
        "vendors": list(event.get("vendors") or []),
        "importance": None if importance in (None, "") else int(importance),
        "heat": int(event.get("heat") or 0),
        "pinned": bool(event.get("pinned")),
        "published_at": event.get("published"),
        "discovered_at": event.get("first_seen") or event.get("published"),
        "sources": {"count": len(sources), "names": sources},
        "push": {"recommended": should_push, "reason": push_reason},
        "links": {"detail": f"{site_base.rstrip('/')}/e/{event_id}.html"},
    }


def build_agent_feed(
    events, generated_at, *, site_base, window_days=AGENT_FEED_WINDOW_DAYS,
):
    """Project recent, editorially complete events into a polling contract."""
    generated = _parse_datetime(generated_at)
    if generated is None:
        raise ValueError("generated_at must be an ISO-8601 datetime")
    reference = generated.astimezone(timezone.utc)
    window = timedelta(days=max(0, float(window_days)))
    selected = []
    for event in events:
        if not is_list_eligible(event):
            continue
        discovered = _discovered_timestamp(event)
        if discovered is None:
            continue
        age = reference - discovered.astimezone(timezone.utc)
        if timedelta(0) <= age <= window:
            selected.append(event)
    selected.sort(
        key=lambda event: (
            _discovered_timestamp(event).isoformat(),
            int(event.get("importance") or 0),
            str(event.get("event_id") or ""),
        ),
        reverse=True,
    )
    return {
        "schema_version": AGENT_FEED_SCHEMA_VERSION,
        "generated_at": generated_at,
        "site_url": site_base.rstrip("/"),
        "push_policy": {
            "version": PUSH_POLICY_VERSION,
            "recommended_poll_seconds": RECOMMENDED_POLL_SECONDS,
            "max_age_hours": PUSH_MAX_AGE_HOURS,
            "max_per_run": PUSH_MAX_PER_RUN,
            "max_per_day": PUSH_MAX_PER_DAY,
            "rules": [
                "pinned",
                f"importance>={PUSH_IMPORTANCE_THRESHOLD}",
                f"importance>={PUSH_MULTI_SOURCE_THRESHOLD} and source_count>=2",
            ],
        },
        "events": [agent_event(event, site_base=site_base) for event in selected],
    }


def find_forbidden_fields(value, *, path="$"):
    violations = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_FIELDS:
                violations.append(child_path)
            violations.extend(find_forbidden_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(find_forbidden_fields(child, path=f"{path}[{index}]"))
    return violations


def validate_agent_feed(payload, *, site_base, site_root=None):
    errors = []
    if payload.get("schema_version") != AGENT_FEED_SCHEMA_VERSION:
        errors.append("schema_version")
    if payload.get("site_url") != site_base.rstrip("/"):
        errors.append("site_url")
    parsed_base = urlsplit(site_base)
    if parsed_base.scheme != "https" or not parsed_base.hostname:
        errors.append("site_base_https")
    if _parse_datetime(payload.get("generated_at")) is None:
        errors.append("generated_at")
    violations = find_forbidden_fields(payload)
    errors.extend(f"forbidden:{path}" for path in violations)

    seen = set()
    previous_key = None
    for item in payload.get("events") or []:
        event_id = str(item.get("event_id") or "")
        if not EVENT_ID_RE.fullmatch(event_id):
            errors.append(f"event_id:{event_id}")
            continue
        if event_id in seen:
            errors.append(f"duplicate:{event_id}")
        seen.add(event_id)
        if not item.get("title") or not item.get("summary"):
            errors.append(f"content:{event_id}")
        detail = (item.get("links") or {}).get("detail")
        expected = f"{site_base.rstrip('/')}/e/{event_id}.html"
        if detail != expected:
            errors.append(f"detail_url:{event_id}")
        source_names = (item.get("sources") or {}).get("names") or []
        if (item.get("sources") or {}).get("count") != len(set(source_names)):
            errors.append(f"source_count:{event_id}")
        discovered = _parse_datetime(item.get("discovered_at"))
        current_key = (
            discovered.isoformat() if discovered else "",
            int(item.get("importance") or 0),
            event_id,
        )
        if previous_key is not None and current_key > previous_key:
            errors.append(f"order:{event_id}")
        previous_key = current_key
        if site_root is not None and not (Path(site_root) / "e" / f"{event_id}.html").is_file():
            errors.append(f"detail_missing:{event_id}")
    return errors
