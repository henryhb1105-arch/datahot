#!/usr/bin/env python3
"""Publish five idempotent DataHot daily highlights to the configured Bluesky account."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from social_cards import social_image_for_event


TZ = ZoneInfo("Asia/Shanghai")
BSKY_API = "https://bsky.social/xrpc"
SITE_BASE = "https://datahot.xiahongbin.com"
ACCOUNT_DID = "did:plc:hw6oq3mktrtycjkskm4nokbl"
LEGACY_HANDLE = "henryhb1105.bsky.social"
VERIFIED_HANDLE = "datahot.xiahongbin.com"
TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"
DAILY_SLOTS = 5
IMAGE_CARD_CANDIDATE_LIMIT = 12
MAX_CARD_IMAGE_BYTES = 1_000_000
RECENT_POST_LOOKBACK_DAYS = 7
RECENT_POST_LIMIT = 100
MAX_SCHEDULE_DELAY = timedelta(minutes=90)
PROFILE_DISPLAY_NAME = "DataHot｜数据与 AI 热点"
PROFILE_DESCRIPTION = (
    "每天精选数据、分析与 AI 工程动态，关注 Data Agent、数据平台、实时计算与团队实践。"
    "每日 5 条，原文优先。\nhttps://datahot.xiahongbin.com/"
)
PROFILE_WEBSITE = f"{SITE_BASE}/"
CATEGORY_HASHTAGS = {
    "agent": "#AIAgents",
    "platform": "#DataPlatform",
    "insight": "#Analytics",
    "product": "#DataProducts",
    "bi": "#BusinessIntelligence",
}


def _clean(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def english_title(event, limit=92):
    """Return a source-provided English title without inventing a translation."""
    for item in event.get("items") or ():
        if not isinstance(item, dict):
            continue
        title = _clean(item.get("title"), 180)
        if not title:
            continue
        title = re.split(r"\s*(?:\\|\|)\s*", title, maxsplit=1)[0].strip()
        letters = [character for character in title if character.isalpha()]
        ascii_letters = [character for character in letters if character.isascii()]
        if len(ascii_letters) < 8 or len(ascii_letters) / max(1, len(letters)) < 0.8:
            continue
        return title[:limit].rstrip()
    return ""


def bilingual_slot(now):
    """Rotate one discovery-oriented bilingual post through all five time slots."""
    return now.date().toordinal() % DAILY_SLOTS


def image_card_slot(now):
    """Rotate one measurable image-card treatment independently of language."""
    return (bilingual_slot(now) + 2) % DAILY_SLOTS


def hook_first_slot(now):
    """Rotate one title-first text treatment without overlapping other variants."""
    return (bilingual_slot(now) + 3) % DAILY_SLOTS


def select_highlight(data, *, position=0, excluded_event_ids=None, require_english=False):
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
    available = [
        event for event in candidates
        if str(event.get("event_id") or "") not in excluded_event_ids
        and (not require_english or english_title(event))
    ]
    return available[position] if 0 <= position < len(available) else None


def select_image_highlight(
    data,
    *,
    excluded_event_ids=None,
    require_english=False,
    limit=IMAGE_CARD_CANDIDATE_LIMIT,
):
    """Return the highest-ranked eligible article with a safe first-party image."""
    excluded_event_ids = {str(event_id) for event_id in (excluded_event_ids or ())}
    for position in range(max(0, int(limit))):
        event = select_highlight(
            data,
            position=position,
            excluded_event_ids=excluded_event_ids,
            require_english=require_english,
        )
        if not event:
            break
        if social_image_for_event(event, SITE_BASE):
            return event
    return None


def post_hashtags(event):
    tags = ["#DataEngineering"]
    category_tag = CATEGORY_HASHTAGS.get(str(event.get("category") or "").strip().lower())
    if category_tag:
        tags.append(category_tag)
    tags.append("#数据")
    return tags


def tracked_url(event_id, *, source="bluesky", creative="text"):
    if source not in {"bluesky", "x"} or creative not in {"card", "text"}:
        raise ValueError("source/creative must use the analytics allowlist")
    query = urlencode({"utm_source": source, "utm_content": creative})
    return f"{SITE_BASE}/e/{event_id}.html?{query}"


def should_use_image_card(now, slot, image):
    """Use exactly one rotating treatment slot when a safe article image exists."""
    return bool(image) and slot == image_card_slot(now)


def build_post(event, *, slot=0, creative="text", bilingual=False, hook_first=False):
    event_id = str(event.get("event_id") or "")
    if not re.fullmatch(r"[a-f0-9]{12}", event_id):
        raise ValueError("invalid event_id")
    title = _clean(event.get("zh_title"), 80)
    source_title = english_title(event) if bilingual else ""
    bilingual = bool(source_title)
    note = _clean(event.get("reason") or event.get("zh_summary"), 110)
    if creative not in {"card", "text"}:
        raise ValueError("creative must be card or text")
    url = tracked_url(event_id, creative=creative)
    tags = post_hashtags(event)
    link_label = "Read / 中文全文" if bilingual else "阅读全文"
    brand_label = (
        f"DataHot data pick {slot + 1}/{DAILY_SLOTS}｜{source_title}"
        if bilingual else f"DataHot 今日精选 {slot + 1}/{DAILY_SLOTS}｜{title}"
    )
    if hook_first:
        prefix = source_title if bilingual else title
        compact_label = f"DataHot data pick {slot + 1}/{DAILY_SLOTS}" if bilingual else f"DataHot 今日精选 {slot + 1}/{DAILY_SLOTS}"
        suffix = f"\n\n{compact_label} · {link_label}：{url}\n{' '.join(tags)}"
    else:
        prefix = brand_label
        suffix = f"\n\n{link_label}：{url}\n{' '.join(tags)}"
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
    for tag in tags:
        encoded_tag = tag.encode("utf-8")
        tag_start = encoded.index(encoded_tag)
        facets.append({
            "index": {"byteStart": tag_start, "byteEnd": tag_start + len(encoded_tag)},
            "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag[1:]}],
        })
    return {
        "text": text,
        "url": url,
        "canonical_url": f"{SITE_BASE}/e/{event_id}.html",
        "facets": facets,
        "creative": creative,
        "copy_variant": "hook_first" if hook_first else "brand_first",
        "language_variant": "bilingual" if bilingual else "zh",
        "langs": ["en", "zh-CN"] if bilingual else ["zh-CN"],
        "card_title": source_title if bilingual else title,
    }


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


def scheduled_run_state(schedule, *, now=None, max_delay=MAX_SCHEDULE_DELAY):
    """Reject a delayed daily cron before it can consume a later day's rkey."""
    fields = str(schedule or "").strip().split()
    if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:
        raise ValueError("scheduled cron must be a fixed daily minute/hour expression")
    try:
        minute, hour = int(fields[0]), int(fields[1])
    except ValueError as error:
        raise ValueError("scheduled cron minute/hour must be integers") from error
    if not 0 <= minute <= 59 or not 0 <= hour <= 23:
        raise ValueError("scheduled cron minute/hour is out of range")

    now = now or datetime.now(TZ)
    utc_now = now.astimezone(ZoneInfo("UTC"))
    scheduled_at = utc_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if scheduled_at > utc_now:
        scheduled_at -= timedelta(days=1)
    delay = utc_now - scheduled_at
    return {
        "stale": delay > max_delay,
        "scheduled_at": scheduled_at.isoformat().replace("+00:00", "Z"),
        "delay_seconds": int(delay.total_seconds()),
    }


