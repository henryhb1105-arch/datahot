#!/usr/bin/env python3
"""Publish one idempotent DataHot daily highlight to the configured Bluesky account."""

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


def _clean(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def select_highlight(data):
    events = {str(event.get("event_id") or ""): event for event in data.get("events", [])}
    for event_id in data.get("top", []):
        event = events.get(str(event_id))
        if event:
            return event
    return next(iter(data.get("events", [])), None)


def build_post(event):
    event_id = str(event.get("event_id") or "")
    if not re.fullmatch(r"[a-f0-9]{12}", event_id):
        raise ValueError("invalid event_id")
    title = _clean(event.get("zh_title"), 80)
    note = _clean(event.get("reason") or event.get("zh_summary"), 110)
    url = f"{SITE_BASE}/e/{event_id}.html"
    suffix = f"\n\n阅读全文：{url}\n#DataAI #数据"
    prefix = f"DataHot 今日重点｜{title}"
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


def daily_tid(now):
    """Return the same valid app.bsky.feed.post TID for every retry that day."""
    fixed = datetime(now.year, now.month, now.day, 8, 17, tzinfo=TZ).astimezone(ZoneInfo("UTC"))
    value = (int(fixed.timestamp() * 1_000_000) << 10) | 170
    encoded = []
    for _ in range(13):
        value, remainder = divmod(value, 32)
        encoded.append(TID_ALPHABET[remainder])
    return "".join(reversed(encoded))


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


def publish(post, *, handle, password, now=None):
    now = now or datetime.now(TZ)
    session = _json_request(f"{BSKY_API}/com.atproto.server.createSession", payload={
        "identifier": handle.strip().lower(),
        "password": password,
    })
    did = session["did"]
    token = session["accessJwt"]
    rkey = daily_tid(now)
    lookup = f"{BSKY_API}/com.atproto.repo.getRecord?" + urlencode({
        "repo": did, "collection": "app.bsky.feed.post", "rkey": rkey,
    })
    try:
        existing = _json_request(lookup, token=token)
        return {"status": "already_published", "uri": existing.get("uri"), "rkey": rkey}
    except HTTPError as error:
        if error.code != 404:
            raise
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
    return {"status": "published", "uri": response.get("uri"), "rkey": rkey}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="site/data/latest.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    event = select_highlight(data)
    if not event:
        print(json.dumps({"status": "skipped", "reason": "no_event"}, ensure_ascii=False))
        return 0
    post = build_post(event)
    enabled = os.getenv("GROWTH_BSKY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    if args.dry_run or not enabled:
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
    wait_until_live(post["url"])
    print(json.dumps(publish(post, handle=handle, password=password), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
