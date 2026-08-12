#!/usr/bin/env python3
"""Safe structured article blocks: parse, sanitize, translate and render."""

from __future__ import annotations

import copy
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


BLOCK_TYPES = {"heading", "paragraph", "list", "blockquote", "code", "table", "figure"}
INLINE_MARKS = {"strong", "em", "code"}
COLOR_TOKENS = {"accent", "warning", "positive", "info", "emphasis"}
SKIP_CONTAINER_TAGS = {
    "script", "style", "noscript", "iframe", "object", "form", "button",
    "select", "textarea", "canvas", "svg", "head", "nav", "footer",
    "header", "aside",
}
SKIP_VOID_TAGS = {"input", "embed"}
DANGEROUS_TAGS = SKIP_CONTAINER_TAGS | SKIP_VOID_TAGS
HTML_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
ARTICLE_CONTAINER_RE = re.compile(
    r"(?:^|[\s_-])(?:article|post|entry|story|richtext|rich-text|markdown|prose)"
    r"(?:[\s_-]*(?:body|content|text))?(?:$|[\s_-])|"
    r"(?:^|[\s_-])(?:body|content)[\s_-]*(?:article|post|story)(?:$|[\s_-])",
    re.I,
)
DECORATIVE_IMAGE_RE = re.compile(
    r"(?:logo|avatar|icon|favicon|emoji|badge|author|profile|portrait|sponsor|"
    r"advert|tracking|pixel|spacer|sprite)",
    re.I,
)
EXPLANATORY_IMAGE_RE = re.compile(
    r"(?:chart|diagram|architecture|workflow|benchmark|figure|graph|flow|"
    r"架构|流程|图表|示意|对比)",
    re.I,
)
BLOCK_ID_RE = re.compile(r"^b-[a-f0-9]{10,16}(?:-\d+)?$")
TEXT_ID_RE = re.compile(r"^t-[a-f0-9]{10,16}(?:-\d+)?$")
CACHED_MEDIA_RE = re.compile(
    r"^\.\./media/[a-zA-Z0-9_-]{1,64}/[a-f0-9]{16,64}\.(?:jpg|png|webp|svg)$"
)


def sanitize_url(value, base_url=""):
    value = re.sub(r"[\x00-\x20]+", "", str(value or ""))
    if not value:
        return ""
    if "\\" in value:
        return ""
    absolute = urljoin(base_url, value)
    try:
        parsed = urlparse(absolute)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username
        or parsed.password
    ):
        return ""
    return absolute


def sanitize_cached_media_path(value):
    value = str(value or "").strip()
    return value if CACHED_MEDIA_RE.fullmatch(value) else ""


def color_token(value):
    value = str(value or "").casefold()
    hex_match = re.search(r"#([0-9a-f]{3}|[0-9a-f]{6})(?![0-9a-f])", value)
    rgb = None
    if hex_match:
        raw = hex_match.group(1)
        if len(raw) == 3:
            raw = "".join(char * 2 for char in raw)
        rgb = tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4))
    else:
        rgb_match = re.search(r"rgb(?:a)?\(\s*(\d+)\D+(\d+)\D+(\d+)", value)
        if rgb_match:
            rgb = tuple(min(255, int(channel)) for channel in rgb_match.groups())
    if rgb:
        red, green, blue = rgb
        if red > green * 1.2 and red > blue * 1.2:
            return "accent"
        if red > 150 and green > 110 and blue < 100:
            return "warning"
        if green > red * 1.15 and green > blue * 1.05:
            return "positive"
        if blue > red * 1.1 or blue > green * 1.1:
            return "info"
        return "emphasis"
    if any(word in value for word in ("red", "orange")):
        return "accent"
    if any(word in value for word in ("yellow", "gold", "amber")):
        return "warning"
    if any(word in value for word in ("green", "lime", "teal")):
        return "positive"
    if any(word in value for word in ("blue", "purple", "violet", "indigo")):
        return "info"
    return "emphasis"


def _clean_text(value, maximum=16000):
    return str(value or "").replace("\x00", "")[:maximum]


def _clean_marks(marks, base_url=""):
    cleaned = []
    for mark in marks if isinstance(marks, list) else []:
        if isinstance(mark, str) and mark in INLINE_MARKS and mark not in cleaned:
            cleaned.append(mark)
        elif isinstance(mark, dict) and mark.get("type") == "link":
            href = sanitize_url(mark.get("href"), base_url)
            if href:
                cleaned.append({"type": "link", "href": href})
        elif isinstance(mark, dict) and mark.get("type") == "color":
            token = mark.get("token")
            cleaned.append({
                "type": "color",
                "token": token if token in COLOR_TOKENS else "emphasis",
            })
    return cleaned


