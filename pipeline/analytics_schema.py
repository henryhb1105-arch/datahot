#!/usr/bin/env python3
"""Strict schema for DataHot's anonymous, content-free behavior events."""

from __future__ import annotations

import re
from datetime import datetime


SCHEMA_VERSION = 1
EVENT_NAMES = {
    "session_start", "list_exposure", "detail_click", "outbound_click",
    "favorite_toggle", "content_feedback", "search", "filter",
    "weekly_brief_click", "daily_brief_click",
}
PAGES = {"home", "for-me", "weekly", "daily", "topics", "topic", "classics", "hot", "favorites", "sources", "detail", "privacy", "other"}
CATEGORIES = {"agent", "platform", "bi", "product", "insight", ""}
VIEWPORTS = {"small", "medium", "large"}
REFERRERS = {"direct", "internal", "search", "social", "other"}
ACTIONS = {"add", "remove", "useful", "not_useful", ""}
FEEDBACK_REASONS = {
    "solid", "relevant", "novel", "source_discovery", "irrelevant",
    "shallow", "marketing", "duplicate", "body_quality", "",
}
QUERY_BUCKETS = {"1-3", "4-8", "9+", ""}
ALLOWED_FIELDS = {
    "schema_version", "event_uuid", "name", "ts", "environment", "site_id",
    "page", "event_id", "category", "source", "session_id", "device_id",
    "sequence", "viewport", "referrer", "action", "filter", "query_bucket",
    "result_count", "feedback_reason",
}
REQUIRED_FIELDS = {
    "schema_version", "event_uuid", "name", "ts", "environment", "site_id",
    "page", "session_id", "device_id", "sequence", "viewport", "referrer",
}
EVENT_ID_REQUIRED = {
    "list_exposure", "detail_click", "outbound_click", "favorite_toggle",
    "content_feedback",
}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
EVENT_ID_RE = re.compile(r"^[a-f0-9]{12}$")
SITE_ID_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
SAFE_TEXT_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,80}$")


def _iso_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None


def validate_event(event):
    """Return a list of stable error codes; an empty list means accepted."""
    if not isinstance(event, dict):
        return ["not_object"]
    errors = []
    unknown = set(event) - ALLOWED_FIELDS
    missing = REQUIRED_FIELDS - set(event)
    if unknown:
        errors.append("unknown_fields")
    if missing:
        errors.append("missing_fields")
    if event.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    if event.get("name") not in EVENT_NAMES:
        errors.append("event_name")
    for field in ("event_uuid", "session_id", "device_id"):
        if not UUID_RE.fullmatch(str(event.get(field) or "")):
            errors.append(field)
    if not _iso_timestamp(event.get("ts")):
        errors.append("timestamp")
    if event.get("environment") != "production":
        errors.append("environment")
    if not SITE_ID_RE.fullmatch(str(event.get("site_id") or "")):
        errors.append("site_id")
    if event.get("page") not in PAGES:
        errors.append("page")
    event_id = str(event.get("event_id") or "")
    if event.get("name") in EVENT_ID_REQUIRED and not EVENT_ID_RE.fullmatch(event_id):
        errors.append("event_id_required")
    elif event_id and not EVENT_ID_RE.fullmatch(event_id):
        errors.append("event_id")
    if str(event.get("category") or "") not in CATEGORIES:
        errors.append("category")
    for field, maximum in (("source", 80), ("filter", 40)):
        value = str(event.get(field) or "")
        if len(value) > maximum or not SAFE_TEXT_RE.fullmatch(value):
            errors.append(field)
    sequence = event.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        sequence = -1
    if sequence < 1 or sequence > 1_000_000:
        errors.append("sequence")
    if event.get("viewport") not in VIEWPORTS:
        errors.append("viewport")
    if event.get("referrer") not in REFERRERS:
        errors.append("referrer")
    if str(event.get("action") or "") not in ACTIONS:
        errors.append("action")
    if str(event.get("feedback_reason") or "") not in FEEDBACK_REASONS:
        errors.append("feedback_reason")
    if str(event.get("query_bucket") or "") not in QUERY_BUCKETS:
        errors.append("query_bucket")
    if event.get("name") == "favorite_toggle" and event.get("action") not in {"add", "remove"}:
        errors.append("action_required")
    if event.get("name") == "content_feedback" and event.get("action") not in {"useful", "not_useful"}:
        errors.append("action_required")
    if event.get("name") == "search" and event.get("query_bucket") not in {"1-3", "4-8", "9+"}:
        errors.append("query_bucket_required")
    if "result_count" in event:
        result_count = event["result_count"]
        if not isinstance(result_count, int) or isinstance(result_count, bool):
            result_count = -1
        if result_count < 0 or result_count > 100_000:
            errors.append("result_count")
    return list(dict.fromkeys(errors))
