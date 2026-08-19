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
    "header", "aside", "audio", "video",
}
SKIP_VOID_TAGS = {"input", "embed"}
DANGEROUS_TAGS = SKIP_CONTAINER_TAGS | SKIP_VOID_TAGS
HTML_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
ARTICLE_CONTAINER_SIGNAL_RE = re.compile(
    r"\b(?:article|post|entry|story)(?:\s+(?:body|content|text))?\b|"
    r"\b(?:body|content)\s+(?:article|post|story)\b|"
    r"\b(?:articlebody|rich\s*text|markdown|prose)\b",
    re.I,
)
ARTICLE_CONTAINER_NOISE_RE = re.compile(
    r"\b(?:archive|author|card|carousel|comment|footer|grid|header|hero|index|"
    r"latest|list|nav|newsletter|popular|promo|recommended|related|share|sidebar|teaser)\b",
    re.I,
)
ARTICLE_TAIL_HEADING_RE = re.compile(
    r"^(?:(?:previous|next)(?:\s+(?:article|post|story))?|"
    r"related\s+(?:content|articles?|posts?|stories)|"
    r"recommended(?:\s+(?:reading|articles?|posts?|stories))?|"
    r"you\s+may\s+also\s+like|more\s+from|latest\s+(?:articles?|posts?|stories)|"
    r"share\s+this\s+(?:article|post|story)|popular\s+(?:articles?|posts?)|"
    r"topic\s+hub|about\s+the\s+authors?|"
    r"上一篇(?:文章)?|下一篇(?:文章)?|相关内容|相关博客|相关主题文章|"
    r"相关客户案例|相关解决方案|相关视频|相关产品推荐|产品推荐|主题中心|"
    r"关于作者|作者简介|相关文章|最新文章|相关推荐|推荐阅读|更多文章|分享本文)$",
    re.I,
)
ARTICLE_PRE_TAIL_PROMO_HEADING_RE = re.compile(
    r"^(?:get\s+started(?:\s+(?:in|with)\s+.+)?|start\s+(?:using|building)\s+.+|"
    r"install\s+.+|try\s+.+|join\s+.+|"
    r"开始使用.+|在.+中开始|安装.+|试用.+|加入.+)$",
    re.I,
)
ARTICLE_PROMO_BLOCK_RE = re.compile(
    r"(?:\bdownload\b.{0,80}\b(?:guide|report|ebook|whitepaper|roadmap)\b|"
    r"\b(?:guide|report|ebook|whitepaper)\b.{0,80}\bdownload\b|"
    r"\b(?:sign\s*up|register|book\s+a\s+demo|contact\s+sales)\b|"
    r"下载.{0,40}(?:指南|报告|电子书|白皮书|路线图)|"
    r"(?:指南|报告|电子书|白皮书).{0,40}下载|注册|预约演示|联系销售)",
    re.I,
)
ARTICLE_TERMINAL_PROMO_RE = re.compile(
    r"^(?:get\s+started\s+(?:with|using|on)\s+.+|try\s+.+(?:today|now)|"
    r"start\s+(?:using|building)\s+.+(?:today|now)|"
    r"(?:立即|现在)?开始使用.+|(?:立即|现在)?试用.+)[.!。！]?$",
    re.I,
)
ARTICLE_BYLINE_RE = re.compile(
    r"^(?:.{0,80}\b(?:last\s+(?:edited|updated)(?:\s+on)?|"
    r"updated\s+(?:on|at)|published\s+(?:on|at))\b|"
    r"by\s+[A-Z][\w.'’-]+|.{0,40}最后(?:编辑|更新)(?:于|时间)?|"
    r"更新于|发布于|作者\s*[：:])",
    re.I,
)
ARTICLE_DATE_META_RE = re.compile(
    r"^\d{4}(?:[-/.]\d{1,2}(?:[-/.]\d{1,2})?|年\d{1,2}月(?:\d{1,2}日)?)"
    r"(?:\s*[|·•]\s*[^|·•]{1,60})?$",
    re.I,
)
ARTICLE_HEAD_UI_RE = re.compile(
    r"^(?:share\s+this\s+(?:article|post|story)|分享本文|"
    r"subscribe|follow|订阅|关注|"
    r"copied\s+to\s+(?:the\s+)?clipboard|已复制到剪贴板)$",
    re.I,
)
ARTICLE_UI_BLOCK_RE = re.compile(
    r"^(?:item\s+not\s+found\.?|未找到项目[。.]?|"
    r"(?:previous|next)(?:\s+(?:article|post|story))?|"
    r"上一页|下一页|上一篇(?:文章)?|下一篇(?:文章)?|"
    r"\d+\s*/\s*\d+|e-?books?|电子书|faq|常见问题)$",
    re.I,
)
ARTICLE_POLLUTION_RE = re.compile(
    r"^(?:item\s+not\s+found\.?|未找到项目[。.]?|"
    r"(?:previous|next)(?:\s+(?:article|post|story))?|"
    r"上一页|下一页|上一篇(?:文章)?|下一篇(?:文章)?|"
    r"\d+\s*/\s*\d+|related\s+(?:content|articles?|posts?|stories)|"
    r"相关内容|相关博客|相关主题文章|相关客户案例|相关解决方案|相关视频|"
    r"相关产品推荐|相关文章|相关推荐|"
    r"view\s+pricing|查看定价|contact\s+sales|联系销售|"
    r"get\s+(?:the\s+)?developer\s+newsletter|获取开发者通讯|"
    r"thanks?!?\s+you(?:'|’)re\s+subscribed\.?|谢谢！?您已订阅[。.]?|"
    r"sorry,?\s+there\s+was\s+a\s+problem[^.]*\.?|"
    r"抱歉，?提交时出现问题[^。]*[。.]?)$",
    re.I,
)
SOURCE_UI_CONTAINER_RE = re.compile(
    r"(?:^|\s)(?:article\s+)?(?:audio|podcast|media)\s+(?:player|controls?|widget)(?:\s|$)|"
    r"(?:^|\s)(?:reading|bookmark)\s+list(?:\s|$)",
    re.I,
)
SOURCE_ARTICLE_CHROME_CONTAINER_RE = re.compile(
    r"(?:^|\s)(?:article|post)\s+(?:footer|navigation|recommendations?)(?:\s|$)|"
    r"(?:^|\s)(?:related|recommended|recommendations?|recirculation)\s+"
    r"(?:content|articles?|posts?|stories|cards?|list|section)(?:\s|$)|"
    r"(?:^|\s)(?:next|previous)\s+(?:article|post|story)(?:\s|$)|"
    r"(?:^|\s)(?:topic\s+hub|newsletter\s+(?:signup|form)|author\s+(?:bio|card)|"
    r"product\s+recommendations?|social\s+share)(?:\s|$)",
    re.I,
)
ARTICLE_AUDIO_UI_LISTEN_RE = re.compile(
    r"^(?:listen\s+to\s+(?:this\s+)?(?:article|post|story)|"
    r"收听(?:本文|这篇文章|文章)|听(?:本文|这篇文章))"
    r"(?:\s*[-–—:：]\s*\d{1,2}:\d{2})?$",
    re.I,
)
ARTICLE_AUDIO_UI_STATUS_RE = re.compile(
    r"^(?:audio\s+(?:is\s+)?ready(?:\s+to\s+play)?|"
    r"音频(?:已)?准备(?:好播放|就绪|完成)|音频已准备好)$",
    re.I,
)
ARTICLE_AUDIO_UI_UNSUPPORTED_RE = re.compile(
    r"^(?:your\s+browser\s+(?:does\s+not|doesn't)\s+support\s+"
    r"(?:the\s+)?audio(?:\s+element)?|"
    r"(?:您|你)的浏览器不支持音频(?:元素)?)$",
    re.I,
)
ARTICLE_AUDIO_UI_TIME_RE = re.compile(
    r"^\d{1,3}:\d{2}(?:\s*/\s*\d{1,3}:\d{2})?$"
)
ARTICLE_AUDIO_UI_LIST_RE = re.compile(
    r"^(?:reading\s+list|my\s+reading\s+list|bookmarks?|阅读列表|书签)$",
    re.I,
)
ARTICLE_META_LABELS = (
    re.compile(r"(?:\bcategory\b|类别\s*[：:])", re.I),
    re.compile(r"(?:\bproduct\b|产品\s*[：:])", re.I),
    re.compile(r"(?:\bdate\b|日期\s*[：:])", re.I),
    re.compile(r"(?:reading\s*time|阅读时间)", re.I),
    re.compile(r"(?:copy\s*link|复制链接)", re.I),
    re.compile(r"(?:\bshare\b|分享(?:\s*[：:]|复制链接))", re.I),
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
            if not block["children"] or not any(
                str(child.get("text") or "").strip() for child in block["children"]
            ):
                continue
        elif kind == "list":
            block["ordered"] = bool(raw.get("ordered"))
            block["items"] = []
            for item in raw.get("items", []) if isinstance(raw.get("items"), list) else []:
                children = _clean_inlines(
                    item.get("children", []) if isinstance(item, dict) else item,
                    base_url,
                )
                if children and any(str(child.get("text") or "").strip() for child in children):
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
                    if children and any(str(child.get("text") or "").strip() for child in children):
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
    """Return balanced container slices and enough ancestry data to compare focus."""
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
                    "start": opened["start"],
                    "end": match.end(),
                    "depth": opened["depth"],
                })
            continue
        if tag not in HTML_VOID_TAGS and not attrs.rstrip().endswith("/"):
            stack.append({
                "tag": tag,
                "attrs": attrs,
                "start": match.start(),
                "depth": len(stack),
            })
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


