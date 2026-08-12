#!/usr/bin/env python3
"""Build the metadata-only payload used by lists, search and favourites."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone


LITE_SCHEMA_VERSION = 1
DEFAULT_PAGE_SIZE = 20
DEFAULT_VENDOR_CAP = 4
DEFAULT_CATEGORY_SOFT_CAP = 12
DEFAULT_WINDOW_SOURCE_CAP = 20
HOME_WINDOW_DAYS = 7
MIN_PUBLIC_IMPORTANCE = 30
FIRST_PAGE_SOURCE_CAPS = {"Claude 官方博客": 2}
WINDOW_SOURCE_CAPS = {"Claude 官方博客": 6}
LIST_CATEGORIES = frozenset({"agent", "platform", "bi", "product", "insight"})
HAN_RE = re.compile(r"[\u3400-\u9fff]")
FORBIDDEN_FIELDS = {
    "full_zh", "content_blocks", "article_blocks", "article_text", "media",
    "summary", "fulltext", "body", "raw_html",
}


def _primary_source(event):
    items = event.get("items") or []
    return str(items[0].get("source") or "") if items else ""


def _primary_vendor(event):
    vendors = event.get("vendors") or []
    return str(vendors[0]) if vendors else _primary_source(event)


def event_timestamp(event):
    """Return the editorial event time, preferring publication over ingestion."""
    value = event.get("published") or event.get("first_seen")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_list_eligible(event):
    """Fail closed for unfinished or untranslated items on public lists.

    Detail pages remain addressable, but homepage, hot-list and weekly-brief
    surfaces only promote entries that completed the Chinese editorial pass.
    """
    title = " ".join(str(event.get("zh_title") or "").split())
    summary = " ".join(str(event.get("zh_summary") or "").split())
    if not title or not summary:
        return False
    if not HAN_RE.search(f"{title} {summary}"):
        return False
    if str(event.get("category") or "") not in LIST_CATEGORIES:
        return False
    raw_importance = event.get("importance")
    if raw_importance not in (None, ""):
        try:
            importance = int(raw_importance)
        except (TypeError, ValueError):
            return False
        if importance < MIN_PUBLIC_IMPORTANCE:
            return False
    else:
        # Older retained events predate importance scoring. Keep them public
        # until they receive an explicit editorial score.
        importance = 50
    editorial_signal = bool(
        str(event.get("reason") or "").strip()
        or event.get("topics") or event.get("vendors") or event.get("pinned")
        or importance != 50
    )
    if not editorial_signal:
        return False
    return bool(_primary_source(event) and event_timestamp(event))


def select_home_events(
    events, *, default_source_cap=DEFAULT_WINDOW_SOURCE_CAP, source_caps=None,
):
    """Return the qualified seven-day feed with bursty sources bounded.

    This is deliberately separate from first-page ranking: the same curated
    pool powers search and load-more, so hidden backlog cannot reappear later.
    """
    caps = dict(WINDOW_SOURCE_CAPS)
    if source_caps:
        caps.update(source_caps)
    source_counts = Counter()
    selected = []
    for event in sorted(events, key=_sort_key, reverse=True):
        if not is_list_eligible(event):
            continue
        source = _primary_source(event)
        cap = max(0, int(caps.get(source, default_source_cap)))
        if source_counts[source] >= cap:
            continue
        selected.append(event)
        source_counts[source] += 1
    return selected


def select_timeline_events(events):
    """Return every qualified retained event for the progressive timeline.

    Source caps belong to short-window promotion surfaces. Applying them to
    the complete timeline would permanently hide valid history, so this pool
    only applies the public editorial gate and chronological ordering.
    """
    return sorted(
        (event for event in events if is_list_eligible(event)),
        key=_sort_key,
        reverse=True,
    )


def _quality_gate(event):
    """Only meaningful signals may override the category soft cap."""
    return bool(
        event.get("pinned")
        or int(event.get("importance") or 0) >= 70
        or int(event.get("heat") or 0) >= 65
        or len(event.get("items") or []) >= 2
    )


def _sort_key(event):
    timestamp = event_timestamp(event)
    return (
        timestamp.isoformat() if timestamp else "",
        int(event.get("heat") or 0),
        int(event.get("importance") or 0),
        str(event.get("event_id") or ""),
    )


def rank_home_events(
    events, *, page_size=DEFAULT_PAGE_SIZE, vendor_cap=DEFAULT_VENDOR_CAP,
    category_soft_cap=DEFAULT_CATEGORY_SOFT_CAP, minimum_page_size=20,
    first_page_only=False, source_caps=None, prevent_adjacent_sources=False,
):
    """Return a stable order whose first page is diverse without quotas.

    Vendor caps are hard on the first page. The category cap is soft: an event
    can exceed it only when it passes a content-quality gate. If the result is
    shorter than the desired first-screen floor, category limits relax while
    the vendor cap remains intact.
    """
    ordered = sorted(events, key=_sort_key, reverse=True)
    selected = []
    deferred = []
    vendor_counts = Counter()
    source_counts = Counter()
    category_counts = Counter()
    selected_ids = set()
    source_caps = dict(source_caps or {})

    def can_add(
        event, *, allow_quality=False, relax_category=False,
        relax_adjacency=False,
    ):
        vendor = _primary_vendor(event)
        source = _primary_source(event)
        category = str(event.get("category") or "")
        if vendor and vendor_counts[vendor] >= vendor_cap:
            return False
        if source in source_caps and source_counts[source] >= int(source_caps[source]):
            return False
        if (
            prevent_adjacent_sources and not relax_adjacency and selected
            and source and source == _primary_source(selected[-1])
        ):
            return False
        return (
            relax_category
            or category_counts[category] < category_soft_cap
            or (allow_quality and _quality_gate(event))
        )

    def add(event):
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in selected_ids:
            return
        selected.append(event)
        selected_ids.add(event_id)
        vendor_counts[_primary_vendor(event)] += 1
        source_counts[_primary_source(event)] += 1
        category_counts[str(event.get("category") or "")] += 1

    for event in ordered:
        if len(selected) >= page_size:
            deferred.append(event)
        elif can_add(event):
            add(event)
        else:
            deferred.append(event)

    # First let every category compete under the same ceiling. Only after that
    # may genuinely strong events cross the category ceiling.
    floor = min(page_size, max(0, minimum_page_size))
    target = page_size if len(ordered) >= page_size else floor
    if len(selected) < target:
        for event in deferred:
            if len(selected) >= target:
                break
            if can_add(event, allow_quality=True):
                add(event)

    # Operational floor: a sparse source mix must not leave a broken-looking
    # first screen. This last resort still retains the hard vendor cap.
    if len(selected) < floor:
        for event in deferred:
            if len(selected) >= floor:
                break
            if can_add(event, relax_category=True, relax_adjacency=True):
                add(event)

    if first_page_only:
        return selected
    return selected + [event for event in ordered if event.get("event_id") not in selected_ids]


def rank_timeline_events(
    events, *, page_size=DEFAULT_PAGE_SIZE, source_caps=None,
    prevent_adjacent_sources=True,
):
    """Order the full timeline in diverse pages without losing history.

    Dates remain strictly descending so loading another page only appends to
    the current last day or adds older days. Diversity is applied within each
    day in page-sized batches; if a day has too little source variety, the
    remaining items fill the batch rather than disappearing.
    """
    by_day = {}
    for event in select_timeline_events(events):
        timestamp = event_timestamp(event)
        day = timestamp.date().isoformat() if timestamp else "unknown"
        by_day.setdefault(day, []).append(event)

    ranked = []
    size = max(1, int(page_size))
    for day in sorted(by_day, reverse=True):
        remaining = list(by_day[day])
        while remaining:
            target = min(size, len(remaining))
            batch = rank_home_events(
                remaining,
                page_size=target,
                minimum_page_size=target,
                first_page_only=True,
                source_caps=source_caps,
                prevent_adjacent_sources=prevent_adjacent_sources,
            )
            batch_ids = {event.get("event_id") for event in batch}
            if len(batch) < target:
                for event in remaining:
                    if event.get("event_id") in batch_ids:
                        continue
                    batch.append(event)
                    batch_ids.add(event.get("event_id"))
                    if len(batch) >= target:
                        break
            ranked.extend(batch)
            remaining = [event for event in remaining if event.get("event_id") not in batch_ids]
    return ranked


def rank_hot_events(events, *, limit=9, source_cap=2):
    """Rank a trustworthy hot list while preventing one publisher takeover.

    Selection is strictly heat-descending: every round picks the highest-heat
    remaining event whose source is still under the cap. A same-source
    adjacency rule previously let a lower-heat event outrank a higher-heat
    one (issue #82); the source cap alone is enough to prevent a takeover,
    so the displayed order now always matches the shown heat values.
    """
    counts = Counter()
    selected = []
    remaining = sorted(
        (event for event in events if is_list_eligible(event)),
        key=lambda event: (
            int(event.get("heat") or 0),
            int(event.get("importance") or 0),
            (event_timestamp(event).isoformat() if event_timestamp(event) else ""),
            str(event.get("event_id") or ""),
        ),
        reverse=True,
    )
    cap = max(1, int(source_cap))
    target = max(0, int(limit))
    while remaining and len(selected) < target:
        candidate_index = next((
            index for index, event in enumerate(remaining)
            if counts[_primary_source(event)] < cap
        ), None)
        if candidate_index is None:
            break
        event = remaining.pop(candidate_index)
        source = _primary_source(event)
        selected.append(event)
        counts[source] += 1
    return selected


def lite_event(event):
    """Project one event to the documented non-body field allowlist."""
    return {
        "event_id": event.get("event_id", ""),
        "zh_title": event.get("zh_title", ""),
        "zh_summary": event.get("zh_summary", ""),
        "reason": event.get("reason", ""),
        "category": event.get("category", ""),
        "category_label": event.get("category_label", ""),
        "vendors": list(event.get("vendors") or []),
        "topics": list(event.get("topics") or []),
        **({"work_tags": event["work_tags"]} if isinstance(event.get("work_tags"), dict) else {}),
        "heat": int(event.get("heat") or 0),
        "star": bool(event.get("star")),
        "importance": (
            None if event.get("importance") in (None, "")
            else int(event.get("importance"))
        ),
        "shelf": event.get("shelf", "news"),
        "pinned": bool(event.get("pinned")),
        "published": event.get("published"),
        "first_seen": event.get("first_seen"),
        "items": [
            {"source": item.get("source", "")}
            for item in (event.get("items") or []) if item.get("source")
        ],
    }


def build_lite_payload(events, generated_at, *, ranking=None, page_size=DEFAULT_PAGE_SIZE):
    if ranking is None:
        ranking = rank_timeline_events(events, page_size=page_size)
    return {
        "schema_version": LITE_SCHEMA_VERSION,
        "generated_at": generated_at,
        "page_size": page_size,
        "home_event_ids": [event["event_id"] for event in ranking],
        "events": [lite_event(event) for event in events],
    }


def find_forbidden_fields(value, *, path="$"):
    """Return recursive body-field violations for build/tests."""
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
