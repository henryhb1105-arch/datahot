#!/usr/bin/env python3
"""Deterministically import an editor-reviewed news batch into latest.json.

The batch keeps discovery provenance (for example an X post) separate from the
canonical article URL. Re-running the same batch is idempotent: canonical URLs
are never duplicated and discovery links are merged into existing events.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from editorial_picks import apply_editorial_picks
from taxonomy import CATEGORY_LABELS, normalize_category_labels


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST = ROOT / "site" / "data" / "latest.json"
TRACKING_KEYS = {
    "fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "source",
}


def norm_url(url: str) -> str:
    """Normalize only identity-irrelevant URL details for deduplication."""
    parts = urlsplit(str(url).strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def stable_id(url: str) -> str:
    return hashlib.md5(norm_url(url).encode("utf-8")).hexdigest()[:12]


def iso_timestamp(value: str) -> str:
    """Normalize valid ISO timestamps to the form consumed by site builders."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()


def newest_timestamp_text(current: str, candidate: str) -> str:
    """Keep the newest catalog timestamp while preserving its original text."""
    values = []
    for value in (current, candidate):
        text = str(value or "").strip()
        if not text:
            continue
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        values.append((parsed.astimezone(timezone.utc), text))
    return max(values)[1] if values else ""


def _require_text(record: dict, key: str) -> str:
    value = str(record.get(key) or "").strip()
    if not value:
        raise ValueError(f"missing required field: {key}")
    return value


def validate_batch(batch: dict) -> list[dict]:
    if not isinstance(batch, dict) or batch.get("schema_version") != 1:
        raise ValueError("manual batch must use schema_version 1")
    ingested_at = _require_text(batch, "ingested_at")
    iso_timestamp(ingested_at)
    records = batch.get("items")
    if not isinstance(records, list) or not records:
        raise ValueError("manual batch items must be a non-empty list")

    canonical_urls: set[str] = set()
    discovery_urls: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("manual batch items must be objects")
        for key in (
            "zh_title", "zh_summary", "reason", "full_zh", "source_title",
            "source_url", "published",
        ):
            _require_text(record, key)
        if record.get("category") not in CATEGORY_LABELS:
            raise ValueError(f"invalid category: {record.get('category')}")
        if record.get("shelf", "news") not in {"news", "evergreen"}:
            raise ValueError(f"invalid shelf: {record.get('shelf')}")
        if "source_name" in record:
            _require_text(record, "source_name")
        published = record["published"]
        iso_timestamp(published)
        source_url = norm_url(record["source_url"])
        discovery_url = str(record.get("discovery_url") or "").strip()
        discovery_account = str(record.get("discovery_account") or "").strip()
        if bool(discovery_url) != bool(discovery_account):
            raise ValueError("discovery_url and discovery_account must be provided together")
        if record.get("discovery_published"):
            iso_timestamp(record["discovery_published"])
        if source_url in canonical_urls:
            raise ValueError(f"duplicate canonical URL in batch: {source_url}")
        canonical_urls.add(source_url)
        if discovery_url:
            discovery_url = norm_url(discovery_url)
            if discovery_url in discovery_urls:
                raise ValueError(f"duplicate discovery URL in batch: {discovery_url}")
            discovery_urls.add(discovery_url)
    return records


def _x_item(record: dict, ingested_at: str) -> dict:
    url = record["discovery_url"]
    account = record["discovery_account"].lstrip("@")
    return {
        "id": stable_id(url),
        "source": f"X 线索·@{account}",
        "link": url,
        "published": iso_timestamp(record.get("discovery_published") or record["published"]),
        "ingested_at": ingested_at,
        "title": record.get("discovery_title") or f"X 原帖：{record['zh_title']}",
    }


def _new_event(record: dict, ingested_at: str) -> dict:
    source_url = record["source_url"]
    importance = int(record.get("importance") or 70)
    items = [{
        "id": stable_id(source_url),
        "source": record.get("source_name") or "主编收录",
        "link": source_url,
        "published": iso_timestamp(record["published"]),
        "ingested_at": ingested_at,
        "title": record["source_title"],
    }]
    discovery_url = str(record.get("discovery_url") or "").strip()
    if discovery_url and norm_url(discovery_url) != norm_url(source_url):
        items.append(_x_item(record, ingested_at))
    event = {
        "event_id": stable_id(source_url),
        "zh_title": record["zh_title"],
        "zh_summary": record["zh_summary"],
        "reason": record["reason"],
        "full_zh": record["full_zh"],
        "content_blocks": [],
        "content_format": "",
        "category": record["category"],
        "category_label": CATEGORY_LABELS[record["category"]],
        "vendors": list(dict.fromkeys(record.get("vendors") or []))[:5],
        "heat": int(record.get("heat") or round(0.5 * importance + 20)),
        "star": False,
        "importance": importance,
        "signal": 0,
        "topics": list(dict.fromkeys(record.get("topics") or []))[:2],
        "shelf": record.get("shelf") or "news",
        "pinned": False,
        "published": iso_timestamp(record["published"]),
        "first_seen": ingested_at,
        "items": items,
    }
    if discovery_url:
        event["discovery_url"] = record["discovery_url"]
        event["discovery_source"] = f"X·@{record['discovery_account'].lstrip('@')}"
    return event


def import_batch(batch_path: Path, latest_path: Path = DEFAULT_LATEST) -> dict:
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    records = validate_batch(batch)
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("latest.json events must be a list")
    normalize_category_labels(events)

    by_url: dict[str, dict] = {}
    for event in events:
        for item in event.get("items") or []:
            link = item.get("link")
            if link:
                by_url[norm_url(link)] = event

    added = enriched = unchanged = 0
    for record in records:
        canonical = norm_url(record["source_url"])
        event = by_url.get(canonical)
        if event is None:
            event = _new_event(record, batch["ingested_at"])
            events.append(event)
            for item in event["items"]:
                by_url[norm_url(item["link"])] = event
            added += 1
            continue

        changed = False
        source_name = str(record.get("source_name") or "").strip()
        primary_items = event.get("items") or []
        if source_name and primary_items and primary_items[0].get("source") == "主编收录":
            primary_items[0]["source"] = source_name
            changed = True
        discovery_url = str(record.get("discovery_url") or "").strip()
        if not discovery_url:
            if changed:
                enriched += 1
            else:
                unchanged += 1
            continue
        event["discovery_url"] = discovery_url
        event["discovery_source"] = f"X·@{record['discovery_account'].lstrip('@')}"
        existing_links = {norm_url(item["link"]) for item in event.get("items") or []}
        discovery = norm_url(discovery_url)
        if discovery in existing_links:
            if changed:
                enriched += 1
            else:
                unchanged += 1
            continue
        event.setdefault("items", []).append(_x_item(record, batch["ingested_at"]))
        by_url[discovery] = event
        enriched += 1

    apply_editorial_picks(events)
    events.sort(key=lambda event: str(event.get("first_seen") or event.get("published") or ""), reverse=True)
    payload["events"] = events
    payload["top"] = [
        event["event_id"]
        for event in sorted(events, key=lambda event: int(event.get("heat") or 0), reverse=True)[:3]
    ]
    payload["generated_at"] = newest_timestamp_text(
        payload.get("generated_at"), batch["ingested_at"]
    )
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "batch_id": batch.get("batch_id"),
        "records": len(records),
        "added": added,
        "enriched": enriched,
        "unchanged": unchanged,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    args = parser.parse_args()
    report = import_batch(args.batch, args.latest)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