def _container_semantics(attrs):
    """Return standardized article signals from class/id/role/itemprop attributes."""
    values = []
    for match in re.finditer(
        r"(?is)\b(?:class|id|role|itemprop)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
        str(attrs or ""),
    ):
        values.append(next((part for part in match.groups() if part is not None), ""))
    normalized = re.sub(r"[^a-z0-9]+", " ", " ".join(values).casefold()).strip()
    return {
        "normalized": normalized,
        "article": bool(ARTICLE_CONTAINER_SIGNAL_RE.search(normalized)),
        "noise": bool(ARTICLE_CONTAINER_NOISE_RE.search(normalized)),
    }


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


def _block_plain_text(block):
    return re.sub(r"\s+", " ", blocks_plain_text([block])).strip()


def _block_links(block):
    links = []
    for node in iter_text_nodes(block):
        for mark in node.get("marks", []):
            if isinstance(mark, dict) and mark.get("type") == "link" and mark.get("href"):
                links.append(str(mark["href"]))
    return list(dict.fromkeys(links))


def _block_link_ratio(block):
    text_chars = len(_block_plain_text(block))
    linked_chars = 0
    for node in iter_text_nodes(block):
        if any(isinstance(mark, dict) and mark.get("type") == "link" for mark in node.get("marks", [])):
            linked_chars += len(str(node.get("text") or ""))
    return linked_chars / max(1, text_chars)


