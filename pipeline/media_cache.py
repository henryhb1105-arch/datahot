#!/usr/bin/env python3
"""Bounded, auditable media cache for safe article figure blocks."""

from __future__ import annotations

import hashlib
import io
import ipaddress
import os
import re
import shutil
import socket
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from content_blocks import sanitize_blocks, sanitize_cached_media_path, sanitize_url


MEDIA_CACHE_POLICY_VERSION = "source-cdn-v1"
RETRYABLE_MEDIA_REASONS = frozenset({
    "cross_site_host", "redirected_cross_site", "download_failed", "event_limit",
})


INPUT_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}
SVG_ALLOWED_TAGS = {
    "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
    "polygon", "text", "tspan", "defs", "linearGradient", "radialGradient",
    "stop", "clipPath", "mask", "title", "desc",
}
SVG_ALLOWED_ATTRS = {
    "viewBox", "width", "height", "preserveAspectRatio", "role", "aria-label",
    "d", "points", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r",
    "rx", "ry", "fill", "fill-opacity", "stroke", "stroke-width",
    "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "stroke-opacity",
    "opacity", "transform", "font-size", "font-family", "font-weight",
    "text-anchor", "dominant-baseline", "offset", "stop-color", "stop-opacity",
    "clip-path", "mask",
}
MEDIA_UA = {
    "User-Agent": "Mozilla/5.0 (compatible; DataHotMedia/1.0; +https://github.com/henryhb1105-arch/datahot)",
    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/svg+xml,image/gif;q=0.8,*/*;q=0.1",
}


class MediaRejected(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _env_int(name, default, minimum=1, maximum=None):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    value = max(minimum, value)
    return min(maximum, value) if maximum is not None else value


def media_enabled():
    return os.getenv("MEDIA_BLOCKS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _host(value):
    return (urlparse(value).hostname or "").casefold().rstrip(".")


def _site_key(host):
    labels = [part for part in host.split(".") if part]
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def same_site_media(media_url, article_url, allowed_hosts=None):
    media_host, article_host = _host(media_url), _host(article_url)
    if not (media_host and article_host):
        return False
    configured = allowed_hosts
    if configured is None:
        configured = {
            item.strip().casefold() for item in os.getenv("MEDIA_ALLOWED_HOSTS", "").split(",")
            if item.strip()
        }
    else:
        configured = {
            str(item).strip().casefold().rstrip(".") for item in configured
            if str(item).strip()
        }
    if any(media_host == allowed or media_host.endswith("." + allowed) for allowed in configured):
        return True
    return (
        media_host == article_host
        or media_host.endswith("." + article_host)
        or article_host.endswith("." + media_host)
        or _site_key(media_host) == _site_key(article_host)
    )


def _assert_public_host(host):
    if not host or host == "localhost" or host.endswith(".local"):
        raise MediaRejected("private_host")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise MediaRejected("private_host")
        return
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise MediaRejected("dns_failed") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise MediaRejected("private_host")


def _https_url(value):
    parsed = urlparse(value)
    if parsed.scheme != "http":
        return value
    return urlunparse(parsed._replace(scheme="https"))


def download_media(
    url, maximum_bytes, timeout=12, allowed_article_url="", *,
    allowed_hosts=None, referer_url="",
):
    safe = sanitize_url(url)
    if not safe:
        raise MediaRejected("invalid_url")
    safe = _https_url(safe)
    _assert_public_host(_host(safe))
    headers = dict(MEDIA_UA)
    referer = sanitize_url(referer_url)
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(safe, headers=headers)
    class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            redirected = sanitize_url(newurl)
            if not redirected:
                raise MediaRejected("invalid_redirect")
            _assert_public_host(_host(redirected))
            if allowed_article_url and not same_site_media(
                redirected, allowed_article_url, allowed_hosts=allowed_hosts,
            ):
                raise MediaRejected("redirected_cross_site")
            return super().redirect_request(req, fp, code, msg, headers, redirected)

    opener = urllib.request.build_opener(SafeRedirectHandler())
    with opener.open(request, timeout=timeout) as response:
        final_url = sanitize_url(response.geturl())
        _assert_public_host(_host(final_url))
        content_type = response.headers.get_content_type().casefold()
        try:
            declared = int(response.headers.get("Content-Length") or 0)
        except ValueError:
            declared = 0
        if declared > maximum_bytes:
            raise MediaRejected("file_too_large")
        chunks, used = [], 0
        while True:
            chunk = response.read(min(64 * 1024, maximum_bytes + 1 - used))
            if not chunk:
                break
            chunks.append(chunk)
            used += len(chunk)
            if used > maximum_bytes:
                raise MediaRejected("file_too_large")
    return b"".join(chunks), content_type, final_url


def _dimension(value):
    match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", str(value or ""))
    return int(float(match.group(1))) if match else 0


def _validate_dimensions(width, height, min_width, min_height, max_pixels):
    if width < min_width or height < min_height:
        raise MediaRejected("dimensions_too_small")
    if width > 10000 or height > 10000 or width * height > max_pixels:
        raise MediaRejected("dimensions_too_large")


def sanitize_svg(data, *, min_width=240, min_height=120, max_pixels=24_000_000, max_bytes=5_000_000):
    if len(data) > min(max_bytes, 1_000_000):
        raise MediaRejected("file_too_large")
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise MediaRejected("unsafe_svg")
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError) as exc:
        raise MediaRejected("invalid_svg") from exc
    local = lambda name: name.rsplit("}", 1)[-1]
    if local(root.tag) != "svg":
        raise MediaRejected("invalid_svg")

    def clean_element(element):
        if local(element.tag) not in SVG_ALLOWED_TAGS:
            return False
        clean_attrs = {}
        for raw_name, raw_value in element.attrib.items():
            name, value = local(raw_name), str(raw_value)[:100000]
            lowered_value = re.sub(r"\s+", "", value).casefold()
            if name not in SVG_ALLOWED_ATTRS or name.casefold().startswith("on"):
                continue
            if any(token in lowered_value for token in ("javascript:", "data:", "http:", "https:", "//")):
                continue
            if "url(" in lowered_value and not re.fullmatch(r"url\(#[a-zA-Z0-9_.:-]+\)", lowered_value):
                continue
            clean_attrs[name] = value
        element.attrib.clear()
        element.attrib.update(clean_attrs)
        for child in list(element):
            if not clean_element(child):
                element.remove(child)
        return True

    clean_element(root)
    width, height = _dimension(root.get("width")), _dimension(root.get("height"))
    if not (width and height):
        values = re.split(r"[\s,]+", root.get("viewBox", "").strip())
        if len(values) == 4:
            try:
                width, height = int(float(values[2])), int(float(values[3]))
            except ValueError:
                width, height = 0, 0
    _validate_dimensions(width, height, min_width, min_height, max_pixels)
    root.set("width", str(width))
    root.set("height", str(height))
    cleaned = ET.tostring(root, encoding="utf-8", method="xml")
    if len(cleaned) > max_bytes:
        raise MediaRejected("file_too_large")
    # The serialized root legitimately carries the SVG XML namespace URL; all
    # attributes capable of external references were removed above.
    if re.search(rb"(?i)<\s*(?:script|foreignObject)|\bon[a-z]+\s*=|(?:data:|javascript:)", cleaned):
        raise MediaRejected("unsafe_svg")
    return cleaned, "image/svg+xml", "svg", width, height


def sanitize_raster(data, content_type, *, min_width=240, min_height=120,
                    max_pixels=24_000_000, max_bytes=5_000_000, max_dimension=2400):
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise MediaRejected("pillow_missing") from exc
    try:
        image = Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP", "GIF"])
        actual_format = str(image.format or "").upper()
        expected_mime = INPUT_MIME_BY_FORMAT.get(actual_format)
        if not expected_mime or content_type != expected_mime:
            raise MediaRejected("mime_mismatch")
        if getattr(image, "is_animated", False):
            raise MediaRejected("animated_media")
        width, height = image.size
        _validate_dimensions(width, height, min_width, min_height, max_pixels)
        image.load()
        image = ImageOps.exif_transpose(image)
        if max(image.size) > max_dimension:
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        if actual_format == "JPEG":
            clean = image.convert("RGB")
            output_format, output_mime, extension = "JPEG", "image/jpeg", "jpg"
            save_options = {"quality": 88, "optimize": True, "progressive": True}
        elif actual_format == "WEBP":
            clean = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output_format, output_mime, extension = "WEBP", "image/webp", "webp"
            save_options = {"quality": 88, "method": 4}
        else:
            clean = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output_format, output_mime, extension = "PNG", "image/png", "png"
            save_options = {"optimize": True}
        # A fresh pixel-only image prevents EXIF, comments and arbitrary source metadata from surviving.
        clean = Image.frombytes(clean.mode, clean.size, clean.tobytes())
        output = io.BytesIO()
        clean.save(output, output_format, **save_options)
        cleaned = output.getvalue()
    except MediaRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise MediaRejected("invalid_image") from exc
    if len(cleaned) > max_bytes:
        raise MediaRejected("file_too_large")
    return cleaned, output_mime, extension, clean.width, clean.height


def sanitize_media(data, content_type, **limits):
    content_type = str(content_type or "").split(";", 1)[0].strip().casefold()
    if content_type == "image/svg+xml":
        svg_limits = {key: value for key, value in limits.items() if key != "max_dimension"}
        return sanitize_svg(data, **svg_limits)
    if content_type not in set(INPUT_MIME_BY_FORMAT.values()):
        raise MediaRejected("mime_not_allowed")
    return sanitize_raster(data, content_type, **limits)


def _safe_event_id(event_id):
    event_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(event_id or ""))[:64]
    return event_id or hashlib.sha256(str(event_id).encode()).hexdigest()[:12]


def cache_event_media(
    blocks, event_id, article_url, site_root, *, fetcher=None, enabled=None,
    allowed_hosts=None, send_referer=False,
):
    """Cache safe figure files and preserve a link-only block for every rejection."""
    enabled = media_enabled() if enabled is None else bool(enabled)
    maximum_bytes = _env_int("MEDIA_MAX_BYTES", 5_000_000, maximum=10_000_000)
    maximum_pixels = _env_int("MEDIA_MAX_PIXELS", 24_000_000, maximum=40_000_000)
    maximum_items = _env_int("MEDIA_MAX_PER_EVENT", 12, maximum=24)
    min_width = _env_int("MEDIA_MIN_WIDTH", 240, maximum=2000)
    min_height = _env_int("MEDIA_MIN_HEIGHT", 120, maximum=2000)
    max_dimension = _env_int("MEDIA_MAX_DIMENSION", 2400, maximum=5000)
    cache_maximum = _env_int("MEDIA_CACHE_MAX_BYTES", 250_000_000, maximum=1_000_000_000)
    safe_blocks = sanitize_blocks(blocks, article_url)
    event_dir = Path(site_root) / "media" / _safe_event_id(event_id)
    report = {
        "figures": 0, "cached": 0, "link_only": 0, "bytes": 0, "reasons": {},
        "policy_version": MEDIA_CACHE_POLICY_VERSION,
    }
    custom_fetcher = fetcher
    expected_cached_prefix = f"../media/{event_dir.name}/"

    for block in safe_blocks:
        if block.get("type") != "figure":
            continue
        report["figures"] += 1
        cached_src = sanitize_cached_media_path(block.get("cached_src"))
        if cached_src and cached_src.startswith(expected_cached_prefix):
            cached_path = Path(site_root) / cached_src.removeprefix("../")
            if cached_path.is_file():
                block["media_status"] = "cached"
                block.pop("media_reason", None)
                report["cached"] += 1
                report["bytes"] += cached_path.stat().st_size
                continue
        block.pop("cached_src", None)
        reason = ""
        if block.get("media_reason") == "rights_restricted":
            reason = "rights_restricted"
        elif (
            block.get("media_status") == "link_only"
            and block.get("media_reason")
            and block.get("media_reason") not in RETRYABLE_MEDIA_REASONS
        ):
            reason = block["media_reason"]
        elif not enabled:
            reason = "disabled"
        elif report["cached"] >= maximum_items:
            reason = "event_limit"
        elif not same_site_media(block["src"], article_url, allowed_hosts=allowed_hosts):
            reason = "cross_site_host"
        try:
            if reason:
                raise MediaRejected(reason)
            downloaded = (
                custom_fetcher(block["src"], maximum_bytes)
                if custom_fetcher is not None
                else download_media(
                    block["src"], maximum_bytes, allowed_article_url=article_url,
                    allowed_hosts=allowed_hosts,
                    referer_url=(
                        article_url
                        if send_referer and not same_site_media(
                            block["src"], article_url, allowed_hosts=(),
                        )
                        else ""
                    ),
                )
            )
            if not isinstance(downloaded, tuple) or len(downloaded) != 3:
                raise MediaRejected("download_failed")
            raw, content_type, final_url = downloaded
            if not same_site_media(final_url, article_url, allowed_hosts=allowed_hosts):
                raise MediaRejected("redirected_cross_site")
            clean, mime, extension, width, height = sanitize_media(
                raw, content_type, min_width=min_width, min_height=min_height,
                max_pixels=maximum_pixels, max_bytes=maximum_bytes,
                max_dimension=max_dimension,
            )
            cache_root = Path(site_root) / "media"
            current_cache_bytes = sum(
                path.stat().st_size for path in cache_root.glob("*/*") if path.is_file()
            ) if cache_root.exists() else 0
            if current_cache_bytes + len(clean) > cache_maximum:
                raise MediaRejected("cache_total_limit")
            digest = hashlib.sha256(clean).hexdigest()
            event_dir.mkdir(parents=True, exist_ok=True)
            destination = event_dir / f"{digest[:24]}.{extension}"
            if not destination.exists():
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                temporary.write_bytes(clean)
                os.replace(temporary, destination)
            block.update({
                "cached_src": f"../media/{event_dir.name}/{destination.name}",
                "width": width, "height": height, "mime": mime,
                "size_bytes": len(clean), "media_status": "cached",
            })
            block.pop("media_reason", None)
            report["cached"] += 1
            report["bytes"] += len(clean)
        except MediaRejected as exc:
            block.pop("cached_src", None)
            block["media_status"] = "link_only"
            block["media_reason"] = exc.reason
            report["link_only"] += 1
            report["reasons"][exc.reason] = report["reasons"].get(exc.reason, 0) + 1
        except Exception:
            block.pop("cached_src", None)
            block["media_status"] = "link_only"
            block["media_reason"] = "download_failed"
            report["link_only"] += 1
            report["reasons"]["download_failed"] = report["reasons"].get("download_failed", 0) + 1
    return sanitize_blocks(safe_blocks, article_url), report


def prune_media_cache(active_event_ids, site_root):
    """Remove only event-scoped media directories no longer present in latest.json."""
    media_root = Path(site_root) / "media"
    if not media_root.exists():
        return {"removed_dirs": 0, "removed_bytes": 0}
    active = {_safe_event_id(event_id) for event_id in active_event_ids}
    removed_dirs = removed_bytes = 0
    for child in media_root.iterdir():
        if not child.is_dir() or child.name in active or _safe_event_id(child.name) != child.name:
            continue
        removed_bytes += sum(path.stat().st_size for path in child.rglob("*") if path.is_file())
        shutil.rmtree(child)
        removed_dirs += 1
    return {"removed_dirs": removed_dirs, "removed_bytes": removed_bytes}
