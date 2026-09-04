#!/usr/bin/env python3
"""Permanent registry and metadata helpers for human-selected articles."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


REGISTRY_PATH = Path(__file__).with_name("editorial_picks.json")
EVENT_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _valid_https_url(value: str) -> bool:
    parts = urlsplit(str(value or "").strip())
    return parts.scheme == "https" and bool(parts.netloc)


def load_editorial_picks(path: Path = REGISTRY_PATH) -> list[dict]:
    """Load and validate the durable human-selection registry."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("editorial picks must use schema_version 1")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("editorial picks must be a non-empty list")

    event_ids: set[str] = set()
    source_urls: set[str] = set()
    discovery_urls: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("editorial pick items must be objects")
        event_id = str(item.get("event_id") or "")
        if not EVENT_ID_RE.fullmatch(event_id):
            raise ValueError(f"invalid editorial pick event_id: {event_id}")
        try:
            datetime.fromisoformat(str(item.get("curated_at") or "").replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"invalid curated_at for {event_id}") from error
        source_url = str(item.get("source_url") or "").strip()
        discovery_url = str(item.get("discovery_url") or "").strip()
        if not _valid_https_url(source_url) or not _valid_https_url(discovery_url):
            raise ValueError(f"editorial pick URLs must use https: {event_id}")
        if event_id in event_ids:
            raise ValueError(f"duplicate editorial pick event_id: {event_id}")
        if source_url in source_urls:
            raise ValueError(f"duplicate editorial pick source_url: {source_url}")
        if discovery_url in discovery_urls:
            raise ValueError(f"duplicate editorial pick discovery_url: {discovery_url}")
        event_ids.add(event_id)
        source_urls.add(source_url)
        discovery_urls.add(discovery_url)
    return items


def editorial_pick_event_ids(path: Path = REGISTRY_PATH) -> frozenset[str]:
    return frozenset(item["event_id"] for item in load_editorial_picks(path))


def apply_editorial_picks(events: list[dict], path: Path = REGISTRY_PATH) -> int:
    """Attach selection provenance without changing canonical article sources."""
    registry = {item["event_id"]: item for item in load_editorial_picks(path)}
    applied = 0
    for event in events:
        pick = registry.get(str(event.get("event_id") or ""))
        if not pick:
            continue
        event["editorial_pick"] = True
        event["curated_at"] = pick["curated_at"]
        applied += 1
    return applied