def _normalized_ui_text(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    return value.strip(" \t\r\n.,!?;:，。！？；：()（）[]【】")


def _source_ui_container(attrs):
    """Recognize player/list widgets from semantics, without source URL rules."""
    values = []
    for key in ("class", "id", "role", "aria-label", "data-testid", "data-component"):
        value = attrs.get(key)
        if value:
            values.append(str(value))
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", " ".join(values))
    normalized = re.sub(r"[^a-z0-9]+", " ", raw.casefold()).strip()
    return bool(SOURCE_UI_CONTAINER_RE.search(normalized))


def _source_article_chrome_container(attrs):
    """Recognize nested article-page components, independent of publisher names."""
    values = []
    for key in ("class", "id", "role", "aria-label", "data-testid", "data-component"):
        value = attrs.get(key)
        if value:
            values.append(str(value))
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", " ".join(values))
    normalized = re.sub(r"[^a-z0-9]+", " ", raw.casefold()).strip()
    return bool(SOURCE_ARTICLE_CHROME_CONTAINER_RE.search(normalized))


def _article_audio_ui_role(block):
    text = _normalized_ui_text(_block_plain_text(block))
    if not text:
        return "blank"
    if ARTICLE_AUDIO_UI_LISTEN_RE.fullmatch(text):
        return "listen"
    if ARTICLE_AUDIO_UI_STATUS_RE.fullmatch(text):
        return "status"
    if ARTICLE_AUDIO_UI_UNSUPPORTED_RE.fullmatch(text):
        return "unsupported"
    if ARTICLE_AUDIO_UI_TIME_RE.fullmatch(text):
        return "time"
    if ARTICLE_AUDIO_UI_LIST_RE.fullmatch(text):
        return "reading_list"
    if any("/showbookmarks.action" in href.casefold() for href in _block_links(block)):
        return "reading_list"
    return ""


def strip_article_ui_chrome(blocks):
    """Remove a proven embedded player UI cluster while retaining article prose.

    Individual keywords are never deleted. A cluster needs multiple independent
    player signals (label/status/fallback plus time or reading-list controls), so
    articles that discuss audio players remain intact.
    """
    safe = sanitize_blocks(blocks)
    roles = [_article_audio_ui_role(block) for block in safe]
    removed = set()
    components = 0
    primary_roles = {"listen", "status", "unsupported"}
    for index, role in enumerate(roles):
        if role not in primary_roles:
            continue
        start, end = max(0, index - 4), min(len(safe), index + 9)
        window = [(offset, roles[offset]) for offset in range(start, end) if roles[offset]]
        role_set = {value for _offset, value in window if value != "blank"}
        ui_offsets = {offset for offset, value in window if value != "blank"}
        proven = bool(
            len(ui_offsets) >= 3
            and len(role_set & primary_roles) >= 2
            and role_set & {"time", "reading_list"}
        )
        if not proven:
            continue
        before = len(removed)
        removed.update(ui_offsets)
        if len(removed) > before:
            components += 1
    filtered = [block for index, block in enumerate(safe) if index not in removed]
    return sanitize_blocks(filtered), {
        "trimmed_embedded_ui_blocks": len(removed),
        "embedded_ui_components": components,
    }


def strip_article_ui_text(value):
    """Apply the same contextual player cleanup to legacy paragraph text."""
    paragraphs = [
        part.strip()
        for part in re.split(r"(?:\r?\n){2,}", str(value or ""))
        if part.strip()
    ]
    blocks = sanitize_blocks([
        {"type": "paragraph", "children": [{"type": "text", "text": part, "marks": []}]}
        for part in paragraphs
    ])
    cleaned, report = strip_article_ui_chrome(blocks)
    return blocks_plain_text(cleaned), report


def _title_key(value):
    value = re.sub(r"^[\s/\\|>›»·•:：-]+", "", str(value or "")).casefold()
    return re.sub(r"[^\w\u3400-\u9fff]+", "", value)


def _looks_like_author_portrait(block, next_text=""):
    if block.get("type") != "figure" or not ARTICLE_BYLINE_RE.search(str(next_text or "")):
        return False
    if str(block.get("alt") or "").strip() or str(block.get("caption") or "").strip():
        return False
    width, height = int(block.get("width", 0) or 0), int(block.get("height", 0) or 0)
    return bool(width and height and 0.75 <= width / max(1, height) <= 1.33 and max(width, height) <= 900)


def _looks_like_byline(block):
    text = _block_plain_text(block).strip(" \t\r\n:：")
    return bool(
        0 < len(text) <= 240
        and (ARTICLE_BYLINE_RE.search(text) or ARTICLE_DATE_META_RE.fullmatch(text))
    )


def _leading_title_followed_by_byline(blocks):
    """Identify a source-page title/byline cluster at the start of a candidate.

    Focused article containers often begin with the publisher's title followed by
    an optional author portrait and a byline/dateline.  The title is useful while
    selecting the article but is duplicate page chrome in DataHot's reading view.
    Requiring an explicit byline signal prevents ordinary opening headings from
    being removed.
    """
    if not blocks or blocks[0].get("type") != "heading":
        return False
    cursor = 1
    if cursor < len(blocks) and blocks[cursor].get("type") == "figure":
        next_text = _block_plain_text(blocks[cursor + 1]) if cursor + 1 < len(blocks) else ""
        if _looks_like_author_portrait(blocks[cursor], next_text):
            cursor += 1
    return cursor < len(blocks) and _looks_like_byline(blocks[cursor])


def _leading_article_chrome_cut(blocks):
    head_cut = 0
    prefix_chars = 0
    for index, block in enumerate(blocks[:24]):
        if block.get("type") not in {"list", "paragraph"}:
            prefix_chars += len(_block_plain_text(block))
            continue
        text = _block_plain_text(block)
        if prefix_chars <= 1200 and sum(bool(pattern.search(text)) for pattern in ARTICLE_META_LABELS) >= 4:
            head_cut = index + 1
            break
        prefix_chars += len(text)

    # Some publishers flatten title, author/date and share controls into sibling
    # blocks.  A share/copy control before any meaningful prose is the reliable
    # end of that page header, regardless of how those blocks are styled.
    prefix_chars = 0
    for index, block in enumerate(blocks[:12]):
        text = _block_plain_text(block).strip(" \t\r\n:：")
        if prefix_chars <= 800 and ARTICLE_HEAD_UI_RE.fullmatch(text):
            head_cut = max(head_cut, index + 1)
            while (
                head_cut < min(len(blocks), 12)
                and ARTICLE_HEAD_UI_RE.fullmatch(
                    _block_plain_text(blocks[head_cut]).strip(" \t\r\n:：")
                )
            ):
                head_cut += 1
            break
        prefix_chars += len(text)

    for index, block in enumerate(blocks[:7]):
        if block.get("type") != "heading" or index == 0:
            continue
        title = _title_key(_block_plain_text(block))
        previous = blocks[:index]
        breadcrumbish = all(
            candidate.get("type") in {"paragraph", "list"}
            and len(_block_plain_text(candidate)) <= 180
            and (
                re.match(r"^[\s/\\|>›»·•:：-]", _block_plain_text(candidate))
                or _block_link_ratio(candidate) >= 0.2
                or len(_block_links(candidate)) >= 2
            )
            for candidate in previous
        )
        previous_titles = [_title_key(_block_plain_text(candidate)) for candidate in previous]
        if title and breadcrumbish and any(
            candidate_title == title or candidate_title.endswith(title)
            for candidate_title in previous_titles
        ):
            head_cut = max(head_cut, index + 1)
            break

    # A focused content container may have already excluded the site navigation
    # and breadcrumb, leaving only title -> byline/date -> body.  Treat that
    # explicit cluster as article-page metadata, not as the opening of the prose.
    if head_cut == 0 and _leading_title_followed_by_byline(blocks):
        head_cut = 1

    cursor = head_cut
    if cursor < len(blocks) and blocks[cursor].get("type") == "figure":
        next_text = _block_plain_text(blocks[cursor + 1]) if cursor + 1 < len(blocks) else ""
        if _looks_like_author_portrait(blocks[cursor], next_text):
            cursor += 1
    while cursor < len(blocks) and _looks_like_byline(blocks[cursor]):
        cursor += 1
    return cursor


def _repeated_promotional_indices(blocks):
    by_link, by_text = {}, {}
    eligible = set()
    for index, block in enumerate(blocks):
        text = _block_plain_text(block).strip(" \t\r\n:：")
        if not text or len(text) > 240 or not ARTICLE_PROMO_BLOCK_RE.search(text):
            continue
        eligible.add(index)
        for href in _block_links(block):
            by_link.setdefault(href, []).append(index)
        by_text.setdefault(_title_key(text), []).append(index)
    repeated = set()
    for indices in list(by_link.values()) + list(by_text.values()):
        if len(set(indices)) >= 2:
            repeated.update(indices)
    return repeated & eligible


def _trim_terminal_promotions(blocks):
    """Remove only explicit, linked conversion copy at the very end of an article."""
    trimmed = list(blocks)
    removed = 0
    while trimmed:
        block = trimmed[-1]
        text = _block_plain_text(block).strip(" \t\r\n:：")
        if not (
            block.get("type") == "paragraph"
            and 0 < len(text) <= 180
            and _block_links(block)
            and _block_link_ratio(block) >= 0.15
            and ARTICLE_TERMINAL_PROMO_RE.fullmatch(text)
        ):
            break
        trimmed.pop()
        removed += 1
    return trimmed, removed


def trim_article_blocks(blocks, minimum_chars=400):
    """Cut deterministic source-site chrome that follows a meaningful article.

    The boundary is intentionally conservative: exact UI copy or a known related-
    content heading only becomes a stop marker after enough article text has been
    observed.  This keeps legitimate mentions inside short articles while removing
    recommendation carousels, newsletter forms and other source-page components.
    """
    safe = sanitize_blocks(blocks)
    text_chars = 0
    boundary_index = None
    boundary_marker = ""
    boundary_start_marker = ""
    for index, block in enumerate(safe):
        text = _block_plain_text(block)
        normalized = text.strip(" \t\r\n:：")
        # Source sites frequently render component labels as plain paragraphs.
        # Exact component copy is therefore stronger evidence than the HTML tag.
        is_heading_boundary = bool(ARTICLE_TAIL_HEADING_RE.fullmatch(normalized))
        is_ui_boundary = bool(ARTICLE_UI_BLOCK_RE.fullmatch(normalized))
        if text_chars >= minimum_chars and (is_heading_boundary or is_ui_boundary):
            boundary_index = index
            boundary_marker = normalized[:120]
            if is_heading_boundary:
                for earlier in range(max(0, index - 8), index):
                    earlier_text = _block_plain_text(safe[earlier]).strip(" \t\r\n:：")
                    between = safe[earlier:index]
                    if (
                        safe[earlier].get("type") == "heading"
                        and ARTICLE_PRE_TAIL_PROMO_HEADING_RE.fullmatch(earlier_text)
                        and sum(len(_block_plain_text(item)) for item in safe[:earlier]) >= minimum_chars
                        and all(len(_block_plain_text(item)) <= 320 for item in between)
                    ):
                        boundary_index = earlier
                        boundary_start_marker = earlier_text[:120]
                        break
            break
        text_chars += len(text)

    tail_trimmed = safe if boundary_index is None else safe[:boundary_index]
    head_cut = _leading_article_chrome_cut(tail_trimmed)
    body, embedded_ui = strip_article_ui_chrome(tail_trimmed[head_cut:])
    promotional_indices = _repeated_promotional_indices(body)
    trimmed = [block for index, block in enumerate(body) if index not in promotional_indices]
    trimmed, terminal_promotions = _trim_terminal_promotions(trimmed)
    findings = []
    for block in trimmed:
        text = _block_plain_text(block).strip(" \t\r\n:：")
        if text and (
            ARTICLE_POLLUTION_RE.fullmatch(text)
            or ARTICLE_TAIL_HEADING_RE.fullmatch(text)
        ):
            findings.append(text[:120])
    evidence = []
    if head_cut:
        evidence.append("head_boundary")
    if boundary_index is not None:
        evidence.append("tail_boundary")
    if promotional_indices:
        evidence.append("repeated_promotion_removed")
    if terminal_promotions:
        evidence.append("terminal_promotion_removed")
    if embedded_ui["trimmed_embedded_ui_blocks"]:
        evidence.append("embedded_ui_removed")
    text_total = len(blocks_plain_text(trimmed))
    if text_total >= minimum_chars and _linked_text_chars(trimmed) / max(1, text_total) <= 0.35:
        evidence.append("prose_density")
    return sanitize_blocks(trimmed), {
        "quality_status": "pass" if not findings else "suspect",
        "quality_flags": list(dict.fromkeys(findings))[:8],
        "quality_evidence": evidence,
        "trimmed_tail_blocks": len(safe) - len(tail_trimmed),
        "trimmed_head_blocks": head_cut,
        "trimmed_promotional_blocks": len(promotional_indices) + terminal_promotions,
        "trimmed_embedded_ui_blocks": embedded_ui["trimmed_embedded_ui_blocks"],
        "embedded_ui_components": embedded_ui["embedded_ui_components"],
        "boundary_marker": boundary_marker,
        "boundary_start_marker": boundary_start_marker,
    }


def _linked_text_chars(blocks):
    total = 0
    for node in iter_text_nodes(blocks):
        if any(isinstance(mark, dict) and mark.get("type") == "link" for mark in node.get("marks", [])):
            total += len(node.get("text", ""))
    return total


def _candidate_integrity(blocks, quality):
    """Apply non-compensating gates before candidates are allowed to compete."""
    quality = dict(quality or {})
    flags = list(quality.get("quality_flags") or [])
    evidence = list(quality.get("quality_evidence") or [])
    text_chars = len(blocks_plain_text(blocks))
    link_ratio = _linked_text_chars(blocks) / max(1, text_chars)
    texts = [
        _title_key(_block_plain_text(block))
        for block in blocks
        if len(_block_plain_text(block)) >= 8
    ]
    duplicate_blocks = len(texts) - len(set(texts))
    duplicate_ratio = duplicate_blocks / max(1, len(texts))
    if link_ratio > 0.42:
        flags.append("link_density_high")
    if duplicate_blocks >= 3 and duplicate_ratio >= 0.12:
        flags.append("repeated_block_content")
    if not flags and text_chars >= 400:
        evidence.append("integrity_gate")
    quality.update({
        "quality_status": "pass" if not flags else "suspect",
        "quality_flags": list(dict.fromkeys(flags))[:8],
        "quality_evidence": list(dict.fromkeys(evidence)),
        "link_ratio": round(link_ratio, 4),
        "duplicate_blocks": duplicate_blocks,
        "duplicate_ratio": round(duplicate_ratio, 4),
    })
    return quality


def _candidate_signature(blocks):
    return hashlib.sha256(
        json.dumps(_without_ids(sanitize_blocks(blocks)), ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _candidate_score(strategy, blocks, quality, *, depth=0, focus_ratio=1.0):
    """Reward focused article semantics without rewarding a whole-page text dump."""
    base = {
        "semantic_container": 720,
        "article": 640,
        "jsonld_article_body": 520,
        "nested_content": 340,
        "main": 260,
        "largest_content": 120,
        "document_fallback": 0,
    }.get(strategy, 0)
    counts = _block_counts(blocks)
    text_chars = counts["text_chars"]
    structural = (
        sum(block.get("type") == "heading" for block in blocks) * 12
        + counts["tables"] * 40
        + counts["figures"] * 10
    )
    link_ratio = _linked_text_chars(blocks) / max(1, text_chars)
    suspect_penalty = 600 if quality.get("quality_status") != "pass" else 0
    raw_blocks = max(len(blocks), int(quality.get("raw_blocks", len(blocks)) or len(blocks)))
    removed_blocks = (
        int(quality.get("trimmed_head_blocks", 0) or 0)
        + int(quality.get("trimmed_tail_blocks", 0) or 0)
        + int(quality.get("trimmed_promotional_blocks", 0) or 0)
    )
    trim_penalty = min(320, removed_blocks / max(1, raw_blocks) * 480)
    focus_bonus = 0
    if strategy == "nested_content":
        if 0.45 <= focus_ratio <= 0.97:
            focus_bonus = 180
        elif 0.25 <= focus_ratio < 0.45:
            focus_bonus = 40
        elif focus_ratio < 0.25:
            focus_bonus = -180
        elif focus_ratio > 0.985:
            focus_bonus = -40
        focus_bonus += min(80, max(0, int(depth)) * 8)
    return round(
        base + min(360, text_chars / 12) + min(120, structural)
        + focus_bonus - min(240, link_ratio * 480) - trim_penalty - suspect_penalty,
        2,
    )


def select_article_media(blocks, maximum=None):
    """Drop decorative media and keep explanatory figures in source order.

    ``maximum`` remains available for bounded callers, but article extraction keeps
    every useful figure by default.  The media cache applies its own download cap;
    figures beyond that cap remain visible as safe source links instead of vanishing.
    """
    safe = sanitize_blocks(blocks)
    candidates, seen, rejected = [], set(), {}
    for index, block in enumerate(safe):
        if block.get("type") != "figure":
            continue
        parsed = urlparse(block.get("src", ""))
        identity = (parsed.netloc.casefold(), parsed.path.rstrip("/").casefold())
        descriptor = " ".join((block.get("src", ""), block.get("alt", ""), block.get("caption", "")))
        width, height = int(block.get("width", 0)), int(block.get("height", 0))
        next_text = _block_plain_text(safe[index + 1]) if index + 1 < len(safe) else ""
        if identity in seen:
            rejected[index] = "duplicate"
            continue
        if DECORATIVE_IMAGE_RE.search(descriptor):
            rejected[index] = "decorative"
            continue
        if _looks_like_author_portrait(block, next_text):
            rejected[index] = "author"
            continue
        if width and height and (width < 240 or height < 120):
            rejected[index] = "small"
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
        limit = max(0, int(maximum))
        for _score, index in ranked[limit:]:
            rejected[index] = "limit"
        ranked = ranked[:limit]
    selected = {index for _score, index in ranked}
    filtered = [
        block for index, block in enumerate(safe)
        if block.get("type") != "figure" or index in selected
    ]
    report = {
        "figures_discovered": sum(block.get("type") == "figure" for block in safe),
        "figures_selected": len(selected),
        "figures_rejected": sum(block.get("type") == "figure" for block in safe) - len(selected),
    }
    for reason in ("author", "decorative", "duplicate", "small", "limit"):
        report[f"figures_rejected_{reason}"] = sum(value == reason for value in rejected.values())
    return sanitize_blocks(filtered), report


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
            if tag not in HTML_VOID_TAGS:
                self.skip_stack.append(tag)
            return
        if tag in SKIP_VOID_TAGS:
            return
        if tag in SKIP_CONTAINER_TAGS:
            self._flush_current()
            self.skip_stack.append(tag)
            return
        if tag in {"div", "section"} and (
            _source_ui_container(attrs) or _source_article_chrome_container(attrs)
        ):
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
    semantic_regions = [
        region for region in regions
        if region["tag"] in {"div", "section"}
        and _container_semantics(region["attrs"])["article"]
        and not _container_semantics(region["attrs"])["noise"]
    ]
    article_regions = [region for region in regions if region["tag"] == "article"]
    main_regions = [region for region in regions if region["tag"] == "main"]
    primary_region_keys = {
        (region.get("start"), region.get("end"))
        for region in semantic_regions + article_regions + main_regions
    }
    nested_regions = sorted(
        (
            region for region in regions
            if region["tag"] in {"div", "section"}
            and (region.get("start"), region.get("end")) not in primary_region_keys
            and _rough_text_length(region["html"]) >= 400
        ),
        key=lambda region: _rough_text_length(region["html"]),
        reverse=True,
    )[:24]
    has_primary_root = bool(semantic_regions or article_regions or main_regions)
    strategies = [
        ("semantic_container", sorted(semantic_regions, key=lambda region: _rough_text_length(region["html"]), reverse=True)[:16]),
        ("article", article_regions),
        ("main", main_regions),
        ("nested_content" if has_primary_root else "largest_content", nested_regions),
    ]
    broad_regions = main_regions or article_regions or semantic_regions or nested_regions
    broad_raw_text_chars = max(
        (_rough_text_length(region["html"]) for region in broad_regions),
        default=max(1, _rough_text_length(source)),
    )
    candidate_pool = []
    for name, strategy_regions in strategies:
        for candidate in strategy_regions:
            parsed = _parse_html_blocks_raw(candidate["html"], base_url)
            trimmed, quality = trim_article_blocks(parsed)
            if _meaningful_blocks(trimmed):
                raw_counts = _block_counts(parsed)
                quality = _candidate_integrity(trimmed, {
                    **quality,
                    "raw_blocks": raw_counts["blocks"],
                    "raw_text_chars": raw_counts["text_chars"],
                })
                focus_ratio = min(1.0, raw_counts["text_chars"] / max(1, broad_raw_text_chars))
                candidate_pool.append({
                    "strategy": name,
                    "blocks": trimmed,
                    "quality": quality,
                    "score": _candidate_score(
                        name, trimmed, quality,
                        depth=candidate.get("depth", 0), focus_ratio=focus_ratio,
                    ),
                    "tag": candidate.get("tag", ""),
                    "depth": max(0, int(candidate.get("depth", 0) or 0)),
                    "focus_ratio": focus_ratio,
                    "raw_counts": raw_counts,
                    "signature": _candidate_signature(trimmed),
                })

    for parsed in (_text_to_blocks(body) for body in _jsonld_article_bodies(source)):
        trimmed, quality = trim_article_blocks(parsed)
        if _meaningful_blocks(trimmed):
            raw_counts = _block_counts(parsed)
            quality = _candidate_integrity(trimmed, {
                **quality,
                "raw_blocks": raw_counts["blocks"],
                "raw_text_chars": raw_counts["text_chars"],
            })
            focus_ratio = min(1.0, raw_counts["text_chars"] / max(1, broad_raw_text_chars))
            candidate_pool.append({
                "strategy": "jsonld_article_body",
                "blocks": trimmed,
                "quality": quality,
                "score": _candidate_score(
                    "jsonld_article_body", trimmed, quality, focus_ratio=focus_ratio,
                ),
                "tag": "jsonld",
                "depth": 0,
                "focus_ratio": focus_ratio,
                "raw_counts": raw_counts,
                "signature": _candidate_signature(trimmed),
            })

    raw_candidate_count = len(candidate_pool)
    unique_candidates = {}
    for candidate in candidate_pool:
        signature = candidate["signature"]
        current = unique_candidates.get(signature)
        if current is None or candidate["score"] > current["score"]:
            unique_candidates[signature] = candidate
    candidate_pool = list(unique_candidates.values())
    quality_candidates = [
        candidate for candidate in candidate_pool
        if candidate["quality"].get("quality_status") == "pass"
    ]
    selection_pool = quality_candidates or candidate_pool
    if candidate_pool:
        chosen = max(selection_pool, key=lambda candidate: candidate["score"])
        selected = chosen["blocks"]
        strategy = chosen["strategy"]
        quality = chosen["quality"]
        selected_score = chosen["score"]
        selected_tag = chosen["tag"]
        selected_depth = chosen["depth"]
        focus_ratio = chosen["focus_ratio"]
        raw_counts = chosen["raw_counts"]
    else:
        parsed = _parse_html_blocks_raw(source, base_url)
        selected, quality = trim_article_blocks(parsed)
        raw_counts = _block_counts(parsed)
        quality = _candidate_integrity(selected, {
            **quality,
            "raw_blocks": raw_counts["blocks"],
            "raw_text_chars": raw_counts["text_chars"],
        })
        strategy = "document_fallback"
        selected_score = _candidate_score(strategy, selected, quality)
        selected_tag = "document"
        selected_depth = 0
        focus_ratio = 1.0

    selection_evidence = list(quality.get("quality_evidence") or [])
    strategy_evidence = {
        "semantic_container": "semantic_container",
        "article": "article_element",
        "nested_content": "nested_focus",
        "largest_content": "largest_content",
        "jsonld_article_body": "jsonld_article_body",
        "main": "main_container",
    }.get(strategy)
    if strategy_evidence:
        selection_evidence.append(strategy_evidence)
    selection_evidence = list(dict.fromkeys(selection_evidence))
    if quality.get("quality_status") == "pass" and not selection_evidence:
        quality = {
            **quality,
            "quality_status": "suspect",
            "quality_flags": ["boundary_evidence_missing"],
        }

    selected, media_report = select_article_media(selected, maximum=maximum_figures)
    counts = _block_counts(selected)
    broad_raw_blocks = max(
        (candidate["raw_counts"]["blocks"] for candidate in candidate_pool),
        default=raw_counts["blocks"],
    )
    return selected, {
        "strategy": strategy,
        "candidate_count": len(candidate_pool),
        "candidate_count_raw": raw_candidate_count,
        "candidate_duplicates": max(0, raw_candidate_count - len(candidate_pool)),
        "candidate_quality_rejected": max(0, len(candidate_pool) - len(quality_candidates)),
        "selected_score": selected_score,
        "selected_tag": selected_tag,
        "selected_depth": selected_depth,
        "selected_raw_blocks": raw_counts["blocks"],
        "selected_raw_text_chars": raw_counts["text_chars"],
        "broad_raw_blocks": broad_raw_blocks,
        "broad_raw_text_chars": broad_raw_text_chars,
        "parent_extra_blocks": max(0, broad_raw_blocks - raw_counts["blocks"]),
        "focus_ratio": round(focus_ratio, 4),
        "selection_evidence": selection_evidence,
        **quality,
        **counts,
        **media_report,
    }


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
        if str(target.get(field) or "").strip()
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
            cached_src = sanitize_cached_media_path(block.get("cached_src"))
            if not render_media or not cached_src or block.get("media_status") != "cached":
                continue
            original_src = html.escape(block["src"], quote=True)
            alt = html.escape(block.get("alt", ""), quote=True)
            dimensions = ""
            if block.get("width") and block.get("height"):
                dimensions = f' width="{block["width"]}" height="{block["height"]}"'
            visual = (
                f'<a class="cb-media-link" href="{original_src}" target="_blank" '
                f'rel="noopener noreferrer nofollow"><img src="{cached_src}" alt="{alt}" '
                f'loading="lazy" decoding="async"{dimensions}></a>'
            )
            rendered.append(f'<figure class="cb-figure">{visual}</figure>')
    return "".join(rendered)
