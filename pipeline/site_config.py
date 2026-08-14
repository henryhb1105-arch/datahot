"""Canonical public URL configuration shared by DataHot site generators."""

from __future__ import annotations

import os
from urllib.parse import urlsplit


DEFAULT_SITE_BASE_URL = "https://datahot.xiahongbin.com"
LEGACY_SITE_BASE_URL = "https://henryhb1105-arch.github.io/datahot"


def resolve_site_base_url(value: str | None = None) -> str:
    """Return a normalized HTTPS origin and reject ambiguous deployment URLs."""
    candidate = (value if value is not None else os.getenv("SITE_BASE_URL", DEFAULT_SITE_BASE_URL)).strip()
    candidate = candidate.rstrip("/")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("SITE_BASE_URL must be an HTTPS origin without a path, query, or fragment")
    return f"https://{parsed.hostname.lower()}"


SITE_BASE_URL = resolve_site_base_url()
SITE_HOST = urlsplit(SITE_BASE_URL).hostname or "datahot.xiahongbin.com"
