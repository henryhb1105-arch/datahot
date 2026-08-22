#!/usr/bin/env python3
"""Poll DataHot and send important events as one OpenClaw message each.

The first successful run only creates a baseline. Delivery attempts are stored
before invoking OpenClaw, so an ambiguous timeout or malformed CLI response is
never followed by an automatic blind resend.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


STATE_SCHEMA_VERSION = 1
FEED_SCHEMA_VERSION = 1
DEFAULT_FEED_URL = "https://datahot.xiahongbin.com/data/agent-feed.json"
DEFAULT_STATE_FILE = Path.home() / ".openclaw" / "workspace" / ".state" / "datahot-push.json"
DEFAULT_CONFIG_FILE = Path.home() / ".openclaw" / "workspace" / "config" / "datahot-push.json"
EVENT_ID_RE = re.compile(r"[0-9a-f]{12}")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_FEED_BYTES = 2_000_000


class PushError(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def isoformat_utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def new_state():
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "initialized_at": None,
        "etag": None,
        "events": {},
        "attempts_by_day": {},
    }


def load_state(path):
    path = Path(path)
    if not path.exists():
        return new_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PushError(f"无法读取状态文件 {path}: {error}") from error
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise PushError(f"不支持的状态版本: {state.get('schema_version')!r}")
    if not isinstance(state.get("events"), dict) or not isinstance(state.get("attempts_by_day"), dict):
        raise PushError("状态文件结构不完整")
    return state


def save_state(path, state):
    """Atomically persist private state with owner-only permissions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(state, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def validate_feed(payload):
    if not isinstance(payload, dict) or payload.get("schema_version") != FEED_SCHEMA_VERSION:
        raise PushError("DataHot Agent Feed schema_version 不受支持")
    if parse_datetime(payload.get("generated_at")) is None:
        raise PushError("DataHot Agent Feed 缺少有效 generated_at")
    events = payload.get("events")
    if not isinstance(events, list):
        raise PushError("DataHot Agent Feed events 不是数组")
    seen = set()
    for item in events:
        event_id = str(item.get("event_id") or "") if isinstance(item, dict) else ""
        if not EVENT_ID_RE.fullmatch(event_id) or event_id in seen:
            raise PushError(f"DataHot Agent Feed event_id 无效或重复: {event_id!r}")
        seen.add(event_id)
        detail = ((item.get("links") or {}).get("detail") or "").strip()
        parsed = urlsplit(detail)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "datahot.xiahongbin.com"
            or parsed.path != f"/e/{event_id}.html"
            or parsed.query
            or parsed.fragment
        ):
            raise PushError(f"DataHot 详情链接无效: {event_id}")
        if not str(item.get("title") or "").strip():
            raise PushError(f"DataHot 标题为空: {event_id}")
        if parse_datetime(item.get("discovered_at")) is None:
            raise PushError(f"DataHot discovered_at 无效: {event_id}")
        recommended = (item.get("push") or {}).get("recommended")
        if not isinstance(recommended, bool):
            raise PushError(f"DataHot push.recommended 无效: {event_id}")
    return payload


def fetch_feed(url, *, etag=None, timeout=20):
    headers = {
        "Accept": "application/json",
        "User-Agent": "DataHot-OpenClaw-Push/1.0",
    }
    if etag:
        headers["If-None-Match"] = str(etag)
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_FEED_BYTES + 1)
            if len(raw) > MAX_FEED_BYTES:
                raise PushError("DataHot Agent Feed 超过 2 MB 安全上限")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise PushError(f"DataHot Agent Feed 不是有效 JSON: {error}") from error
            return validate_feed(payload), response.headers.get("ETag"), False
    except HTTPError as error:
        if error.code == 304:
            return None, etag, True
        raise PushError(f"DataHot Agent Feed HTTP {error.code}") from error
    except URLError as error:
        raise PushError(f"无法连接 DataHot Agent Feed: {error.reason}") from error


def _snapshot(item, *, now, status="seen"):
    return {
        "importance": item.get("importance"),
        "recommended": bool((item.get("push") or {}).get("recommended")),
        "status": status,
        "last_seen_at": isoformat_utc(now),
    }