def _clean_inlines(nodes, base_url=""):
    output = []
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict) or node.get("type") != "text":
            continue
        text = _clean_text(node.get("text"), 8000)
        if not text:
            continue
        cleaned = {
            "type": "text",
            "text": text,
            "marks": _clean_marks(node.get("marks", []), base_url),
        }
        if TEXT_ID_RE.match(str(node.get("id", ""))):
            cleaned["id"] = node["id"]
        if output and output[-1].get("marks") == cleaned["marks"] and "\n" not in text:
            output[-1]["text"] += text
        else:
            output.append(cleaned)
    return output


def sanitize_blocks(blocks, base_url=""):
    output = []
    for raw in blocks if isinstance(blocks, list) else []:
        if not isinstance(raw, dict) or raw.get("type") not in BLOCK_TYPES:
            continue
        kind = raw["type"]
        block = {"type": kind}
        if BLOCK_ID_RE.match(str(raw.get("id", ""))):
            block["id"] = raw["id"]
        if kind in {"heading", "paragraph", "blockquote"}:
            block["children"] = _clean_inlines(raw.get("children", []), base_url)
            if kind == "heading":
                try:
                    block["level"] = min(4, max(2, int(raw.get("level", 2))))
                except (TypeError, ValueError):
                    block["level"] = 2
            if not block["children"]:
                continue
        elif kind == "list":
            block["ordered"] = bool(raw.get("ordered"))
            block["items"] = []
            for item in raw.get("items", []) if isinstance(raw.get("items"), list) else []:
                children = _clean_inlines(
                    item.get("children", []) if isinstance(item, dict) else item,
                    base_url,
                )
                if children:
                    block["items"].append({"children": children})
            if not block["items"]:
                continue
        elif kind == "code":
            block["text"] = _clean_text(raw.get("text"), 30000)
            language = re.sub(r"[^a-zA-Z0-9_+.-]", "", str(raw.get("language") or ""))[:30]
            if language:
                block["language"] = language
            if not block["text"].strip():
                continue
        elif kind == "table":
            rows = []
            for raw_row in raw.get("rows", []) if isinstance(raw.get("rows"), list) else []:
                cells = []
                source_cells = raw_row.get("cells", []) if isinstance(raw_row, dict) else raw_row
                for raw_cell in source_cells if isinstance(source_cells, list) else []:
                    children = _clean_inlines(
                        raw_cell.get("children", []) if isinstance(raw_cell, dict) else raw_cell,
                        base_url,
                    )
                    if children:
                        cell = {
                            "header": bool(raw_cell.get("header")) if isinstance(raw_cell, dict) else False,
                            "children": children,
                        }
                        if isinstance(raw_cell, dict):
                            for span_name in ("rowspan", "colspan"):
                                try:
                                    span = int(raw_cell.get(span_name, 1))
                                except (TypeError, ValueError):
                                    span = 1
                                if 1 < span <= 20:
                                    cell[span_name] = span
                        cells.append(cell)
                if cells:
                    rows.append({"cells": cells})
            block["rows"] = rows[:100]
            if not block["rows"]:
                continue
        elif kind == "figure":
            src = sanitize_url(raw.get("src") or raw.get("original_src"), base_url)
            if not src:
                continue
            block.update({
                "src": src,
                "alt": _clean_text(raw.get("alt"), 500),
                "caption": _clean_text(raw.get("caption"), 1000),
            })
            source_url = sanitize_url(raw.get("source_url"), base_url)
            if source_url:
                block["source_url"] = source_url
            cached_src = sanitize_cached_media_path(raw.get("cached_src"))
            if cached_src:
                block["cached_src"] = cached_src
            for dimension in ("width", "height"):
                try:
                    value = int(raw.get(dimension, 0))
                except (TypeError, ValueError):
                    value = 0
                if 0 < value <= 10000:
                    block[dimension] = value
            if raw.get("mime") in {"image/jpeg", "image/png", "image/webp", "image/svg+xml"}:
                block["mime"] = raw["mime"]
            try:
                size_bytes = int(raw.get("size_bytes", 0))
            except (TypeError, ValueError):
                size_bytes = 0
            if 0 < size_bytes <= 10_000_000:
                block["size_bytes"] = size_bytes
            if raw.get("media_status") in {"cached", "link_only"}:
                block["media_status"] = raw["media_status"]
            reason = re.sub(r"[^a-z0-9_-]", "", str(raw.get("media_reason") or "").lower())[:40]
            if reason:
                block["media_reason"] = reason
        output.append(block)
    return assign_stable_ids(output)


