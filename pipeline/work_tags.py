#!/usr/bin/env python3
"""Closed-vocabulary work-tag normalization, merging, and audit helpers."""

import argparse
import json
from collections import Counter
from pathlib import Path


TAXONOMY_PATH = Path(__file__).with_name("work_tags.json")
TAXONOMY = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
TAXONOMY_VERSION = str(TAXONOMY["version"])
DIMENSIONS = TAXONOMY["dimensions"]
DIMENSION_NAMES = tuple(DIMENSIONS)


def prompt_instructions():
    """Return the compact closed vocabulary appended to the existing enrich prompt."""
    rows = []
    for name, meta in DIMENSIONS.items():
        values = "/".join(meta["values"])
        rows.append(
            f'- {name}（{meta["label"]}，0-{int(meta["max_items"])}个）：{values}'
        )
    return "\n".join(rows)


def normalize_work_tags(raw):
    """Sanitize model output while retaining an explicit taxonomy version."""
    raw = raw if isinstance(raw, dict) else {}
    normalized = {"taxonomy_version": TAXONOMY_VERSION}
    for name, meta in DIMENSIONS.items():
        allowed = set(meta["values"])
        values = raw.get(name)
        values = values if isinstance(values, list) else []
        cleaned = []
        for value in values:
            if not isinstance(value, str):
                continue
            value = value.strip()
            if value in allowed and value not in cleaned:
                cleaned.append(value)
            if len(cleaned) >= int(meta["max_items"]):
                break
        normalized[name] = cleaned
    return normalized


def merge_work_tags(*tag_sets):
    """Merge work tags in source order; return None when no input was tagged."""
    present = [value for value in tag_sets if isinstance(value, dict)]
    if not present:
        return None
    combined = {}
    for name in DIMENSION_NAMES:
        combined[name] = [
            value
            for tag_set in present
            for value in (tag_set.get(name) if isinstance(tag_set.get(name), list) else [])
        ]
    return normalize_work_tags(combined)


def validation_errors(raw):
    """Describe persisted values that do not conform to the current taxonomy."""
    if not isinstance(raw, dict):
        return ["work_tags must be an object"]
    errors = []
    if raw.get("taxonomy_version") != TAXONOMY_VERSION:
        errors.append("taxonomy_version mismatch")
    for name, meta in DIMENSIONS.items():
        values = raw.get(name)
        if not isinstance(values, list):
            errors.append(f"{name} must be a list")
            continue
        allowed = set(meta["values"])
        invalid = [
            value for value in values
            if not isinstance(value, str) or value not in allowed
        ]
        if invalid:
            errors.append(f"{name} has invalid values: {invalid}")
        seen = []
        has_duplicates = False
        for value in values:
            if any(value == existing for existing in seen):
                has_duplicates = True
                break
            seen.append(value)
        if has_duplicates:
            errors.append(f"{name} has duplicate values")
        if len(values) > int(meta["max_items"]):
            errors.append(f"{name} exceeds max_items")
    return errors


def audit_events(events):
    """Build a deterministic coverage and validity report for an event collection."""
    events = list(events)
    processed = 0
    tagged = 0
    invalid = {}
    counts = {name: Counter() for name in DIMENSION_NAMES}
    for event in events:
        work_tags = event.get("work_tags")
        if not isinstance(work_tags, dict):
            continue
        processed += 1
        errors = validation_errors(work_tags)
        if errors:
            invalid[str(event.get("event_id") or "unknown")] = errors
        normalized = normalize_work_tags(work_tags)
        if any(normalized[name] for name in DIMENSION_NAMES):
            tagged += 1
        for name in DIMENSION_NAMES:
            counts[name].update(normalized[name])
    total = len(events)
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "events": total,
        "processed_events": processed,
        "tagged_events": tagged,
        "processed_coverage": round(processed / total, 4) if total else 0,
        "tagged_coverage": round(tagged / total, 4) if total else 0,
        "invalid_events": invalid,
        "counts": {name: dict(counter.most_common()) for name, counter in counts.items()},
    }


def main():
    parser = argparse.ArgumentParser(description="Audit DataHot work-tag coverage")
    parser.add_argument("payload", type=Path, help="latest.json or another event payload")
    args = parser.parse_args()
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    events = payload.get("events", []) if isinstance(payload, dict) else payload
    report = audit_events(events if isinstance(events, list) else [])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["invalid_events"] else 0)


if __name__ == "__main__":
    main()