def initialize_state(payload, state, *, now, etag=None):
    state["initialized_at"] = isoformat_utc(now)
    state["etag"] = etag
    state["events"] = {
        item["event_id"]: _snapshot(item, now=now, status="seen")
        for item in payload["events"]
    }
    return state


def _within_age(item, *, now, max_age_hours):
    discovered = parse_datetime(item.get("discovered_at"))
    if discovered is None:
        return False
    age = now.astimezone(timezone.utc) - discovered.astimezone(timezone.utc)
    return timedelta(0) <= age <= timedelta(hours=max(0, float(max_age_hours)))


def prepare_candidates(payload, state, *, now, max_age_hours=48):
    """Update observations and leave deferred eligible events in pending state."""
    candidates = []
    for item in payload["events"]:
        event_id = item["event_id"]
        recommended = bool((item.get("push") or {}).get("recommended"))
        previous = state["events"].get(event_id)
        status = str((previous or {}).get("status") or "seen")
        newly_eligible = recommended and (
            previous is None or not bool(previous.get("recommended"))
        )
        if status in {"sent", "attempted", "failed"}:
            next_status = status
        elif recommended and status == "pending":
            next_status = "pending"
        elif newly_eligible and _within_age(item, now=now, max_age_hours=max_age_hours):
            next_status = "pending"
        elif newly_eligible:
            next_status = "expired"
        elif not recommended and status == "pending":
            next_status = "seen"
        else:
            next_status = status
        snapshot = _snapshot(item, now=now, status=next_status)
        for key in ("attempted_at", "sent_at", "error"):
            if previous and key in previous:
                snapshot[key] = previous[key]
        state["events"][event_id] = snapshot
        if next_status == "pending" and _within_age(item, now=now, max_age_hours=max_age_hours):
            candidates.append(item)

    candidates.sort(
        key=lambda item: (
            int(item.get("importance") or 0),
            parse_datetime(item.get("discovered_at")).isoformat(),
            item["event_id"],
        ),
        reverse=True,
    )
    return candidates


def _trim_state(state, *, now):
    cutoff = now.astimezone(timezone.utc) - timedelta(days=90)
    state["events"] = {
        event_id: value for event_id, value in state["events"].items()
        if (parse_datetime(value.get("last_seen_at")) or now) >= cutoff
    }
    allowed_days = {
        (now.astimezone(SHANGHAI).date() - timedelta(days=offset)).isoformat()
        for offset in range(14)
    }
    state["attempts_by_day"] = {
        day: int(count) for day, count in state["attempts_by_day"].items()
        if day in allowed_days
    }


