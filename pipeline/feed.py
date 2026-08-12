#!/usr/bin/env python3
"""Build and validate DataHot's safe Atom 1.0 feed."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from taxonomy import category_label


ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("", ATOM)
EVENT_ID_RE = re.compile(r"^[a-f0-9]{12}$")


def _tag(name):
    return f"{{{ATOM}}}{name}"


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _atom_time(value):
    parsed = value if isinstance(value, datetime) else _parse_time(value)
    if parsed is None:
        raise ValueError(f"invalid Atom timestamp: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _entry_times(event):
    primary = _parse_time(event.get("published")) or _parse_time(event.get("first_seen"))
    if primary is None:
        return None, None
    candidates = [primary, _parse_time(event.get("first_seen"))]
    for item in event.get("items") or []:
        candidates.extend((_parse_time(item.get("published")), _parse_time(item.get("ingested_at"))))
    updated = max(value for value in candidates if value is not None)
    return primary, updated


def _clean_text(value, maximum):
    return " ".join(str(value or "").split())[:maximum]


def build_atom_feed(events, generated_at, *, site_base, limit=50):
    site_base = str(site_base).rstrip("/")
    generated = _parse_time(generated_at)
    if generated is None:
        raise ValueError("generated_at must be timezone-aware ISO 8601")
    eligible = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        published, updated = _entry_times(event)
        if EVENT_ID_RE.fullmatch(event_id) and published is not None:
            eligible.append((event, published, updated))
    eligible.sort(key=lambda row: (row[2], row[0]["event_id"]), reverse=True)
    eligible = eligible[:max(1, min(200, int(limit or 50)))]

    root = ET.Element(_tag("feed"))
    ET.SubElement(root, _tag("id")).text = f"{site_base}/"
    ET.SubElement(root, _tag("title")).text = "DataHot · 数据领域 AI 热榜"
    ET.SubElement(root, _tag("subtitle")).text = "Data Agent、AI 数据平台、BI、数据产品和 AI分析的中文摘要与原始信源入口"
    ET.SubElement(root, _tag("link"), {"href": f"{site_base}/", "rel": "alternate", "type": "text/html"})
    ET.SubElement(root, _tag("link"), {"href": f"{site_base}/feed.xml", "rel": "self", "type": "application/atom+xml"})
    ET.SubElement(root, _tag("updated")).text = _atom_time(generated)
    author = ET.SubElement(root, _tag("author"))
    ET.SubElement(author, _tag("name")).text = "DataHot"

    for event, published, updated in eligible:
        event_id = event["event_id"]
        detail_url = f"{site_base}/e/{event_id}.html"
        entry = ET.SubElement(root, _tag("entry"))
        ET.SubElement(entry, _tag("id")).text = detail_url
        title = _clean_text(event.get("zh_title") or event.get("title"), 240) or f"DataHot 事件 {event_id}"
        summary = _clean_text(event.get("zh_summary") or event.get("reason"), 1200)
        if not summary:
            summary = "DataHot 已收录此事件，请前往详情页查看摘要与原始信源。"
        ET.SubElement(entry, _tag("title")).text = title
        ET.SubElement(entry, _tag("link"), {"href": detail_url, "rel": "alternate", "type": "text/html"})
        ET.SubElement(entry, _tag("published")).text = _atom_time(published)
        ET.SubElement(entry, _tag("updated")).text = _atom_time(updated)
        category = str(event.get("category") or "platform")[:40]
        label = _clean_text(category_label(category, event.get("category_label") or category), 80)
        ET.SubElement(entry, _tag("category"), {"term": category, "label": label})
        ET.SubElement(entry, _tag("summary"), {"type": "text"}).text = summary
        source_item = next((item for item in event.get("items") or [] if item.get("source")), None)
        if source_item:
            source = ET.SubElement(entry, _tag("source"))
            ET.SubElement(source, _tag("title")).text = _clean_text(source_item.get("source"), 120)
            source_url = str(source_item.get("link") or "")
            parsed = urlsplit(source_url)
            if parsed.scheme == "https" and parsed.netloc:
                ET.SubElement(source, _tag("link"), {"href": source_url, "rel": "alternate", "type": "text/html"})

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def validate_atom_feed(xml_payload, *, site_base, site_root=None):
    """Return stable error codes for XML, schema, URL and local-link failures."""
    errors = []
    try:
        root = ET.fromstring(xml_payload)
    except (ET.ParseError, TypeError, ValueError):
        return ["invalid_xml"]
    if root.tag != _tag("feed"):
        return ["not_atom_feed"]

    base = str(site_base).rstrip("/")
    self_links = [
        node.get("href", "") for node in root.findall(_tag("link"))
        if node.get("rel") == "self" and node.get("type") == "application/atom+xml"
    ]
    if self_links != [f"{base}/feed.xml"]:
        errors.append("self_link")
    if not root.findtext(_tag("title")) or _parse_time(root.findtext(_tag("updated"))) is None:
        errors.append("feed_metadata")

    seen_ids = set()
    entries = root.findall(_tag("entry"))
    for entry in entries:
        entry_id = entry.findtext(_tag("id")) or ""
        if not entry_id or entry_id in seen_ids:
            errors.append("entry_id")
        seen_ids.add(entry_id)
        links = [
            node.get("href", "") for node in entry.findall(_tag("link"))
            if node.get("rel") in {None, "alternate"}
        ]
        if links != [entry_id]:
            errors.append("entry_link")
            continue
        parsed = urlsplit(entry_id)
        if parsed.scheme != "https" or not parsed.netloc or not entry_id.startswith(f"{base}/e/"):
            errors.append("entry_https")
            continue
        if _parse_time(entry.findtext(_tag("published"))) is None or _parse_time(entry.findtext(_tag("updated"))) is None:
            errors.append("entry_time")
        summary = entry.find(_tag("summary"))
        if summary is None or summary.get("type") != "text" or list(summary) or not (summary.text or "").strip():
            errors.append("entry_summary")
        if entry.find(_tag("content")) is not None:
            errors.append("entry_content")
        if site_root is not None:
            path = unquote(parsed.path)
            prefix = urlsplit(f"{base}/").path
            if not path.startswith(prefix):
                errors.append("entry_path")
            else:
                local = Path(site_root) / path[len(prefix):]
                if not local.is_file():
                    errors.append("entry_missing")
    if not entries:
        errors.append("no_entries")
    return list(dict.fromkeys(errors))
