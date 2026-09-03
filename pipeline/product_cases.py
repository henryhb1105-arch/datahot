#!/usr/bin/env python3
"""Load and validate the editorially curated product-design case manifest."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path


PRODUCT_CASES_PATH = Path(__file__).with_name("product_cases.json")
SCHEMA_VERSION = "product-cases-v1"
MIN_CASES = 8
MAX_CASES = 12
PRODUCT_TYPES = frozenset({"Data Agent", "数据平台", "BI/数据应用"})
TASK_TYPES = frozenset({"找数据", "问数据", "做分析", "看结果", "管任务", "做治理"})
REQUIRED_FIELDS = frozenset({
    "event_id",
    "product",
    "product_type",
    "task_type",
    "hero_figure_id",
    "user_problem",
    "modules",
    "interactions",
    "official_facts",
    "datahot_interpretation",
    "tradeoffs",
    "takeaways",
    "limitations",
    "observed_at",
})
LIST_FIELDS = (
    "modules",
    "interactions",
    "official_facts",
    "datahot_interpretation",
    "tradeoffs",
    "takeaways",
    "limitations",
)
EVENT_ID_RE = re.compile(r"^[0-9a-f]{12}$")
FIGURE_ID_RE = re.compile(r"^b-[0-9a-f]{12}$")


def _event_index(events):
    if isinstance(events, dict):
        events = events.get("events", [])
    if not isinstance(events, (list, tuple)):
        return {}
    return {
        str(event.get("event_id") or ""): event
        for event in events
        if isinstance(event, dict) and event.get("event_id")
    }


def find_case_hero(event, case):
    """Return the cached figure referenced by a case, or ``None``.

    ``hero_figure_id`` intentionally points at the existing content-block ``id``;
    the manifest never duplicates a mutable media path.
    """
    if not isinstance(event, dict) or not isinstance(case, dict):
        return None
    figure_id = str(case.get("hero_figure_id") or "")
    for block in event.get("content_blocks") or []:
        if not isinstance(block, dict):
            continue
        if (
            block.get("type") == "figure"
            and block.get("id") == figure_id
            and isinstance(block.get("cached_src"), str)
            and block["cached_src"].strip()
        ):
            return block
    return None


def validation_errors(payload, events=None):
    """Return deterministic validation errors for a product-case payload."""
    if not isinstance(payload, dict):
        return ["payload must be an object"]

    errors = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        errors.append("cases must be a list")
        return errors
    if not MIN_CASES <= len(cases) <= MAX_CASES:
        errors.append(f"cases must contain {MIN_CASES}-{MAX_CASES} items")

    event_index = _event_index(events) if events is not None else None
    seen_event_ids = set()
    product_types = set()
    task_types = set()

    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = sorted(REQUIRED_FIELDS - set(case))
        extra = sorted(set(case) - REQUIRED_FIELDS)
        if missing:
            errors.append(f"{prefix} missing fields: {', '.join(missing)}")
        if extra:
            errors.append(f"{prefix} has unsupported fields: {', '.join(extra)}")

        event_id = case.get("event_id")
        if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
            errors.append(f"{prefix}.event_id must be a 12-character lowercase hex id")
        elif event_id in seen_event_ids:
            errors.append(f"{prefix}.event_id is duplicated: {event_id}")
        else:
            seen_event_ids.add(event_id)

        for field in ("product", "user_problem"):
            value = case.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")

        product_type = case.get("product_type")
        if product_type not in PRODUCT_TYPES:
            errors.append(f"{prefix}.product_type is not in the closed vocabulary")
        else:
            product_types.add(product_type)
        task_type = case.get("task_type")
        if task_type not in TASK_TYPES:
            errors.append(f"{prefix}.task_type is not in the closed vocabulary")
        else:
            task_types.add(task_type)

        figure_id = case.get("hero_figure_id")
        if not isinstance(figure_id, str) or not FIGURE_ID_RE.fullmatch(figure_id):
            errors.append(f"{prefix}.hero_figure_id must reference a figure block id")

        for field in LIST_FIELDS:
            values = case.get(field)
            if not isinstance(values, list) or not values:
                errors.append(f"{prefix}.{field} must be a non-empty list")
                continue
            if any(not isinstance(value, str) or not value.strip() for value in values):
                errors.append(f"{prefix}.{field} must contain non-empty strings")
            if len(values) != len(set(values)):
                errors.append(f"{prefix}.{field} must not contain duplicates")

        official = case.get("official_facts") or []
        interpretation = case.get("datahot_interpretation") or []
        if isinstance(official, list) and isinstance(interpretation, list):
            overlap = set(official) & set(interpretation)
            if overlap:
                errors.append(
                    f"{prefix} must keep official_facts and "
                    "datahot_interpretation separate"
                )
            if any(
                isinstance(value, str) and value.lstrip().startswith("DataHot解读")
                for value in official
            ):
                errors.append(f"{prefix}.official_facts contains interpretation copy")
            if any(
                isinstance(value, str) and value.lstrip().startswith("官方说明")
                for value in interpretation
            ):
                errors.append(
                    f"{prefix}.datahot_interpretation contains official-fact copy"
                )

        observed_at = case.get("observed_at")
        try:
            date.fromisoformat(observed_at)
        except (TypeError, ValueError):
            errors.append(f"{prefix}.observed_at must be an ISO date")

        if event_index is not None and isinstance(event_id, str):
            event = event_index.get(event_id)
            if event is None:
                errors.append(f"{prefix}.event_id is absent from the event payload")
            else:
                hero = find_case_hero(event, case)
                if hero is None:
                    errors.append(
                        f"{prefix}.hero_figure_id does not resolve to a cached figure"
                    )
                else:
                    cached_src = hero["cached_src"].strip()
                    expected_prefix = f"../media/{event_id}/"
                    if not cached_src.startswith(expected_prefix):
                        errors.append(
                            f"{prefix}.hero_figure_id uses an unsafe cached media path"
                        )

    if cases and not PRODUCT_TYPES.issubset(product_types):
        missing_types = sorted(PRODUCT_TYPES - product_types)
        errors.append(f"cases do not cover product types: {', '.join(missing_types)}")
    if cases and len(task_types) < 4:
        errors.append("cases must cover at least four task types")
    return errors


def load_product_cases(path=PRODUCT_CASES_PATH, events=None):
    """Load validated cases; a missing manifest is an empty optional feature."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read product cases from {path}: {exc}") from exc
    errors = validation_errors(payload, events=events)
    if errors:
        detail = "\n- ".join(errors)
        raise ValueError(f"invalid product case manifest:\n- {detail}")
    return [dict(case) for case in payload["cases"]]


def product_case_event_ids(path=PRODUCT_CASES_PATH):
    """Return selected event ids for release-retention and indexing rules."""
    return frozenset(case["event_id"] for case in load_product_cases(path))