def _json_request(url, *, payload=None, token=""):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    with urlopen(request, timeout=20) as response:
        response_body = response.read()
        if not response_body.strip():
            return {}
        return json.loads(response_body.decode("utf-8"))


def _upload_image_blob(*, token, image_url):
    image_request = Request(image_url, headers={"Accept": "image/*", "User-Agent": "DataHotGrowth/1.0"})
    with urlopen(image_request, timeout=20) as response:
        content_type = str(response.headers.get_content_type() or "").lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("social card asset is not a supported raster image")
        content = response.read(MAX_CARD_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_CARD_IMAGE_BYTES:
        raise ValueError("social card image must be between 1 byte and 1 MB")
    upload = Request(
        f"{BSKY_API}/com.atproto.repo.uploadBlob",
        data=content,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type, "Accept": "application/json"},
        method="POST",
    )
    with urlopen(upload, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    blob = payload.get("blob") if isinstance(payload, dict) else None
    if not isinstance(blob, dict):
        raise ValueError("Bluesky image upload did not return a blob")
    return blob


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


def _get_record(*, did, token, rkey, collection="app.bsky.feed.post"):
    lookup = f"{BSKY_API}/com.atproto.repo.getRecord?" + urlencode({
        "repo": did, "collection": collection, "rkey": rkey,
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


def _recent_published_event_ids(*, did, token, now, lookback_days=RECENT_POST_LOOKBACK_DAYS):
    """Return DataHot articles already posted during the rolling lookback window."""
    lookup = f"{BSKY_API}/com.atproto.repo.listRecords?" + urlencode({
        "repo": did,
        "collection": "app.bsky.feed.post",
        "limit": RECENT_POST_LIMIT,
    })
    payload = _json_request(lookup, token=token)
    cutoff = now.astimezone(ZoneInfo("UTC")) - timedelta(days=max(0, int(lookback_days)))
    event_ids = set()
    for record in payload.get("records") or ():
        if not isinstance(record, dict):
            continue
        created_at = str(((record.get("value") or {}).get("createdAt") or "")).strip()
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.tzinfo is None or created.astimezone(ZoneInfo("UTC")) < cutoff:
            continue
        event_id = _event_id_from_record(record)
        if event_id:
            event_ids.add(event_id)
    return event_ids


def sync_profile(*, handle, password):
    session = _json_request(f"{BSKY_API}/com.atproto.server.createSession", payload={
        "identifier": handle.strip().lower(),
        "password": password,
    })
    did = session["did"]
    token = session["accessJwt"]
    existing = _get_record(
        did=did,
        token=token,
        collection="app.bsky.actor.profile",
        rkey="self",
    )
    record = dict((existing or {}).get("value") or {})
    expected = {
        "displayName": PROFILE_DISPLAY_NAME,
        "description": PROFILE_DESCRIPTION,
        "website": PROFILE_WEBSITE,
    }
    if all(record.get(key) == value for key, value in expected.items()):
        return {"status": "already_synced", "uri": (existing or {}).get("uri")}
    record.update({"$type": "app.bsky.actor.profile", **expected})
    response = _json_request(f"{BSKY_API}/com.atproto.repo.putRecord", token=token, payload={
        "repo": did,
        "collection": "app.bsky.actor.profile",
        "rkey": "self",
        "validate": True,
        "record": record,
    })
    return {"status": "synced", "uri": response.get("uri")}


def sync_handle(*, handle, password):
    """Move the known DataHot DID to its verified domain handle safely."""
    session = _json_request(f"{BSKY_API}/com.atproto.server.createSession", payload={
        "identifier": handle.strip().lower(),
        "password": password,
    })
    did = str(session.get("did") or "")
    current_handle = str(session.get("handle") or "").strip().lower()
    token = session["accessJwt"]
    if did != ACCOUNT_DID:
        raise RuntimeError("Bluesky 会话 DID 与 DataHot 账号不一致，取消域名切换")
    if current_handle not in {LEGACY_HANDLE, VERIFIED_HANDLE}:
        raise RuntimeError("Bluesky 当前 handle 不在允许的迁移范围，取消域名切换")

    lookup = f"{BSKY_API}/com.atproto.identity.resolveHandle?" + urlencode({
        "handle": VERIFIED_HANDLE,
    })
    resolved = _json_request(lookup)
    if str(resolved.get("did") or "") != ACCOUNT_DID:
        raise RuntimeError("DataHot 域名尚未解析到目标 DID，取消域名切换")
    if current_handle == VERIFIED_HANDLE:
        return {
            "status": "already_synced",
            "handle": VERIFIED_HANDLE,
            "did": ACCOUNT_DID,
        }

    _json_request(
        f"{BSKY_API}/com.atproto.identity.updateHandle",
        token=token,
        payload={"handle": VERIFIED_HANDLE},
    )
    return {
        "status": "synced",
        "previous_handle": current_handle,
        "handle": VERIFIED_HANDLE,
        "did": ACCOUNT_DID,
    }


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

    recent_event_ids = _recent_published_event_ids(did=did, token=token, now=now)
    used_event_ids = set(recent_event_ids)
    treatment_slot = image_card_slot(now)
    treatment_already_published = False
    for other_slot in range(DAILY_SLOTS):
        if other_slot == slot:
            continue
        record = _get_record(did=did, token=token, rkey=daily_slot_tid(now, other_slot))
        if other_slot == treatment_slot and record:
            treatment_already_published = True
        event_id = _event_id_from_record(record)
        if event_id:
            used_event_ids.add(event_id)
    wants_bilingual = slot == bilingual_slot(now)
    reserved_card_event = None
    if slot == treatment_slot or not treatment_already_published:
        reserved_card_event = select_image_highlight(
            data,
            excluded_event_ids=used_event_ids,
            require_english=wants_bilingual if slot == treatment_slot else False,
        )
    if slot == treatment_slot:
        event = reserved_card_event
        selection_exclusions = used_event_ids
    else:
        text_exclusions = set(used_event_ids)
        if reserved_card_event:
            text_exclusions.add(str(reserved_card_event.get("event_id") or ""))
        selection_exclusions = text_exclusions
        event = select_highlight(
            data,
            excluded_event_ids=text_exclusions,
            require_english=wants_bilingual,
        )
    if not event and wants_bilingual:
        event = select_highlight(data, excluded_event_ids=selection_exclusions)
    if not event:
        event = select_highlight(data, excluded_event_ids=selection_exclusions)
    if not event:
        return {
            "status": "skipped",
            "reason": "no_unused_event",
            "rkey": rkey,
            "recent_excluded_count": len(recent_event_ids),
        }
    canonical_url = f"{SITE_BASE}/e/{event['event_id']}.html"
    wait_until_live(canonical_url)
    image = social_image_for_event(event, SITE_BASE)
    use_card = should_use_image_card(now, slot, image)
    thumb = None
    if use_card:
        try:
            thumb = _upload_image_blob(token=token, image_url=image["url"])
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
            thumb = None
    creative = "card" if thumb else "text"
    post = build_post(
        event,
        slot=slot,
        creative=creative,
        bilingual=wants_bilingual,
        hook_first=slot == hook_first_slot(now),
    )
    record = {
        "$type": "app.bsky.feed.post",
        "text": post["text"],
        "facets": post["facets"],
        "langs": post["langs"],
        "createdAt": now.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"),
    }
    if thumb:
        record["embed"] = {
            "$type": "app.bsky.embed.external",
            "external": {
                "uri": post["url"],
                "title": post["card_title"],
                "description": _clean(event.get("reason") or event.get("zh_summary"), 200),
                "thumb": thumb,
            },
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
        "creative": creative,
        "copy_variant": post["copy_variant"],
        "language_variant": post["language_variant"],
        "recent_excluded_count": len(recent_event_ids),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="site/data/latest.json")
    parser.add_argument("--slot", type=int, choices=range(DAILY_SLOTS), default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sync-profile", action="store_true")
    parser.add_argument("--sync-handle", action="store_true")
    parser.add_argument("--scheduled-cron", default="")
    args = parser.parse_args(argv)
    enabled = os.getenv("GROWTH_BSKY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    handle = os.getenv("BSKY_HANDLE", "").strip()
    password = os.getenv("BSKY_APP_PASSWORD", "").strip()
    if args.sync_handle:
        if not enabled:
            print(json.dumps({"status": "disabled", "operation": "sync_handle"}, ensure_ascii=False))
            return 0
        if not handle or not password:
            raise SystemExit("GROWTH_BSKY_ENABLED=true 但缺少 BSKY_HANDLE/BSKY_APP_PASSWORD")
        print(json.dumps(sync_handle(handle=handle, password=password), ensure_ascii=False))
        return 0
    if args.sync_profile:
        if not enabled:
            print(json.dumps({"status": "disabled", "operation": "sync_profile"}, ensure_ascii=False))
            return 0
        if not handle or not password:
            raise SystemExit("GROWTH_BSKY_ENABLED=true 但缺少 BSKY_HANDLE/BSKY_APP_PASSWORD")
        print(json.dumps(sync_profile(handle=handle, password=password), ensure_ascii=False))
        return 0

    if args.scheduled_cron:
        schedule_state = scheduled_run_state(args.scheduled_cron)
        if schedule_state["stale"]:
            print(json.dumps({
                "status": "skipped",
                "reason": "stale_schedule",
                "slot": args.slot,
                "scheduled_at": schedule_state["scheduled_at"],
                "delay_seconds": schedule_state["delay_seconds"],
            }, ensure_ascii=False))
            return 0

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    if args.dry_run or not enabled:
        event = select_highlight(data, position=args.slot)
        if not event:
            print(json.dumps({"status": "skipped", "reason": "no_event"}, ensure_ascii=False))
            return 0
        now = datetime.now(TZ)
        post = build_post(
            event,
            slot=args.slot,
            bilingual=args.slot == bilingual_slot(now),
            hook_first=args.slot == hook_first_slot(now),
        )
        print(json.dumps({
            "status": "dry_run" if args.dry_run else "disabled",
            "event_id": event["event_id"],
            "text": post["text"],
            "copy_variant": post["copy_variant"],
            "language_variant": post["language_variant"],
        }, ensure_ascii=False, indent=2))
        return 0
    if not handle or not password:
        raise SystemExit("GROWTH_BSKY_ENABLED=true 但缺少 BSKY_HANDLE/BSKY_APP_PASSWORD")
    print(json.dumps(publish(data, handle=handle, password=password, slot=args.slot), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
