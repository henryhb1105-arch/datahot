"""Build local, versioned display images without changing original source assets."""
import hashlib
import io
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


def responsive_image(src, site_root, widths=(480, 960, 1440), crop=None):
    """Return responsive attributes, keeping the input's optional ../ URL prefix.

    Only cached media and reviewed case-media are eligible. Missing/unsupported
    originals retain their existing rendering. Unsafe paths are rejected.
    """
    if site_root is None:
        return None
    src = str(src)
    prefix = "../" if src.startswith("../") else ""
    relative = src.removeprefix(prefix) if prefix else src
    if not re.fullmatch(r"(?:case-media|media)/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+\.(?:png|jpe?g|webp)", relative):
        return None
    root = Path(site_root).resolve()
    original = (root / relative).resolve()
    if not original.is_relative_to(root):
        raise ValueError("display image escapes site root")
    if not original.is_file() or original.stat().st_size > 10_000_000:
        return None
    content = original.read_bytes()
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > 24_000_000 or getattr(source, "is_animated", False):
                return None
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGBA" if "A" in source.getbands() else "RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None
    if crop is not None:
        if len(crop) != 4 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in crop):
            raise ValueError("invalid preview crop")
        x, y, width, height = crop
        if min(x, y) < 0 or min(width, height) <= 0 or x + width > image.width or y + height > image.height:
            raise ValueError("preview crop outside original image")
        image = image.crop(tuple(round(v) for v in (x, y, x + width, y + height)))
    iw, ih = image.size
    sizes = sorted({min(int(w), iw) for w in widths if int(w) > 0})
    if not sizes:
        return None
    settings = json.dumps({"version": 1, "crop": crop, "widths": sizes, "quality": 84, "method": 4}, sort_keys=True).encode()
    digest = hashlib.sha256(content + settings).hexdigest()[:20]
    directory = (root / "derived-media").resolve()
    if not directory.is_relative_to(root):
        raise ValueError("display image output escapes site root")
    directory.mkdir(exist_ok=True)
    variants = []
    for width in sizes:
        name = f"{digest}-{width}.webp"
        target = directory / name
        if target.is_symlink():
            raise ValueError("display image output is a symlink")
        if not target.is_file():
            resized = image.resize((width, max(1, round(ih * width / iw))), Image.Resampling.LANCZOS)
            resized.save(target, "WEBP", quality=84, method=4)
        variants.append((f"{prefix}derived-media/{name}", width))
    return {
        "src": variants[0][0],
        "srcset": ", ".join(f"{url} {width}w" for url, width in variants),
        "width": iw,
        "height": ih,
    }
