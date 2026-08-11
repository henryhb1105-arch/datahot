#!/usr/bin/env python3
"""Validate every local href/src in a generated static site."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class BrokenLink:
    source: Path
    line: int
    reference: str
    target: Path
    reason: str = "missing"


class LocalReferenceParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []

    def _collect(self, attrs):
        line, _column = self.getpos()
        for name, value in attrs:
            if name.casefold() in {"href", "src"} and value is not None:
                self.references.append((line, value.strip()))

    def handle_starttag(self, tag, attrs):
        self._collect(attrs)

    def handle_startendtag(self, tag, attrs):
        self._collect(attrs)


def _is_exact_path(path, root):
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        try:
            names = {child.name for child in current.iterdir()}
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return False
        if part not in names:
            return False
        current = current / part
    return current.exists()


def resolve_local_reference(site_root, source, reference, project_path="datahot"):
    if not reference or reference.startswith("#") or reference.startswith("//"):
        return None
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc:
        return None
    raw_path = unquote(parsed.path)
    if not raw_path:
        return source
    if "\x00" in raw_path:
        return (site_root / "__invalid_null_path__").resolve()
    if raw_path.startswith("/"):
        prefix = f"/{project_path.strip('/')}/"
        if raw_path == f"/{project_path.strip('/')}" or raw_path == prefix:
            raw_path = "index.html"
        elif raw_path.startswith(prefix):
            raw_path = raw_path[len(prefix):]
        else:
            raw_path = raw_path.lstrip("/")
        target = site_root / raw_path
    else:
        target = source.parent / raw_path
    target = target.resolve()
    if target.is_dir() or raw_path.endswith("/"):
        target = target / "index.html"
    return target


def check_site_links(site_root, project_path="datahot"):
    site_root = Path(site_root).resolve()
    broken = []
    for source in sorted(site_root.rglob("*.html")):
        parser = LocalReferenceParser()
        try:
            parser.feed(source.read_text(encoding="utf-8"))
            parser.close()
        except (OSError, UnicodeError) as exc:
            broken.append(BrokenLink(source, 0, "", source, f"unreadable:{type(exc).__name__}"))
            continue
        for line, reference in parser.references:
            target = resolve_local_reference(site_root, source, reference, project_path)
            if target is None:
                continue
            try:
                target.relative_to(site_root)
            except ValueError:
                broken.append(BrokenLink(source, line, reference, target, "outside_site"))
                continue
            if not _is_exact_path(target, site_root):
                broken.append(BrokenLink(source, line, reference, target, "missing"))
    return broken


def format_broken_links(broken, site_root):
    site_root = Path(site_root).resolve()
    lines = []
    for item in broken:
        try:
            source = item.source.relative_to(site_root)
        except ValueError:
            source = item.source
        try:
            target = item.target.relative_to(site_root)
        except ValueError:
            target = item.target
        lines.append(
            f"{source}:{item.line}: {item.reference!r} -> {target} ({item.reason})"
        )
    return "\n".join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    site_root = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent / "site"
    broken = check_site_links(site_root)
    if broken:
        print(f"[links] 失败：发现 {len(broken)} 个失效本地引用")
        print(format_broken_links(broken, site_root))
        return 1
    html_count = sum(1 for _ in site_root.rglob("*.html"))
    print(f"[links] 通过：{html_count} 个 HTML，本地 href/src 100% 有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
