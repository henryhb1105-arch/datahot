#!/usr/bin/env python3
"""Notify IndexNow about public DataHot URLs changed by a completed release."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from site_config import DEFAULT_SITE_BASE_URL, resolve_site_base_url


INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
INDEXNOW_USER_AGENT = "DataHotIndexNow/1.0"
# IndexNow requires this ownership proof to be published at the site root. It is
# intentionally public and is not an authentication credential.
INDEXNOW_KEY = "2b62bfcff58e09f05baedd2543396778"  # gitleaks:allow
INDEXNOW_KEY_RE = re.compile(r"[A-Za-z0-9-]{8,128}")
EVENT_ID_RE = re.compile(r"[a-f0-9]{12}")
MAX_URLS = 10_000
BOOTSTRAP_WINDOW_HOURS = 24
BOOTSTRAP_EVENT_LIMIT = 20
PUBLIC_LISTING_PATHS = ("", "hot.html", "cases.html", "topics.html")


def validate_key(key: str) -> str:
    value = str(key or "").strip()
    if not INDEXNOW_KEY_RE.fullmatch(value):
        raise ValueError("IndexNow key must contain 8-128 letters, numbers, or dashes")
    return value


def key_filename(key: str = INDEXNOW_KEY) -> str:
    return f"{validate_key(key)}.txt"


def write_key_file(site_root, key: str = INDEXNOW_KEY) -> Path:
    """Write the root ownership proof required by the IndexNow protocol."""
    site_root = Path(site_root)
    site_root.mkdir(parents=True, exist_ok=True)
    value = validate_key(key)
    target = site_root / key_filename(value)
    target.write_text(value, encoding="utf-8")
    if target.read_text(encoding="utf-8") != value:
        raise RuntimeError("IndexNow key file verification failed")
    return target


def load_payload(path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError(f"invalid latest payload: {path}")
    return payload


def _events_by_id(payload: dict) -> dict[str, dict]:
    events = {}
    for event in payload.get("events") or ():
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id") or "")
        if EVENT_ID_RE.fullmatch(event_id):
            events[event_id] = event
    return events


def _parse_timestamp(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bootstrap_event_ids(candidate: dict, *, now: datetime) -> set[str]:
    """Return only freshly discovered URLs when IndexNow is first enabled."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=BOOTSTRAP_WINDOW_HOURS)
    event_ids = []
    for event in candidate.get("events") or ():
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id") or "")
        first_seen = _parse_timestamp(event.get("first_seen"))
        if EVENT_ID_RE.fullmatch(event_id) and first_seen and first_seen >= cutoff:
            event_ids.append(event_id)
            if len(event_ids) >= BOOTSTRAP_EVENT_LIMIT:
                break
    return set(event_ids)


def _public_url(path: str, site_base: str) -> str:
    base = resolve_site_base_url(site_base)
    value = str(path or "").strip().lstrip("/")
    if value and (
        ".." in Path(value).parts
        or "?" in value
        or "#" in value
        or not value.endswith(".html")
    ):
        raise ValueError(f"invalid IndexNow public path: {path!r}")
    return f"{base}/{value}" if value else f"{base}/"


def validate_urls(urls, *, site_base: str) -> tuple[str, ...]:
    base = urlsplit(resolve_site_base_url(site_base))
    normalized = []
    for value in urls:
        parsed = urlsplit(str(value or "").strip())
        if (
            parsed.scheme != "https"
            or parsed.netloc != base.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"foreign or noncanonical IndexNow URL: {value!r}")
        normalized.append(parsed.geturl())
    unique = tuple(sorted(set(normalized)))
    if len(unique) > MAX_URLS:
        raise ValueError(f"IndexNow batch exceeds {MAX_URLS} URLs")
    return unique