def _clean_text(value, limit):
    text = " ".join(str(value or "").split())
    text = URL_RE.sub("", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def format_message(item):
    """Render exactly one event with exactly one raw, clickable detail URL."""
    importance = item.get("importance")
    label = f"重要度 {importance}" if importance not in (None, "") else "编辑重点"
    title = _clean_text(item.get("title"), 120)
    reason = _clean_text(item.get("why_it_matters") or item.get("summary"), 280)
    detail = (item.get("links") or {})["detail"]
    return f"🔥 DataHot｜{label}\n\n{title}\n\n为什么值得看：{reason}\n\n{detail}"


def process_payload(
    payload, state, *, now, etag=None, sender, persist,
    max_age_hours=48, max_per_run=3, max_per_day=5,
):
    """Process one feed response and persist before every external send."""
    validate_feed(payload)
    if not state.get("initialized_at"):
        initialize_state(payload, state, now=now, etag=etag)
        _trim_state(state, now=now)
        persist(state)
        return {"baseline": True, "sent": [], "failed": [], "pending": 0}

    state["etag"] = etag
    candidates = prepare_candidates(
        payload, state, now=now, max_age_hours=max_age_hours,
    )
    _trim_state(state, now=now)
    day = now.astimezone(SHANGHAI).date().isoformat()
    attempted_today = int(state["attempts_by_day"].get(day, 0))
    allowance = max(0, int(max_per_day) - attempted_today)
    selected = candidates[: min(max(0, int(max_per_run)), allowance)]
    persist(state)

    sent = []
    failed = []
    for item in selected:
        event_id = item["event_id"]
        record = state["events"][event_id]
        record["status"] = "attempted"
        record["attempted_at"] = isoformat_utc(now)
        record.pop("error", None)
        state["attempts_by_day"][day] = int(state["attempts_by_day"].get(day, 0)) + 1
        persist(state)
        try:
            ok, error = sender(format_message(item))
        except Exception as exc:  # fail closed after the recorded attempt
            ok, error = False, str(exc)
        if ok:
            record["status"] = "sent"
            record["sent_at"] = isoformat_utc(now)
            sent.append(event_id)
        else:
            record["status"] = "failed"
            record["error"] = _clean_text(error or "send failed", 240)
            failed.append(event_id)
        persist(state)
    pending = sum(1 for value in state["events"].values() if value.get("status") == "pending")
    return {"baseline": False, "sent": sent, "failed": failed, "pending": pending}


def load_sender_config(path):
    path = Path(path)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PushError(f"缺少推送配置文件: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise PushError(f"无法读取推送配置文件 {path}: {error}") from error
    command = str(config.get("openclaw_command") or "")
    channel = str(config.get("channel") or "")
    target = str(config.get("target") or "")
    account = str(config.get("account") or "")
    command_path = Path(command).expanduser()
    if (
        not command
        or "\x00" in command
        or not command_path.is_absolute()
        or not command_path.is_file()
        or not os.access(command_path, os.X_OK)
        or not channel
        or not target
        or target.startswith("REPLACE_")
    ):
        raise PushError(
            "推送配置必须包含可执行的绝对 openclaw_command、channel 和非占位 target"
        )
    return {
        "openclaw_command": str(command_path),
        "channel": channel,
        "target": target,
        "account": account,
    }


def openclaw_sender(config, *, timeout=60):
    def send(message):
        argv = [
            config["openclaw_command"], "message", "send",
            "--channel", config["channel"],
            "--target", config["target"],
            "--message", message,
            "--json",
        ]
        if config.get("account"):
            argv.extend(["--account", config["account"]])
        try:
            completed = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, str(error)
        if completed.returncode == 0:
            # Exit 0 is authoritative. Do not parse or retry on noisy plugin JSON.
            return True, ""
        diagnostic = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        return False, diagnostic

    return send


def _dry_run(payload, state, *, now, max_age_hours, max_per_run, max_per_day):
    shadow = copy.deepcopy(state)
    if not shadow.get("initialized_at"):
        return {"baseline": True, "messages": [], "pending": 0}
    candidates = prepare_candidates(payload, shadow, now=now, max_age_hours=max_age_hours)
    day = now.astimezone(SHANGHAI).date().isoformat()
    allowance = max(0, int(max_per_day) - int(shadow["attempts_by_day"].get(day, 0)))
    selected = candidates[: min(max(0, int(max_per_run)), allowance)]
    return {
        "baseline": False,
        "messages": [format_message(item) for item in selected],
        "pending": len(candidates) - len(selected),
    }


def build_parser():
    parser = argparse.ArgumentParser(description="DataHot important-event push adapter for OpenClaw")
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--max-age-hours", type=float, default=48)
    parser.add_argument("--max-per-run", type=int, default=3)
    parser.add_argument("--max-per-day", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    now = utc_now()
    try:
        state = load_state(args.state_file)
        payload, etag, not_modified = fetch_feed(
            args.feed_url,
            etag=None if args.dry_run else state.get("etag"),
        )
        if not_modified:
            print("NO_REPLY")
            return 0
        if args.dry_run:
            print(json.dumps(_dry_run(
                payload, state, now=now,
                max_age_hours=args.max_age_hours,
                max_per_run=args.max_per_run,
                max_per_day=args.max_per_day,
            ), ensure_ascii=False, indent=2))
            return 0

        config = load_sender_config(args.config)
        sender = openclaw_sender(config)

        result = process_payload(
            payload, state, now=now, etag=etag, sender=sender,
            persist=lambda value: save_state(args.state_file, value),
            max_age_hours=args.max_age_hours,
            max_per_run=args.max_per_run,
            max_per_day=args.max_per_day,
        )
        print(
            f"[datahot-push] baseline={result['baseline']} sent={len(result['sent'])} "
            f"failed={len(result['failed'])} pending={result['pending']}",
            file=sys.stderr,
        )
        print("NO_REPLY")
        return 1 if result["failed"] else 0
    except PushError as error:
        print(f"[datahot-push] {error}", file=sys.stderr)
        print("NO_REPLY")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
