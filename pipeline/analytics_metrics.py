#!/usr/bin/env python3
"""Validate exported analytics events and compute privacy-safe product metrics."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from analytics_schema import validate_event


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _ratio(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else 0.0


def read_export_lines(lines):
    events = []
    parse_errors = 0
    for line in lines:
        if not str(line).strip():
            continue
        try:
            payload = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            parse_errors += 1
            continue
        if isinstance(payload, dict) and isinstance(payload.get("events"), list):
            events.extend(payload["events"])
        else:
            events.append(payload)
    return events, parse_errors


def compute_metrics(raw_events, parse_errors=0):
    errors = Counter()
    valid, seen_uuids = [], set()
    duplicates = 0
    for event in raw_events:
        event_errors = validate_event(event)
        if event_errors:
            errors.update(event_errors)
            continue
        if event["event_uuid"] in seen_uuids:
            duplicates += 1
            continue
        seen_uuids.add(event["event_uuid"])
        valid.append(event)

    event_counts = Counter(event["name"] for event in valid)
    exposure_pairs = {
        (event["session_id"], event["event_id"])
        for event in valid if event["name"] == "list_exposure"
    }
    detail_pairs = {
        (event["session_id"], event["event_id"])
        for event in valid if event["name"] == "detail_click"
    }
    outbound_pairs = {
        (event["session_id"], event["event_id"])
        for event in valid if event["name"] == "outbound_click"
    }
    favorite_add_pairs = {
        (event["session_id"], event["event_id"])
        for event in valid
        if event["name"] == "favorite_toggle" and event.get("action") == "add"
    }
    feedback_by_reader_event = {}
    for event in valid:
        if event["name"] != "content_feedback":
            continue
        feedback_by_reader_event[(event["device_id"], event["event_id"])] = event
    useful_feedback = sum(
        event.get("action") == "useful"
        for event in feedback_by_reader_event.values()
    )
    feedback_reasons = Counter(
        event.get("feedback_reason")
        for event in feedback_by_reader_event.values()
        if event.get("feedback_reason")
    )
    sessions = {event["session_id"] for event in valid if event["name"] == "session_start"}
    search_sessions = {event["session_id"] for event in valid if event["name"] == "search"}
    filter_sessions = {event["session_id"] for event in valid if event["name"] == "filter"}
    brief_sessions = {
        event["session_id"] for event in valid
        if event["name"] in {"weekly_brief_click", "daily_brief_click"}
    }
    orphan_session_events = sum(
        1 for event in valid
        if event["name"] != "session_start" and event["session_id"] not in sessions
    )

    activity = defaultdict(set)
    daily_devices = defaultdict(set)
    daily_page_views = Counter()
    top_pages = Counter()
    page_referrers = Counter()
    for event in valid:
        day = datetime.fromisoformat(event["ts"].replace("Z", "+00:00")).astimezone(SHANGHAI).date()
        activity[event["device_id"]].add(day)
        if event["name"] == "page_view":
            daily_devices[day.isoformat()].add(event["device_id"])
            daily_page_views[day.isoformat()] += 1
            top_pages[event.get("page_path") or event["page"]] += 1
            page_referrers[event["referrer"]] += 1
    max_day = max((day for days in activity.values() for day in days), default=None)
    cohort, returned = 0, 0
    if max_day:
        for days in activity.values():
            first = min(days)
            if first > max_day - timedelta(days=7):
                continue
            cohort += 1
            if any(1 <= (day - first).days <= 7 for day in days):
                returned += 1

    quality = {
        "input_events": len(raw_events) + parse_errors,
        "valid_events": len(valid),
        "invalid_events": len(raw_events) - len(valid) - duplicates,
        "parse_errors": parse_errors,
        "duplicate_events": duplicates,
        "orphan_session_events": orphan_session_events,
        "invalid_reasons": dict(sorted(errors.items())),
        "valid_rate": _ratio(len(valid), len(raw_events) + parse_errors),
    }
    metrics = {
        "event_counts": dict(sorted(event_counts.items())),
        "unique_sessions": len(sessions),
        "list_exposures": len(exposure_pairs),
        "detail_click_through_rate": _ratio(len(detail_pairs & exposure_pairs), len(exposure_pairs)),
        "outbound_click_rate": _ratio(len(outbound_pairs & detail_pairs), len(detail_pairs)),
        "favorite_rate": _ratio(len(favorite_add_pairs & exposure_pairs), len(exposure_pairs)),
        "content_feedback_count": len(feedback_by_reader_event),
        "useful_feedback_rate": _ratio(useful_feedback, len(feedback_by_reader_event)),
        "content_feedback_reasons": dict(sorted(feedback_reasons.items())),
        "search_usage_rate": _ratio(len(search_sessions & sessions), len(sessions)),
        "filter_usage_rate": _ratio(len(filter_sessions & sessions), len(sessions)),
        "weekly_brief_click_rate": _ratio(len(brief_sessions & sessions), len(sessions)),
        "seven_day_return_rate": _ratio(returned, cohort),
        "seven_day_return_cohort": cohort,
        "daily_active_devices": {
            day: len(devices) for day, devices in sorted(daily_devices.items())
        },
        "daily_page_views": dict(sorted(daily_page_views.items())),
        "top_pages": dict(top_pages.most_common()),
        "page_view_referrers": dict(sorted(page_referrers.items())),
    }
    return {"quality": quality, "metrics": metrics}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        lines = []
        for filename in argv:
            lines.extend(Path(filename).read_text(encoding="utf-8").splitlines())
    else:
        lines = sys.stdin.read().splitlines()
    events, parse_errors = read_export_lines(lines)
    report = compute_metrics(events, parse_errors=parse_errors)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["quality"]["invalid_events"] == 0 and parse_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
