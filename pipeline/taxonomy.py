#!/usr/bin/env python3
"""Canonical DataHot category taxonomy shared by every pipeline surface."""

from __future__ import annotations


CATEGORY_LABELS = {
    "agent": "Data Agent",
    "platform": "AI 数据平台",
    "bi": "BI 与可视化",
    "product": "数据产品",
    "insight": "AI分析",
}


def category_label(category: str, fallback: str = "") -> str:
    """Return the single public label for a stable category value."""
    key = str(category or "")
    return CATEGORY_LABELS.get(key, fallback or key)


def normalize_category_label(record: dict) -> bool:
    """Rewrite a record's cached display label from its stable category value."""
    label = CATEGORY_LABELS.get(str(record.get("category") or ""))
    if not label or record.get("category_label") == label:
        return False
    record["category_label"] = label
    return True


def normalize_category_labels(records) -> int:
    """Normalize a sequence in place and return the number of changed records."""
    return sum(1 for record in records if normalize_category_label(record))
