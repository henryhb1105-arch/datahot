#!/usr/bin/env python3
"""Publish five idempotent DataHot daily highlights to the configured Bluesky account."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Asia/Shanghai")
BSKY_API = "https://bsky.social/xrpc"
SITE_BASE = "https://datahot.xiahongbin.com"
TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"
DAILY_SLOTS = 5


def _clean(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def select_highlight(data, *, position=0, excluded_event_ids=None):
    excluded_event_ids = {str(event_id) for event_id in (excluded_event_ids or ())}
    events = {str(event.get("event_id") or ""): event for event in data.get("events", [])}
    candidates = []
    seen = set()
    for event_id in data.get("top", []):
        event_id = str(event_id)
        event = events.get(event_id)
        if event and event_id not in seen:
            candidates.append(event)
            seen.add(event_id)
    for event in data.get("events", []):
        event_id = str(event.get("event_id") or "")
        if event_id and event_id not in seen:
            candidates.append(event)
            seen.add(event_id)
    available = [event for event in candidates if str(event.get("event_id") or "") not in excluded_event_ids]
    return available[position] if 0 <= position < len(available) else None


def build_post(event, *, slot=0):
    event_id = str(event.get("event_id") or "")
    if not re.fullmatch(r"[a-f0-9]{12}", event_id):
        raise ValueError("invalid event_id")
    title = _clean(event.get("zh_title"), 80)
    note = _clean(event.get("reason") or event.get("zh_summary"), 110)
    url = f"{SITE_BASE}/e/{event_id}.html"
    suffix = f"\n\n阅读全文：{url}\n#DataAI #数据"
    prefix = f"DataHot 今日精选 {slot + 1}/{DAILY_SLOTS}｜{title}"
    available = max(0, 300 - len(prefix) - len(suffix) - 2)
    body = note[:available]
    text = prefix + (f"\n\n{body}" if body else "") + suffix
    encoded = text.encode("utf-8")
    link = url.encode("utf-8")
    start = encoded.index(link)
    facets = [{
        "index": {"byteStart": start, "byteEnd": start + len(link)},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
    }]
    return {"text": text, "url": url, "facets": facets}


def daily_slot_tid(now, slot=0):
    """Return one stable app.bsky.feed.post TID for each daily slot."""
    if not 0 <= slot < DAILY_SLOTS:
        raise ValueError(f"slot must be between 0 and {DAILY_SLOTS - 1}")
    fixed = datetime(now.year, now.month, now.day, 8, 17, tzinfo=TZ).astimezone(ZoneInfo("UTC"))
    # Slot 0 deliberately preserves the original daily TID (clock id 170), so
    # the first post published before the five-slot rollout remains idempotent.
    value = (int(fixed.timestamp() * 1_000_000) << 10) | (170 + slot)
    encoded = []
    for _ in range(13):
        value, remainder = divmod(value, 32)
        encoded.append(TID_ALPHABET[remainder])
    return "".join(reversed(encoded))


def daily_tid(now):
    """Backward-compatible alias for the original first daily slot."""
    return daily_slot_tid(now, 0)


def _json_request(url, *, payload=None, token=""):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _xrpc_error_name(error):
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    return str(payload.get("error") or "") if isinstance(payload, dict) else ""


def wait_until_live(url, *, attempts=12, delay=10):
    """Confirm the public detail page exists before any external distribution."""
    last_error = None
    for attempt in range(attempts):
        request = Request(url, headers={"User-Agent": "DataHotGrowth/1.0"}, method="GET")
        try:
            with urlopen(request, timeout=15) as response:
                if 200 <= response.status < 400:
                    return
                last_error = RuntimeError(f"live page returned HTTP {response.status}")
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
        if attempt + 1 < attempts:
            time.sleep(delay)
    raise RuntimeError(f"详情页尚未在线，取消本次分发：{url}") from last_error


def _get_record(*, did, token, rkey):
    lookup = f"{BSKY_API}/com.atproto.repo.getRecord?" + urlencode({
        "repo": did, "collection": "app.bsky.feed.post", "rkey": rkey,
    })
    try:
        return _json_request(lookup, token=token)
    except HTTPError as error:
        # The reference PDS returns HTTP 400 + RecordNotFound for a missing
        # record. Only that explicit XRPC error means it is safe to create.
        if _xrpc_error_name(error) == "RecordNotFound":
            return None
        raise


def _event_id_from_record(record):
    value = (record or {}).get("value") or {}
    match = re.search(rf"{re.escape(SITE_BASE)}/e/([a-f0-9]{{12}})\.html", str(value.get("text") or ""))
    return match.group(1) if match else ""


def publish(data, *, handle, password, slot=0, now=None):
    now = now or datetime.now(TZ)
    if not 0 <= slot < DAILY_SLOTS:
        raise ValueError(f"slot must be between 0 and {DAILY_SLOTS - 1}")
    session = _json_request(f"{BSKY_API}/com.atproto.server.createSession", payload={
        "identifier": handle.strip().lower(),
        "password": password,
    })
    did = session["did"]
    token = session["accessJwt"]
    rkey = daily_slot_tid(now, slot)
    existing = _get_record(did=did, token=token, rkey=rkey)
    if existing:
        return {"status": "already_published", "uri": existing.get("uri"), "rkey": rkey}

    used_event_ids = set()
    for other_slot in range(DAILY_SLOTS):
        if other_slot == slot:
            continue
        record = _get_record(did=did, token=token, rkey=daily_slot_tid(now, other_slot))
        event_id = _event_id_from_record(record)
        if event_id:
            used_event_ids.add(event_id)
    event = select_highlight(data, excluded_event_ids=used_event_ids)
    if not event:
        return {"status": "skipped", "reason": "no_unused_event", "rkey": rkey}
    post = build_post(event, slot=slot)
    wait_until_live(post["url"])
    record = {
        "$type": "app.bsky.feed.post",
        "text": post["text"],
        "facets": post["facets"],
        "langs": ["zh-CN"],
        "createdAt": now.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"),
    }
    response = _json_request(f"{BSKY_API}/com.atproto.repo.putRecord", token=token, payload={
        "repo": did,
        "collection": "app.bsky.feed.post",
        "rkey": rkey,
        "validate": True,
        "record": record,
    })
    return {
        "status": "published",
        "uri": response.get("uri"),
        "rkey": rkey,
        "event_id": event["event_id"],
        "slot": slot,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="site/data/latest.json")
    parser.add_argument("--slot", type=int, choices=range(DAILY_SLOTS), default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    enabled = os.getenv("GROWTH_BSKY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    if args.dry_run or not enabled:
        event = select_highlight(data, position=args.slot)
        if not event:
            print(json.dumps({"status": "skipped", "reason": "no_event"}, ensure_ascii=False))
            return 0
        post = build_post(event, slot=args.slot)
        print(json.dumps({
            "status": "dry_run" if args.dry_run else "disabled",
            "event_id": event["event_id"],
            "text": post["text"],
        }, ensure_ascii=False, indent=2))
        return 0
    handle = os.getenv("BSKY_HANDLE", "").strip()
    password = os.getenv("BSKY_APP_PASSWORD", "").strip()
    if not handle or not password:
        raise SystemExit("GROWTH_BSKY_ENABLED=true 但缺少 BSKY_HANDLE/BSKY_APP_PASSWORD")
    print(json.dumps(publish(data, handle=handle, password=password, slot=args.slot), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
