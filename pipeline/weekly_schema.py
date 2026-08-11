#!/usr/bin/env python3
"""Small dependency-free JSON Schema validator for weekly AI responses."""

from __future__ import annotations

import re


EVENT_ID_PATTERN = r"^[0-9a-f]{12}$"
SIGNAL_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{2,47}$"
CHANGE_TYPES = (
    "early_signal", "new", "strengthening", "continuing", "cooling", "unknown",
)
CONFIDENCE_LEVELS = ("high", "medium", "low")
PRIORITIES = ("现在行动", "安排测试", "继续观察", "暂时忽略")


SIGNAL_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "signal_id", "title", "change_type", "confidence", "confidence_reason",
        "anchor", "mechanism", "baseline_comparison", "evidence_ids",
        "counter_evidence",
    ],
    "properties": {
        "signal_id": {"type": "string", "pattern": SIGNAL_ID_PATTERN},
        "title": {"type": "string", "minLength": 4, "maxLength": 32},
        "change_type": {"type": "string", "enum": list(CHANGE_TYPES)},
        "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
        "confidence_reason": {"type": "string", "minLength": 12, "maxLength": 240},
        "anchor": {"type": "string", "minLength": 12, "maxLength": 220},
        "mechanism": {"type": "string", "minLength": 16, "maxLength": 320},
        "baseline_comparison": {"type": "string", "minLength": 12, "maxLength": 240},
        "evidence_ids": {
            "type": "array", "minItems": 1, "maxItems": 6, "uniqueItems": True,
            "items": {"type": "string", "pattern": EVENT_ID_PATTERN},
        },
        "counter_evidence": {"type": "string", "minLength": 8, "maxLength": 240},
    },
}


NOT_PROMOTED_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label", "reason", "evidence_ids"],
    "properties": {
        "label": {"type": "string", "minLength": 2, "maxLength": 40},
        "reason": {"type": "string", "minLength": 8, "maxLength": 240},
        "evidence_ids": {
            "type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True,
            "items": {"type": "string", "pattern": EVENT_ID_PATTERN},
        },
    },
}


SIGNAL_RESPONSE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "weekly_judgement", "signals", "signals_not_promoted", "uncertainty",
        "next_week_question",
    ],
    "properties": {
        "weekly_judgement": {"type": "string", "minLength": 12, "maxLength": 180},
        "signals": {
            "type": "array", "minItems": 0, "maxItems": 3,
            "items": SIGNAL_ITEM_SCHEMA,
        },
        "signals_not_promoted": {
            "type": "array", "minItems": 0, "maxItems": 4,
            "items": NOT_PROMOTED_ITEM_SCHEMA,
        },
        "uncertainty": {"type": "string", "minLength": 8, "maxLength": 260},
        "next_week_question": {"type": "string", "minLength": 8, "maxLength": 180},
    },
}


PERSONAL_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["signal_id", "priority", "insight", "why_it_matters", "action"],
    "properties": {
        "signal_id": {"type": "string", "pattern": SIGNAL_ID_PATTERN},
        "priority": {"type": "string", "enum": list(PRIORITIES)},
        "insight": {"type": "string", "minLength": 20, "maxLength": 280},
        "why_it_matters": {"type": "string", "minLength": 16, "maxLength": 260},
        "action": {"type": "string", "minLength": 6, "maxLength": 240},
    },
}


EVIDENCE_INDEX_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["event_id", "title"],
    "properties": {
        "event_id": {"type": "string", "pattern": EVENT_ID_PATTERN},
        "title": {"type": "string", "minLength": 1, "maxLength": 180},
    },
}


PERSONAL_RESPONSE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title", "bottom_line", "for_you", "what_not_to_overread", "uncertainty",
        "next_week_question", "evidence_index",
    ],
    "properties": {
        "title": {"type": "string", "minLength": 4, "maxLength": 24},
        "bottom_line": {"type": "string", "minLength": 16, "maxLength": 80},
        "for_you": {
            "type": "array", "minItems": 0, "maxItems": 3,
            "items": PERSONAL_ITEM_SCHEMA,
        },
        "what_not_to_overread": {"type": "string", "minLength": 8, "maxLength": 260},
        "uncertainty": {"type": "string", "minLength": 8, "maxLength": 260},
        "next_week_question": {"type": "string", "minLength": 8, "maxLength": 180},
        "evidence_index": {
            "type": "array", "minItems": 0, "maxItems": 18, "uniqueItems": True,
            "items": EVIDENCE_INDEX_ITEM_SCHEMA,
        },
    },
}


def _matches_type(value, expected):
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def validate_json_schema(value, schema, path="$", *, errors=None):
    """Validate the JSON Schema subset used by the weekly pipeline."""
    errors = [] if errors is None else errors
    expected = schema.get("type")
    if expected and not _matches_type(value, expected):
        errors.append(f"{path}: expected {expected}")
        return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in enum")

    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(
                f"{path}: string is too short "
                f"({len(value)}<{int(schema.get('minLength', 0))})"
            )
        maximum = schema.get("maxLength")
        if maximum is not None and len(value) > int(maximum):
            errors.append(f"{path}: string is too long ({len(value)}>{int(maximum)})")
        pattern = schema.get("pattern")
        if pattern and not re.fullmatch(pattern, value):
            errors.append(f"{path}: string does not match pattern")

    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            errors.append(f"{path}: array has too few items")
        maximum = schema.get("maxItems")
        if maximum is not None and len(value) > int(maximum):
            errors.append(f"{path}: array has too many items")
        if schema.get("uniqueItems"):
            seen = set()
            for item in value:
                marker = repr(item)
                if marker in seen:
                    errors.append(f"{path}: array items must be unique")
                    break
                seen.add(marker)
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_json_schema(item, item_schema, f"{path}[{index}]", errors=errors)

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}.{name}: required property is missing")
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    errors.append(f"{path}.{name}: additional property is not allowed")
        for name, child_schema in properties.items():
            if name in value:
                validate_json_schema(
                    value[name], child_schema, f"{path}.{name}", errors=errors,
                )
    return errors