def _without_ids(value):
    if isinstance(value, dict):
        return {key: _without_ids(val) for key, val in value.items() if key != "id"}
    if isinstance(value, list):
        return [_without_ids(item) for item in value]
    return value


def assign_stable_ids(blocks):
    block_counts, text_counts = {}, {}
    for block in blocks:
        digest = hashlib.sha256(
            json.dumps(_without_ids(block), ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        block_counts[digest] = block_counts.get(digest, 0) + 1
        if not BLOCK_ID_RE.match(str(block.get("id", ""))):
            suffix = f"-{block_counts[digest]}" if block_counts[digest] > 1 else ""
            block["id"] = f"b-{digest}{suffix}"
        for index, node in enumerate(iter_text_nodes(block)):
            text_digest = hashlib.sha256(
                f"{block['id']}\0{index}\0{node.get('text','')}\0{json.dumps(node.get('marks',[]), sort_keys=True)}".encode("utf-8")
            ).hexdigest()[:12]
            text_counts[text_digest] = text_counts.get(text_digest, 0) + 1
            if not TEXT_ID_RE.match(str(node.get("id", ""))):
                suffix = f"-{text_counts[text_digest]}" if text_counts[text_digest] > 1 else ""
                node["id"] = f"t-{text_digest}{suffix}"
    return blocks


def iter_text_nodes(value):
    if isinstance(value, dict):
        if value.get("type") == "text":
            yield value
        else:
            for child in value.values():
                yield from iter_text_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_text_nodes(child)


TAG_TOKEN_RE = re.compile(
    r"(?is)<!--.*?-->|<![^>]*>|<\s*(/?)\s*([a-zA-Z][\w:-]*)([^>]*)>"
)


def _container_regions(html_text):
    """Return balanced article-like container slices without building a live DOM."""
    stack, regions = [], []
    for match in TAG_TOKEN_RE.finditer(str(html_text or "")):
        tag = str(match.group(2) or "").casefold()
        if not tag:
            continue
        closing = bool(match.group(1))
        attrs = str(match.group(3) or "")
        if closing:
            index = next(
                (i for i in range(len(stack) - 1, -1, -1) if stack[i]["tag"] == tag),
                None,
            )
            if index is None:
                continue
            opened = stack[index]
            del stack[index:]
            if tag in {"article", "main", "div", "section"}:
                regions.append({
                    "tag": tag,
                    "attrs": opened["attrs"],
                    "html": str(html_text or "")[opened["start"]:match.end()],
                })
            continue
        if tag not in HTML_VOID_TAGS and not attrs.rstrip().endswith("/"):
            stack.append({"tag": tag, "attrs": attrs, "start": match.start()})
    return regions


def _jsonld_article_bodies(html_text):
    bodies = []

    def visit(value):
        if isinstance(value, dict):
            body = value.get("articleBody")
            if isinstance(body, str) and body.strip():
                bodies.append(body.strip())
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    pattern = re.compile(r"(?is)<script\b([^>]*)>(.*?)</script\s*>")
    for attrs, payload in pattern.findall(str(html_text or "")):
        if "ld+json" not in attrs.casefold():
            continue
        try:
            visit(json.loads(html.unescape(payload).strip()))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return bodies


def _text_to_blocks(value):
    paragraphs = [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"(?:\r?\n){2,}", str(value or ""))
        if part.strip()
    ]
    if len(paragraphs) == 1 and len(paragraphs[0]) > 1600:
        paragraphs = [
            part.strip() for part in re.split(r"(?<=[。！？.!?])\s+", paragraphs[0])
            if part.strip()
        ]
    return sanitize_blocks([
        {"type": "paragraph", "children": [{"type": "text", "text": part, "marks": []}]}
        for part in paragraphs
    ])


def _rough_text_length(fragment):
    value = re.sub(
        r"(?is)<(?:script|style|noscript|nav|footer|header|aside)\b[^>]*>.*?</(?:script|style|noscript|nav|footer|header|aside)\s*>",
        " ", str(fragment or ""),
    )
    return len(re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", value)).strip())


def _block_counts(blocks):
    return {
        "blocks": len(blocks),
        "text_chars": len(blocks_plain_text(blocks)),
        "figures": sum(block.get("type") == "figure" for block in blocks),
        "tables": sum(block.get("type") == "table" for block in blocks),
    }


def _meaningful_blocks(blocks):
    counts = _block_counts(blocks)
    return counts["text_chars"] >= 400 or (
        counts["text_chars"] >= 120 and counts["figures"] + counts["tables"] > 0
    )


def select_article_media(blocks, maximum=None):
    """Drop decorative media and keep explanatory figures in source order.

    ``maximum`` remains available for bounded callers, but article extraction keeps
    every useful figure by default.  The media cache applies its own download cap;
    figures beyond that cap remain visible as safe source links instead of vanishing.
    """
    safe = sanitize_blocks(blocks)
    candidates, seen = [], set()
    for index, block in enumerate(safe):
        if block.get("type") != "figure":
            continue
        parsed = urlparse(block.get("src", ""))
        identity = (parsed.netloc.casefold(), parsed.path.rstrip("/").casefold())
        descriptor = " ".join((block.get("src", ""), block.get("alt", ""), block.get("caption", "")))
        width, height = int(block.get("width", 0)), int(block.get("height", 0))
        if identity in seen or DECORATIVE_IMAGE_RE.search(descriptor):
            continue
        if width and height and (width < 240 or height < 120):
            continue
        seen.add(identity)
        score = 0
        score += 5 if block.get("caption") else 0
        score += 2 if block.get("alt") else 0
        score += 3 if width >= 640 and height >= 240 else 0
        score += 6 if EXPLANATORY_IMAGE_RE.search(descriptor) else 0
        candidates.append((score, index))
    ranked = sorted(candidates, key=lambda value: (-value[0], value[1]))
    if maximum is not None:
        ranked = ranked[:max(0, int(maximum))]
    selected = {index for _score, index in ranked}
    filtered = [
        block for index, block in enumerate(safe)
        if block.get("type") != "figure" or index in selected
    ]
    return sanitize_blocks(filtered), {
        "figures_discovered": sum(block.get("type") == "figure" for block in safe),
        "figures_selected": len(selected),
        "figures_rejected": sum(block.get("type") == "figure" for block in safe) - len(selected),
    }


class ArticleBlockParser(HTMLParser):
    def __init__(self, base_url=""):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.blocks = []
        self.current = None
        self.list_block = None
        self.list_item = None
        self.code_block = None
        self.table_block = None
        self.table_row = None
        self.table_cell = None
        self.active_marks = []
        self.mark_frames = []
        self.skip_stack = []
        self.figure_block = None
        self.figure_caption = False
        self.figure_caption_parts = []

    def _flush_current(self):
        if self.current and self.current.get("children"):
            self.blocks.append(self.current)
        self.current = None

    def _push_mark(self, tag, mark):
        self.mark_frames.append((tag, mark))
        if mark is not None:
            self.active_marks.append(mark)

    def _pop_mark(self, tag):
        for index in range(len(self.mark_frames) - 1, -1, -1):
            frame_tag, mark = self.mark_frames[index]
            if frame_tag == tag:
                self.mark_frames.pop(index)
                if mark is not None:
                    for mark_index in range(len(self.active_marks) - 1, -1, -1):
                        if self.active_marks[mark_index] == mark:
                            self.active_marks.pop(mark_index)
                            break
                return

    def _target_inlines(self):
        if self.table_cell is not None:
            return self.table_cell["children"]
        if self.list_item is not None:
            return self.list_item["children"]
        if self.current is None:
            self.current = {"type": "paragraph", "children": []}
        return self.current["children"]

    def _append_text(self, data):
        if self.code_block is not None:
            self.code_block["text"] += data
            return
        if not data:
            return
        normalized = re.sub(r"\s+", " ", data)
        if not normalized.strip() and "\n" not in data:
            normalized = " "
        target = self._target_inlines()
        node = {"type": "text", "text": normalized, "marks": copy.deepcopy(self.active_marks)}
        if target and target[-1].get("marks") == node["marks"]:
            target[-1]["text"] += node["text"]
        else:
            target.append(node)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = {str(key).lower(): value for key, value in attrs}
        if self.skip_stack:
            if tag in SKIP_CONTAINER_TAGS:
                self.skip_stack.append(tag)
            return
        if tag in SKIP_VOID_TAGS:
            return
        if tag in SKIP_CONTAINER_TAGS:
            self._flush_current()
            self.skip_stack.append(tag)
            return
        if self.figure_caption:
            if tag == "br":
                self.figure_caption_parts.append("\n")
            return
        if tag == "figure":
            self._flush_current()
            self.figure_block = {
                "type": "figure", "src": "", "alt": "", "caption": "",
                "source_url": self.base_url,
            }
            self.figure_caption_parts = []
        elif tag == "figcaption" and self.figure_block is not None:
            self.figure_caption = True
        elif tag == "img":
            candidates = [
                attrs.get("data-src"), attrs.get("data-original"),
                attrs.get("data-lazy-src"), attrs.get("src"),
            ]
            srcset = attrs.get("srcset") or attrs.get("data-srcset") or ""
            if srcset:
                ranked = []
                for index, candidate in enumerate(srcset.split(",")):
                    parts = candidate.strip().split()
                    if not parts:
                        continue
                    score = index
                    if len(parts) > 1:
                        match = re.match(r"([0-9.]+)(w|x)$", parts[-1])
                        if match:
                            score = float(match.group(1)) * (10000 if match.group(2) == "x" else 1)
                    ranked.append((score, parts[0]))
                if ranked:
                    candidates.insert(0, max(ranked, key=lambda value: value[0])[1])
            src = next((sanitize_url(value, self.base_url) for value in candidates if sanitize_url(value, self.base_url)), "")
            if src:
                figure = self.figure_block or {
                    "type": "figure", "src": src, "alt": "", "caption": "",
                    "source_url": self.base_url,
                }
                if not figure.get("src"):
                    figure["src"] = src
                figure["alt"] = _clean_text(attrs.get("alt"), 500)
                for dimension in ("width", "height"):
                    match = re.search(r"\d+", str(attrs.get(dimension) or ""))
                    if match:
                        figure[dimension] = int(match.group(0))
                if self.figure_block is None:
                    self._flush_current()
                    self.blocks.append(figure)
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush_current()
            self.current = {"type": "heading", "level": min(4, max(2, int(tag[1]))), "children": []}
        elif tag == "p":
            if self.current and self.current.get("type") == "blockquote" and self.current.get("children"):
                self._append_text("\n")
            elif self.list_item is None and self.current is None and self.table_cell is None:
                self.current = {"type": "paragraph", "children": []}
        elif tag in {"ul", "ol"} and self.list_block is None:
            self._flush_current()
            self.list_block = {"type": "list", "ordered": tag == "ol", "items": []}
        elif tag == "li" and self.list_block is not None:
            self.list_item = {"children": []}
        elif tag == "blockquote":
            self._flush_current()
            self.current = {"type": "blockquote", "children": []}
        elif tag == "pre":
            self._flush_current()
            language = ""
            class_name = attrs.get("class") or ""
            match = re.search(r"(?:language-|lang-)([a-zA-Z0-9_+.-]+)", class_name)
            if match:
                language = match.group(1)
            self.code_block = {"type": "code", "text": "", "language": language}
        elif tag == "table":
            self._flush_current()
            self.table_block = {"type": "table", "rows": []}
        elif tag == "tr" and self.table_block is not None:
            self.table_row = {"cells": []}
        elif tag in {"th", "td"} and self.table_row is not None:
            self.table_cell = {"header": tag == "th", "children": []}
            for span_name in ("rowspan", "colspan"):
                try:
                    span = int(attrs.get(span_name, 1))
                except (TypeError, ValueError):
                    span = 1
                if 1 < span <= 20:
                    self.table_cell[span_name] = span
        elif tag == "br":
            self._append_text("\n")
        elif tag in {"strong", "b"}:
            self._push_mark(tag, "strong")
        elif tag in {"em", "i"}:
            self._push_mark(tag, "em")
        elif tag == "code" and self.code_block is None:
            self._push_mark(tag, "code")
        elif tag == "a":
            href = sanitize_url(attrs.get("href"), self.base_url)
            self._push_mark(tag, {"type": "link", "href": href} if href else None)
        elif tag in {"span", "font", "mark"}:
            style = attrs.get("style") or ""
            raw_color = attrs.get("color") or ""
            has_color = bool(raw_color or re.search(r"(?:^|;)\s*color\s*:", style, re.I))
            if tag == "mark":
                self._push_mark(tag, {"type": "color", "token": "warning"})
            elif has_color:
                self._push_mark(tag, {
                    "type": "color", "token": color_token(raw_color or style),
                })
            else:
                self._push_mark(tag, None)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip_stack:
            if tag in self.skip_stack:
                while self.skip_stack:
                    opened = self.skip_stack.pop()
                    if opened == tag:
                        break
            return
        if tag == "figcaption" and self.figure_block is not None:
            self.figure_caption = False
            self.figure_block["caption"] = re.sub(
                r"\s+", " ", "".join(self.figure_caption_parts)
            ).strip()
            return
        if self.figure_caption:
            return
        if tag == "figure" and self.figure_block is not None:
            if self.figure_block.get("src"):
                self.blocks.append(self.figure_block)
            self.figure_block = None
            self.figure_caption_parts = []
        elif tag in {"strong", "b", "em", "i", "a", "span", "font", "mark"}:
            self._pop_mark(tag)
        elif tag == "code" and self.code_block is None:
            self._pop_mark(tag)
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}:
            self._flush_current()
        elif (
            tag == "p" and self.list_item is None and self.table_cell is None
            and self.current is not None and self.current.get("type") == "paragraph"
        ):
            self._flush_current()
        elif tag == "li" and self.list_block is not None:
            if self.list_item and self.list_item.get("children"):
                self.list_block["items"].append(self.list_item)
            self.list_item = None
        elif tag in {"ul", "ol"} and self.list_block is not None:
            if self.list_block.get("items"):
                self.blocks.append(self.list_block)
            self.list_block = None
        elif tag == "pre" and self.code_block is not None:
            if self.code_block["text"].strip():
                self.blocks.append(self.code_block)
            self.code_block = None
        elif tag in {"th", "td"} and self.table_cell is not None:
            if self.table_cell.get("children"):
                self.table_row["cells"].append(self.table_cell)
            self.table_cell = None
        elif tag == "tr" and self.table_row is not None:
            if self.table_row.get("cells"):
                self.table_block["rows"].append(self.table_row)
            self.table_row = None
        elif tag == "table" and self.table_block is not None:
            if self.table_block.get("rows"):
                self.blocks.append(self.table_block)
            self.table_block = None
        elif tag in {"div", "section", "article", "main"} and self.current is not None:
            self._flush_current()

    def handle_data(self, data):
        if self.skip_stack:
            return
        if self.figure_caption:
            self.figure_caption_parts.append(data)
            return
        if data.strip() or self.current is not None or self.list_item is not None or self.table_cell is not None:
            self._append_text(data)

    def close(self):
        super().close()
        self._flush_current()
        if self.figure_block and self.figure_block.get("src"):
            self.blocks.append(self.figure_block)
        self.figure_block = None


def _parse_html_blocks_raw(html_text, base_url=""):
    parser = ArticleBlockParser(base_url)
    try:
        parser.feed(str(html_text or ""))
        parser.close()
    except Exception:
        return []
    return sanitize_blocks(parser.blocks, base_url)


def parse_html_blocks_with_report(html_text, base_url="", maximum_figures=None):
    """Extract the best article body and return auditable selection metadata."""
    source = str(html_text or "")
    regions = _container_regions(source)
    strategies = [
        ("article", [region for region in regions if region["tag"] == "article"]),
        ("main", [region for region in regions if region["tag"] == "main"]),
        (
            "semantic_container",
            [
                region for region in regions
                if region["tag"] in {"div", "section"}
                and ARTICLE_CONTAINER_RE.search(region["attrs"])
            ],
        ),
    ]
    selected, strategy = [], ""
    for name, candidates in strategies:
        parsed = [_parse_html_blocks_raw(candidate["html"], base_url) for candidate in candidates]
        parsed = [blocks for blocks in parsed if _meaningful_blocks(blocks)]
        if parsed:
            selected = max(parsed, key=lambda blocks: _block_counts(blocks)["text_chars"])
            strategy = name
            break

    if not selected:
        jsonld = [_text_to_blocks(body) for body in _jsonld_article_bodies(source)]
        jsonld = [blocks for blocks in jsonld if _meaningful_blocks(blocks)]
        if jsonld:
            selected = max(jsonld, key=lambda blocks: _block_counts(blocks)["text_chars"])
            strategy = "jsonld_article_body"

    if not selected:
        largest = sorted(
            (
                region for region in regions
                if region["tag"] in {"div", "section"}
                and _rough_text_length(region["html"]) >= 400
            ),
            key=lambda region: _rough_text_length(region["html"]),
            reverse=True,
        )[:12]
        parsed = [_parse_html_blocks_raw(candidate["html"], base_url) for candidate in largest]
        parsed = [blocks for blocks in parsed if _meaningful_blocks(blocks)]
        if parsed:
            selected = max(parsed, key=lambda blocks: _block_counts(blocks)["text_chars"])
            strategy = "largest_content"

    if not selected:
        selected = _parse_html_blocks_raw(source, base_url)
        strategy = "document_fallback"

    selected, media_report = select_article_media(selected, maximum=maximum_figures)
    counts = _block_counts(selected)
    return selected, {"strategy": strategy, **counts, **media_report}


def parse_html_blocks(html_text, base_url=""):
    blocks, _report = parse_html_blocks_with_report(html_text, base_url)
    return blocks


def _figure_translation_id(block, field):
    digest = hashlib.sha256(
        f"{block.get('id','')}\0{field}\0{block.get(field,'')}".encode("utf-8")
    ).hexdigest()[:12]
    return f"t-{digest}"


def _translation_targets(blocks):
    for block in blocks:
        if block.get("type") == "figure":
            for field in ("caption", "alt"):
                if str(block.get(field) or "").strip():
                    yield _figure_translation_id(block, field), block, field
        else:
            for node in iter_text_nodes(block):
                yield node["id"], node, "text"


def translation_nodes(blocks, maximum_chars=None):
    nodes, used = [], 0
    safe = sanitize_blocks(blocks)
    for node_id, target, field in _translation_targets(safe):
        text = target.get(field, "")
        if not text.strip():
            continue
        if maximum_chars is not None and used + len(text) > maximum_chars:
            remaining = maximum_chars - used
            if remaining <= 0:
                break
            text = text[:remaining]
        nodes.append({"id": node_id, "text": text})
        used += len(text)
    return nodes


def apply_translations(blocks, translated_nodes):
    result = copy.deepcopy(sanitize_blocks(blocks))
    existing = {
        node_id: (target, field)
        for node_id, target, field in _translation_targets(result)
    }
    applied, ignored = 0, 0
    seen = set()
    for translated in translated_nodes if isinstance(translated_nodes, list) else []:
        if not isinstance(translated, dict):
            ignored += 1
            continue
        node_id = str(translated.get("id") or "")
        text = _clean_text(translated.get("text"), 8000)
        if node_id in existing and node_id not in seen and text:
            target, field = existing[node_id]
            target[field] = text
            seen.add(node_id)
            applied += 1
        else:
            ignored += 1
    return sanitize_blocks(result), {"applied": applied, "ignored": ignored, "missing": len(existing) - applied}


def blocks_plain_text(blocks):
    parts = []
    for block in sanitize_blocks(blocks):
        kind = block["type"]
        if kind == "code":
            parts.append(block["text"])
        elif kind == "figure":
            parts.append(block.get("caption") or block.get("alt") or "")
        else:
            parts.append("".join(node["text"] for node in iter_text_nodes(block)).strip())
    return "\n\n".join(part for part in parts if part)


def limit_blocks(blocks, maximum_chars, preserve_types=None):
    preserve_types = set(preserve_types or ())
    result, used, exhausted = [], 0, False
    for block in copy.deepcopy(sanitize_blocks(blocks)):
        if block.get("type") in preserve_types:
            result.append(block)
            continue
        if exhausted:
            continue
        block_chars = sum(len(node.get("text", "")) for node in iter_text_nodes(block))
        if block.get("type") == "code":
            block_chars += len(block.get("text", ""))
        elif block.get("type") == "figure":
            block_chars += len(block.get("caption") or block.get("alt") or "")
        if used + block_chars <= maximum_chars:
            result.append(block)
            used += block_chars
            continue
        remaining = maximum_chars - used
        if remaining <= 0:
            exhausted = True
            continue
        if block.get("type") == "code":
            block["text"] = block.get("text", "")[:remaining]
            cleaned = sanitize_blocks([block])
            if cleaned:
                result.extend(cleaned)
            exhausted = True
            continue
        if block.get("type") == "figure":
            block["caption"] = block.get("caption", "")[:remaining]
            cleaned = sanitize_blocks([block])
            if cleaned:
                result.extend(cleaned)
            exhausted = True
            continue
        for node in iter_text_nodes(block):
            if remaining <= 0:
                node["text"] = ""
                continue
            node["text"] = node.get("text", "")[:remaining]
            remaining -= len(node["text"])
        cleaned = sanitize_blocks([block])
        if cleaned:
            result.extend(cleaned)
        exhausted = True
    return sanitize_blocks(result)


def _render_inlines(nodes):
    rendered = []
    for node in _clean_inlines(nodes):
        value = html.escape(node["text"])
        for mark in node.get("marks", []):
            if mark == "strong":
                value = f"<strong>{value}</strong>"
            elif mark == "em":
                value = f"<em>{value}</em>"
            elif mark == "code":
                value = f"<code>{value}</code>"
            elif isinstance(mark, dict) and mark.get("type") == "color":
                value = f'<span class="tone-{mark["token"]}">{value}</span>'
            elif isinstance(mark, dict) and mark.get("type") == "link":
                href = html.escape(mark["href"], quote=True)
                value = f'<a href="{href}" target="_blank" rel="noopener noreferrer nofollow">{value}</a>'
        rendered.append(value.replace("\n", "<br>"))
    return "".join(rendered)


def render_blocks_html(blocks, render_media=True):
    rendered = []
    for block in sanitize_blocks(blocks):
        kind = block["type"]
        if kind == "heading":
            level = block.get("level", 2)
            rendered.append(f'<h{level} class="cb-heading">{_render_inlines(block["children"])}</h{level}>')
        elif kind == "paragraph":
            rendered.append(f'<p>{_render_inlines(block["children"])}</p>')
        elif kind == "blockquote":
            rendered.append(f'<blockquote>{_render_inlines(block["children"])}</blockquote>')
        elif kind == "list":
            tag = "ol" if block.get("ordered") else "ul"
            items = "".join(f'<li>{_render_inlines(item["children"])}</li>' for item in block["items"])
            rendered.append(f"<{tag}>{items}</{tag}>")
        elif kind == "code":
            language = html.escape(block.get("language", ""), quote=True)
            rendered.append(f'<pre><code class="language-{language}">{html.escape(block["text"])}</code></pre>')
        elif kind == "table":
            rows = []
            for row in block["rows"]:
                cells = ""
                for cell in row["cells"]:
                    tag = "th" if cell.get("header") else "td"
                    spans = "".join(
                        f' {name}="{cell[name]}"'
                        for name in ("rowspan", "colspan") if cell.get(name)
                    )
                    cells += f'<{tag}{spans}>{_render_inlines(cell["children"])}</{tag}>'
                rows.append(f"<tr>{cells}</tr>")
            rendered.append(
                f'<div class="cb-table" role="region" aria-label="原文表格" tabindex="0">'
                f'<table>{"".join(rows)}</table></div>'
            )
        elif kind == "figure":
            original_src = html.escape(block["src"], quote=True)
            source_url = html.escape(block.get("source_url") or block["src"], quote=True)
            cached_src = sanitize_cached_media_path(block.get("cached_src"))
            alt = html.escape(block.get("alt", ""), quote=True)
            caption = html.escape(block.get("caption") or block.get("alt") or "")
            dimensions = ""
            if block.get("width") and block.get("height"):
                dimensions = f' width="{block["width"]}" height="{block["height"]}"'
            if render_media and cached_src:
                visual = (
                    f'<a class="cb-media-link" href="{original_src}" target="_blank" '
                    f'rel="noopener noreferrer nofollow"><img src="{cached_src}" alt="{alt}" '
                    f'loading="lazy" decoding="async"{dimensions}></a>'
                )
            elif render_media:
                visual = '<div class="cb-media-placeholder" role="img" aria-label="图片未缓存">图片未缓存，可前往来源查看</div>'
            else:
                visual = ""
            host = html.escape(urlparse(block.get("source_url") or block["src"]).netloc)
            links = (
                f'<span class="cb-media-source">来源：<a href="{source_url}" target="_blank" '
                f'rel="noopener noreferrer nofollow">{host or "原文"}</a></span>'
                f'<a href="{original_src}" target="_blank" rel="noopener noreferrer nofollow">查看原图 ↗</a>'
            )
            rendered.append(
                f'<figure class="cb-figure">{visual}<figcaption>'
                f'{f"<span>{caption}</span>" if caption else ""}<span class="cb-media-meta">{links}</span>'
                f'</figcaption></figure>'
            )
    return "".join(rendered)
