"""Reviewed focal regions in original screenshots; never rewrite image pixels."""
import html
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from image_derivatives import responsive_image

MANIFEST = Path(__file__).with_name("case_visuals.json")


@lru_cache(maxsize=1)
def load_visuals():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "case-visuals-v1":
        raise ValueError("invalid case visual schema")
    regions = {}
    for region in payload.get("regions", []):
        src = region.get("src", "")
        if not re.fullmatch(r"(?:case-media|media)/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+\.(?:png|jpe?g|webp)", src) or src in regions:
            raise ValueError("unsafe or duplicate focal image")
        rect = region.get("rect", [])
        dimensions = [region.get("image_width"), region.get("image_height")]
        if len(rect) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in [*rect, *dimensions]):
            raise ValueError("invalid focal coordinates")
        x, y, width, height = rect
        iw, ih = dimensions
        if min(x, y) < 0 or min(width, height, iw, ih) <= 0 or x + width > iw or y + height > ih:
            raise ValueError("focal region outside source image")
        if abs(width / height - 16 / 9) > .01 or not isinstance(region.get("label"), str) or not region["label"].strip():
            raise ValueError("focal region requires a 16:9 preview and label")
        regions[src] = region
    return regions


def visual_for(src):
    return load_visuals().get(str(src).removeprefix("../"))


def card_image(src, alt, *, site_root=None, priority=False):
    source, text = html.escape(src, quote=True), html.escape(alt, quote=True)
    region = visual_for(src)
    preview = responsive_image(src, site_root, widths=(400, 800, 1200), crop=region["rect"] if region else None)
    loading = 'loading="eager" fetchpriority="high"' if priority else 'loading="lazy"'
    if preview:
        suffix = "（局部预览）" if region else ""
        sizes = "(max-width:600px) calc(100vw - 30px), (max-width:820px) 116px, (max-width:1200px) calc((100vw - 258px)/2), 352px"
        image = (f'<img src="{preview["src"]}" srcset="{preview["srcset"]}" sizes="{sizes}" '
                 f'width="{preview["width"]}" height="{preview["height"]}" alt="{text}{suffix}" '
                 f'{loading} decoding="async">')
        if region:
            return f'<span class="case-preview-window">{image}</span><span class="case-preview-label">局部预览 · 点击看全图</span>'
        return image
    if not region:
        return f'<img src="{source}" alt="{text}" {loading} decoding="async">'
    x, y, width, height = region["rect"]
    style = f'width:{region["image_width"] / width * 100:.4f}%;left:{-x / width * 100:.4f}%;top:{-y / height * 100:.4f}%'
    return f'<span class="case-preview-window"><img src="{source}" alt="{text}（局部预览）" style="{style}" {loading} decoding="async"></span><span class="case-preview-label">局部预览 · 点击看全图</span>'


def detail_image(src, alt, attributes=""):
    """Outline a reviewed region on the full image; viewer receives the original."""
    source, text = html.escape(src, quote=True), html.escape(alt, quote=True)
    image = f'<img src="{source}" alt="{text}" {attributes} decoding="async">'
    region = visual_for(src)
    if not region:
        return image
    x, y, width, height = region["rect"]
    iw, ih = region["image_width"], region["image_height"]
    style = f'left:{x / iw * 100:.4f}%;top:{y / ih * 100:.4f}%;width:{width / iw * 100:.4f}%;height:{height / ih * 100:.4f}%'
    return f'<span class="study-image-frame" style="max-width:{520 * iw / ih:.2f}px">{image}<span class="study-focus-region" style="{style}" aria-hidden="true"><b>1</b></span></span>'


def focus_caption(src):
    region = visual_for(src)
    return f'<span class="study-focus-caption">① {html.escape(region["label"])}</span>' if region else ""