def changed_public_urls(
    baseline: dict,
    candidate: dict,
    *,
    site_root,
    site_base: str = DEFAULT_SITE_BASE_URL,
    bootstrap: bool = False,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Return canonical URLs whose public output changed in this release."""
    baseline_events = _events_by_id(baseline)
    candidate_events = _events_by_id(candidate)
    changed_ids = {
        event_id
        for event_id in baseline_events.keys() | candidate_events.keys()
        if baseline_events.get(event_id) != candidate_events.get(event_id)
    }
    if bootstrap:
        changed_ids.update(_bootstrap_event_ids(
            candidate,
            now=now or datetime.now(timezone.utc),
        ))

    paths = {f"e/{event_id}.html" for event_id in changed_ids}
    listings_changed = bool(changed_ids) or baseline.get("top") != candidate.get("top")
    sources_changed = baseline.get("sources") != candidate.get("sources")
    if listings_changed:
        paths.update(PUBLIC_LISTING_PATHS)
        topics_dir = Path(site_root) / "topics"
        if topics_dir.is_dir():
            paths.update(f"topics/{path.name}" for path in topics_dir.glob("*.html"))
    if listings_changed or sources_changed:
        paths.add("sources.html")

    return validate_urls(
        (_public_url(path, site_base) for path in paths),
        site_base=site_base,
    )


def _read_url(request_or_url, *, opener=urlopen, timeout=20):
    with opener(request_or_url, timeout=timeout) as response:
        return response.status, response.read()


def wait_until_release_live(
    expected_source_sha: str,
    *,
    site_base: str = DEFAULT_SITE_BASE_URL,
    key: str = INDEXNOW_KEY,
    attempts: int = 24,
    delay: float = 10,
    opener=urlopen,
):
    """Wait for the release manifest and ownership key on the public origin."""
    if not re.fullmatch(r"[a-f0-9]{40}", str(expected_source_sha or "")):
        raise ValueError("expected_source_sha must be a full git SHA")
    base = resolve_site_base_url(site_base)
    key = validate_key(key)
    last_error = None
    for attempt in range(attempts):
        nonce = urlencode({"indexnow_release": expected_source_sha[:12], "attempt": attempt})
        try:
            status, body = _read_url(
                Request(f"{base}/data/release.json?{nonce}", headers={
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "User-Agent": INDEXNOW_USER_AGENT,
                }),
                opener=opener,
            )
            manifest = json.loads(body.decode("utf-8")) if status == 200 else {}
            if manifest.get("source_sha") != expected_source_sha:
                raise RuntimeError("release manifest has not reached the expected source SHA")
            key_status, key_body = _read_url(
                Request(f"{base}/{key_filename(key)}?{nonce}", headers={
                    "Accept": "text/plain",
                    "Cache-Control": "no-cache",
                    "User-Agent": INDEXNOW_USER_AGENT,
                }),
                opener=opener,
            )
            if key_status != 200 or key_body.decode("utf-8").strip() != key:
                raise RuntimeError("IndexNow ownership key is not live")
            return
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as error:
            last_error = error
        if attempt + 1 < attempts:
            time.sleep(delay)
    detail = f"{type(last_error).__name__}: {last_error}" if last_error else "unknown error"
    raise RuntimeError(f"published release or IndexNow key did not become live: {detail}") from last_error


def submit_urls(
    urls,
    *,
    site_base: str = DEFAULT_SITE_BASE_URL,
    key: str = INDEXNOW_KEY,
    endpoint: str = INDEXNOW_ENDPOINT,
    opener=urlopen,
) -> dict:
    urls = validate_urls(urls, site_base=site_base)
    if not urls:
        return {"status": "skipped", "reason": "no_changed_urls", "url_count": 0}
    base = resolve_site_base_url(site_base)
    key = validate_key(key)
    payload = {
        "host": urlsplit(base).netloc,
        "key": key,
        "keyLocation": f"{base}/{key_filename(key)}",
        "urlList": list(urls),
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": INDEXNOW_USER_AGENT,
        },
        method="POST",
    )
    status, _ = _read_url(request, opener=opener)
    if status not in {200, 202}:
        raise RuntimeError(f"IndexNow returned HTTP {status}")
    return {
        "status": "submitted" if status == 200 else "accepted_pending_key_validation",
        "http_status": status,
        "url_count": len(urls),
        "urls": list(urls),
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-latest", required=True)
    parser.add_argument("--candidate-latest", required=True)
    parser.add_argument("--site-root", required=True)
    parser.add_argument("--site-base", default=DEFAULT_SITE_BASE_URL)
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wait-attempts", type=int, default=24)
    parser.add_argument("--wait-delay", type=float, default=10)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        baseline = load_payload(args.baseline_latest)
        candidate = load_payload(args.candidate_latest)
        urls = changed_public_urls(
            baseline,
            candidate,
            site_root=args.site_root,
            site_base=args.site_base,
            bootstrap=args.bootstrap,
        )
        if args.dry_run or not urls:
            result = {
                "status": "dry_run" if args.dry_run else "skipped",
                "reason": "no_changed_urls" if not urls else None,
                "url_count": len(urls),
                "urls": list(urls),
            }
        else:
            wait_until_release_live(
                args.expected_source_sha,
                site_base=args.site_base,
                attempts=args.wait_attempts,
                delay=args.wait_delay,
            )
            result = submit_urls(urls, site_base=args.site_base)
    except (OSError, ValueError, RuntimeError, HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
