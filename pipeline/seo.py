"""Search discovery assets for the generated DataHot site."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
PUBLIC_ROOT_PAGES = (
    "",
    "hot.html",
    "cases.html",
    "topics.html",
    "sources.html",
    "weekly.html",
    "agent.html",
)


def _normalize_path(value: str) -> str:
    path = str(value or "").strip().lstrip("/")
    if path in {"", "index.html"}:
        return ""
    parsed = urlsplit(path)
    pure = PurePosixPath(parsed.path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or pure.is_absolute()
        or ".." in pure.parts
        or not parsed.path.endswith(".html")
    ):
        raise ValueError(f"invalid public sitemap path: {value!r}")
    return pure.as_posix()


def absolute_public_url(path: str, site_base: str) -> str:
    """Return one canonical public URL on the configured HTTPS origin."""
    base = site_base.rstrip("/")
    parsed_base = urlsplit(base)
    if parsed_base.scheme != "https" or not parsed_base.hostname:
        raise ValueError("site_base must be an HTTPS origin")
    normalized = _normalize_path(path)
    return f"{base}/{normalized}" if normalized else f"{base}/"


def public_sitemap_paths(
    detail_names=(), topic_names=(), weekly_names=(), *, weekly_enabled=True,
):
    """Build the canonical allowlist from pages emitted in the current build."""
    paths = list(PUBLIC_ROOT_PAGES)
    if not weekly_enabled:
        paths.remove("weekly.html")
    paths.extend(f"e/{Path(name).name}" for name in detail_names)
    paths.extend(f"topics/{Path(name).name}" for name in topic_names)
    if weekly_enabled:
        paths.extend(f"weekly/{Path(name).name}" for name in weekly_names)
    return tuple(sorted({_normalize_path(path) for path in paths}, key=lambda value: (value != "", value)))


def _normalize_lastmod(value: str) -> str:
    candidate = str(value or "").strip()
    try:
        parsed = date.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"invalid sitemap lastmod: {value!r}") from exc
    if parsed.isoformat() != candidate:
        raise ValueError(f"invalid sitemap lastmod: {value!r}")
    return candidate


def build_sitemap(paths, site_base: str, *, lastmod_by_path=None) -> bytes:
    """Build a deterministic Sitemap Protocol document containing canonical URLs."""
    ET.register_namespace("", SITEMAP_NAMESPACE)
    root = ET.Element(f"{{{SITEMAP_NAMESPACE}}}urlset")
    normalized_lastmod = {
        _normalize_path(path): _normalize_lastmod(value)
        for path, value in (lastmod_by_path or {}).items()
    }
    normalized_paths = sorted(
        {_normalize_path(path) for path in paths}, key=lambda value: (value != "", value),
    )
    if len(normalized_paths) > 50_000:
        raise ValueError("a sitemap cannot contain more than 50,000 URLs")
    for path in normalized_paths:
        url = ET.SubElement(root, f"{{{SITEMAP_NAMESPACE}}}url")
        ET.SubElement(url, f"{{{SITEMAP_NAMESPACE}}}loc").text = absolute_public_url(path, site_base)
        if path in normalized_lastmod:
            ET.SubElement(url, f"{{{SITEMAP_NAMESPACE}}}lastmod").text = normalized_lastmod[path]
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8") + b"\n"


def validate_sitemap(payload: bytes, *, site_base: str, site_root=None):
    """Return stable validation errors for malformed, foreign, duplicate or missing URLs."""
    errors = []
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return ["invalid_xml"]
    if root.tag != f"{{{SITEMAP_NAMESPACE}}}urlset":
        return ["invalid_root"]

    expected_origin = urlsplit(site_base.rstrip("/"))
    seen = set()
    locations = root.findall(f"{{{SITEMAP_NAMESPACE}}}url/{{{SITEMAP_NAMESPACE}}}loc")
    if len(locations) > 50_000:
        errors.append("too_many_urls")
    for element in locations:
        location = (element.text or "").strip()
        if not location:
            errors.append("empty_loc")
            continue
        parsed = urlsplit(location)
        if (
            parsed.scheme != "https"
            or parsed.netloc != expected_origin.netloc
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            errors.append(f"foreign_or_noncanonical:{location}")
            continue
        if location in seen:
            errors.append(f"duplicate:{location}")
        seen.add(location)
        if site_root is not None:
            relative = parsed.path.lstrip("/")
            target = Path(site_root) / (relative or "index.html")
            if not target.is_file():
                errors.append(f"missing:{location}")
    for url in root.findall(f"{{{SITEMAP_NAMESPACE}}}url"):
        lastmods = url.findall(f"{{{SITEMAP_NAMESPACE}}}lastmod")
        if len(lastmods) > 1:
            errors.append("duplicate_lastmod")
            continue
        if lastmods:
            try:
                _normalize_lastmod(lastmods[0].text or "")
            except ValueError:
                errors.append(f"invalid_lastmod:{lastmods[0].text or ''}")
    return errors


def robots_text(site_base: str) -> str:
    root_url = absolute_public_url("", site_base)
    return (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {root_url}sitemap.xml\n"
    )


def write_search_discovery(site_root, paths, *, site_base: str, lastmod_by_path=None):
    """Write and validate sitemap.xml plus the root robots.txt discovery pointer."""
    site_root = Path(site_root)
    sitemap = build_sitemap(paths, site_base, lastmod_by_path=lastmod_by_path)
    errors = validate_sitemap(sitemap, site_base=site_base, site_root=site_root)
    if errors:
        raise RuntimeError(f"invalid sitemap: {', '.join(errors[:10])}")
    (site_root / "sitemap.xml").write_bytes(sitemap)
    (site_root / "robots.txt").write_text(robots_text(site_base), encoding="utf-8")
    return len(ET.fromstring(sitemap).findall(f"{{{SITEMAP_NAMESPACE}}}url"))
