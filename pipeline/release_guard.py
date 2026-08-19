#!/usr/bin/env python3
"""Block regressive Pages releases and emit a machine-readable release manifest."""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_blocks import blocks_plain_text, sanitize_blocks, trim_article_blocks


PROTECTED_EVENT_IDS = {"65c35101abc1", "dfb9071b69e0"}
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DETAIL_PATH_RE = re.compile(r"(?:^|/)e/([A-Za-z0-9_-]+)\.html$")
ISSUE_RE = re.compile(r"#\d+")


class ReleaseGuardError(ValueError):
    pass


def load_payload(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ReleaseGuardError(f"invalid latest payload: {path}")
    return payload


def event_map(payload):
    mapped = {}
    for event in payload.get("events", []):
        event_id = str(event.get("event_id") or "")
        if not EVENT_ID_RE.fullmatch(event_id):
            raise ReleaseGuardError(f"invalid event_id: {event_id!r}")
        if event_id in mapped:
            raise ReleaseGuardError(f"duplicate event_id: {event_id}")
        mapped[event_id] = event
    return mapped


def parse_time(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def recent_ids(events, *, now, days):
    cutoff = now - timedelta(days=days)
    result = set()
    for event_id, event in events.items():
        observed = parse_time(event.get("first_seen")) or parse_time(event.get("published"))
        if observed and observed >= cutoff:
            result.add(event_id)
    return result


def expected_expired_ids(events, *, now, days):
    """News older than the retention window may disappear without an override."""
    return {
        event_id
        for event_id, event in events.items()
        if event_id not in recent_ids(events, now=now, days=days)
        and event.get("shelf") != "evergreen"
    } - PROTECTED_EVENT_IDS


def load_detail_ids(path):
    ids = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = DETAIL_PATH_RE.search(line.strip())
        if match:
            ids.add(match.group(1))
    return ids


def candidate_detail_ids(site_root):
    detail_root = Path(site_root) / "e"
    return {path.stem for path in detail_root.glob("*.html") if EVENT_ID_RE.fullmatch(path.stem)}


def load_manifest(path):
    manifest_path = Path(path) if path else None
    if not manifest_path or not manifest_path.is_file():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def content_quality_snapshot(events):
    """Return reader-visible structured-content invariants for a release candidate."""
    structured_ids = set()
    renderable_ids = set()
    suspect_ids = set()
    stored_chrome_ids = set()
    for event_id, event in events.items():
        source_url = ((event.get("items") or [{}])[0].get("link", "") if event.get("items") else "")
        blocks = sanitize_blocks(event.get("content_blocks", []), source_url)
        if not blocks:
            continue
        structured_ids.add(event_id)
        trimmed, quality = trim_article_blocks(blocks)
        if len(trimmed) != len(blocks):
            stored_chrome_ids.add(event_id)
        if len(blocks_plain_text(trimmed)) >= 120:
            renderable_ids.add(event_id)
        if quality.get("quality_status") != "pass":
            suspect_ids.add(event_id)
    return {
        "structured_ids": structured_ids,
        "renderable_ids": renderable_ids,
        "suspect_ids": suspect_ids,
        "stored_chrome_ids": stored_chrome_ids,
    }


def content_quality_counts(snapshot):
    return {
        "structured": len(snapshot["structured_ids"]),
        "renderable": len(snapshot["renderable_ids"]),
        "suspect": len(snapshot["suspect_ids"]),
        "stored_chrome": len(snapshot["stored_chrome_ids"]),
    }


def assess_release(
    baseline_payload,
    candidate_payload,
    baseline_details,
    candidate_details,
    *,
    source_sha,
    run_id,
    issue,
    baseline_manifest=None,
    allow_shrink=False,
    recent_days=8,
    now=None,
):
    now = now or datetime.now(timezone.utc)
    baseline_events = event_map(baseline_payload)
    candidate_events = event_map(candidate_payload)
    baseline_details = set(baseline_details)
    candidate_details = set(candidate_details)
    baseline_quality = content_quality_snapshot(baseline_events)
    candidate_quality = content_quality_snapshot(candidate_events)

    missing_candidate_pages = set(candidate_events) - candidate_details
    if missing_candidate_pages:
        sample = ", ".join(sorted(missing_candidate_pages)[:10])
        raise ReleaseGuardError(f"candidate detail pages missing: {sample}")

    baseline_recent = recent_ids(baseline_events, now=now, days=recent_days)
    candidate_recent = recent_ids(candidate_events, now=now, days=recent_days)
    allowed_expired = expected_expired_ids(baseline_events, now=now, days=recent_days)
    expired_events_removed = allowed_expired - set(candidate_events)
    event_floor = len(baseline_events) - len(expired_events_removed)

    violations = []
    if len(candidate_events) < event_floor:
        violations.append({
            "code": "event_count_decreased",
            "message": (
                f"events {len(baseline_events)} -> {len(candidate_events)} "
                f"below retention floor {event_floor}"
            ),
        })

    missing_recent = baseline_recent - set(candidate_events)
    if missing_recent:
        violations.append({
            "code": "recent_events_missing",
            "message": f"{len(missing_recent)} recent event(s) missing",
            "event_ids": sorted(missing_recent),
        })

    expired_details_removed = (allowed_expired & baseline_details) - candidate_details
    detail_floor = len(baseline_details) - len(expired_details_removed)
    if len(candidate_details) < detail_floor:
        violations.append({
            "code": "detail_count_decreased",
            "message": (
                f"details {len(baseline_details)} -> {len(candidate_details)} "
                f"below retention floor {detail_floor}"
            ),
        })

    missing_protected = PROTECTED_EVENT_IDS - set(candidate_events)
    if missing_protected:
        violations.append({
            "code": "protected_events_missing",
            "message": "protected public event(s) missing",
            "event_ids": sorted(missing_protected),
        })

    lost_structured = (
        baseline_quality["structured_ids"] & set(candidate_events)
    ) - candidate_quality["structured_ids"]
    if lost_structured:
        violations.append({
            "code": "structured_content_lost",
            "message": f"{len(lost_structured)} existing structured article(s) lost blocks",
            "event_ids": sorted(lost_structured),
        })

    became_unrenderable = (
        baseline_quality["renderable_ids"] & set(candidate_events)
    ) - candidate_quality["renderable_ids"]
    if became_unrenderable:
        violations.append({
            "code": "structured_content_unrenderable",
            "message": f"{len(became_unrenderable)} structured article(s) became unrenderable",
            "event_ids": sorted(became_unrenderable),
        })

    new_suspect = candidate_quality["suspect_ids"] - baseline_quality["suspect_ids"]
    if new_suspect:
        violations.append({
            "code": "structured_content_suspect",
            "message": f"{len(new_suspect)} new suspect structured article(s)",
            "event_ids": sorted(new_suspect),
        })

    stored_chrome = candidate_quality["stored_chrome_ids"]
    if stored_chrome:
        violations.append({
            "code": "stored_article_chrome",
            "message": f"{len(stored_chrome)} structured article(s) still contain page chrome",
            "event_ids": sorted(stored_chrome),
        })

    if violations and not allow_shrink:
        raise ReleaseGuardError("; ".join(item["message"] for item in violations))
    if violations and (not issue or not ISSUE_RE.search(issue)):
        raise ReleaseGuardError("shrink override requires an explicit #Issue reference")

    baseline_manifest = baseline_manifest or {}
    should_publish = baseline_manifest.get("source_sha") != source_sha
    manifest = {
        "schema_version": 1,
        "source_sha": source_sha,
        "run_id": str(run_id),
        "issue": issue or "automatic",
        "generated_at": now.isoformat(),
        "event_count": len(candidate_events),
        "recent_event_count": len(candidate_recent),
        "detail_count": len(candidate_details),
        "recent_window_days": int(recent_days),
        "content_quality": content_quality_counts(candidate_quality),
        "allow_shrink": bool(allow_shrink),
        "overrides": violations,
        "baseline": {
            "source_sha": baseline_manifest.get("source_sha", ""),
            "event_count": len(baseline_events),
            "recent_event_count": len(baseline_recent),
            "detail_count": len(baseline_details),
            "allowed_expired_count": len(allowed_expired),
            "expired_removed_count": len(expired_events_removed),
            "content_quality": content_quality_counts(baseline_quality),
        },
        "should_publish": should_publish,
    }
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-latest", required=True)
    parser.add_argument("--baseline-details", required=True)
    parser.add_argument("--baseline-manifest")
    parser.add_argument("--candidate-site", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--issue", default="automatic")
    parser.add_argument("--recent-days", type=int, default=8)
    parser.add_argument("--allow-shrink", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--github-output")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        candidate_site = Path(args.candidate_site)
        manifest = assess_release(
            load_payload(args.baseline_latest),
            load_payload(candidate_site / "data" / "latest.json"),
            load_detail_ids(args.baseline_details),
            candidate_detail_ids(candidate_site),
            source_sha=args.source_sha,
            run_id=args.run_id,
            issue=args.issue,
            baseline_manifest=load_manifest(args.baseline_manifest),
            allow_shrink=args.allow_shrink,
            recent_days=args.recent_days,
        )
    except (OSError, json.JSONDecodeError, ReleaseGuardError) as error:
        print(f"release guard blocked: {error}", file=sys.stderr)
        return 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"should_publish={'true' if manifest['should_publish'] else 'false'}\n")
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
