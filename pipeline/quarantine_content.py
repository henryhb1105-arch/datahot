#!/usr/bin/env python3
"""Quarantine newly ingested events with stored page chrome before site generation."""

import argparse
import json
import sys
from pathlib import Path

from release_guard import (
    ReleaseGuardError,
    load_payload,
    quarantine_new_stored_chrome,
)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--report", required=True)
    return parser


def write_json_atomic(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def main(argv=None):
    args = build_parser().parse_args(argv)
    candidate_path = Path(args.candidate)
    try:
        candidate_payload = load_payload(candidate_path)
        cleaned_payload, quarantined = quarantine_new_stored_chrome(
            load_payload(args.baseline), candidate_payload,
        )
        if quarantined:
            write_json_atomic(candidate_path, cleaned_payload)
        report = {
            "schema_version": 1,
            "candidate_event_count_before": len(candidate_payload.get("events", [])),
            "candidate_event_count_after": len(cleaned_payload.get("events", [])),
            "quarantined": quarantined,
        }
        write_json_atomic(args.report, report)
    except (OSError, json.JSONDecodeError, ReleaseGuardError) as error:
        print(f"content quarantine blocked: {error}", file=sys.stderr)
        return 1

    if quarantined:
        for item in quarantined:
            print(
                f"[quarantine] {item['event_id']} | {item['title']} | "
                f"{item['reason']} | {item['disposition']}"
            )
    else:
        print("[quarantine] no new stored page chrome")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
