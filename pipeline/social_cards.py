#!/usr/bin/env python3
"""Select a safe first-party image for DataHot social previews."""

from __future__ import annotations

import re


_MEDIA_PATH_RE = re.compile(
    r"^media/(?P<event_id>[a-f0-9]{12})/(?P<filename>[a-f0-9]{12,64}\.(?:jpe?g|png|webp))$",
    re.I,
)


def _bounded_dimension(value):
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= 10_000 else None


def social_image_for_event(event, site_base):
    """Return bounded social-image metadata from an already cached figure."""
    event_id = str(event.get("event_id") or "")
    if not re.fullmatch(r"[a-f0-9]{12}", event_id):
        return None
    for block in event.get("content_blocks") or ():
        if not isinstance(block, dict) or block.get("type") != "figure":
            continue
        cached = str(block.get("cached_src") or "").strip().replace("\\", "/")
        while cached.startswith("../"):
            cached = cached[3:]
        match = _MEDIA_PATH_RE.fullmatch(cached)
        if not match or match.group("event_id") != event_id:
            continue
        return {
            "path": cached,
            "url": f"{str(site_base).rstrip('/')}/{cached}",
            "alt": str(block.get("alt") or block.get("caption") or event.get("zh_title") or "DataHot 文章配图")[:160],
            "width": _bounded_dimension(block.get("width")),
            "height": _bounded_dimension(block.get("height")),
        }
    return None
