#!/usr/bin/env python3
"""Build deterministic, bounded scripts for DataHot article narration."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Iterable

from content_blocks import sanitize_blocks


TEXT_VERSION = "tts-text-v1"
DEFAULT_MAX_CHARACTERS = 350
MIN_SEGMENT_CHARACTERS = 18

URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https?://)?[^)]+\)")
HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
LEADING_REASON_RE = re.compile(r"^\s*推荐理由\s*[:：]\s*")
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
SENTENCE_BREAKS = "。！？；.!?;"
CLAUSE_BREAKS = "，、：,"


def clean_tts_text(value: object) -> str:
    """Remove markup and URL noise while retaining readable punctuation."""
    text = html.unescape(str(value or "")).replace("\x00", " ")
    text = FENCE_RE.sub(" ", text)
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = URL_RE.sub(" ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = text.replace("`", "").replace("#", "")
    text = SPACE_RE.sub(" ", text).strip(" \t\r\n-|_")
    return text


def _nodes_text(nodes: object) -> str:
    if not isinstance(nodes, list):
        return ""
    return clean_tts_text("".join(
        str(node.get("text") or "")
        for node in nodes
        if isinstance(node, dict) and node.get("type") == "text"
    ))


def _structured_candidates(event: dict) -> Iterable[str]:
    items = event.get("items") if isinstance(event.get("items"), list) else []
    base_url = str(items[0].get("link") or "") if items and isinstance(items[0], dict) else ""
    blocks = sanitize_blocks(event.get("content_blocks", []), base_url)
    for block in blocks:
        kind = block.get("type")
        if kind in {"heading", "paragraph", "blockquote"}:
            text = _nodes_text(block.get("children"))
            if text:
                yield text
        elif kind == "list":
            parts = [
                _nodes_text(item.get("children"))
                for item in block.get("items", [])
                if isinstance(item, dict)
            ]
            text = clean_tts_text("；".join(part for part in parts if part))
            if text:
                yield text


def _legacy_candidates(event: dict) -> Iterable[str]:
    raw = FENCE_RE.sub(" ", str(event.get("full_zh") or ""))
    for paragraph in re.split(r"\n\s*\n|\n(?=##?\s)", raw):
        paragraph = re.sub(r"^\s*#{1,6}\s*", "", paragraph)
        if paragraph.lstrip().startswith(("|", "【免责声明", "免责声明")):
            continue
        text = clean_tts_text(paragraph)
        if text:
            yield text


def _fingerprint(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def _is_duplicate(candidate: str, accepted: list[str]) -> bool:
    current = _fingerprint(candidate)
    if not current:
        return True
    for value in accepted:
        prior = _fingerprint(value)
        if current == prior:
            return True
        shorter, longer = sorted((current, prior), key=len)
        if len(shorter) >= 24 and shorter in longer:
            return True
    return False


def _clip_sentence(text: str, maximum: int, allow_fragment: bool = False) -> str:
    if len(text) <= maximum:
        return text
    if maximum < MIN_SEGMENT_CHARACTERS:
        return ""
    window = text[:maximum]
    split_at = max(window.rfind(mark) for mark in SENTENCE_BREAKS)
    if split_at >= max(MIN_SEGMENT_CHARACTERS, maximum // 2):
        return window[:split_at + 1].strip()
    clause_at = max(window.rfind(mark) for mark in CLAUSE_BREAKS)
    if clause_at >= max(MIN_SEGMENT_CHARACTERS, maximum // 2):
        return window[:clause_at].rstrip("，、：,") + "。"
    if not allow_fragment:
        return ""
    window = re.sub(r"[A-Za-z0-9_+.-]+$", "", window).rstrip("，、；;：: ")
    return window + "。" if window else ""


def _append_segment(segments: list[str], candidate: object, maximum: int) -> bool:
    text = clean_tts_text(candidate)
    if not text or _is_duplicate(text, segments):
        return False
    used = sum(len(segment) for segment in segments) + len(segments)
    remaining = maximum - used
    clipped = _clip_sentence(text, remaining, allow_fragment=not segments)
    minimum = 1 if not segments else MIN_SEGMENT_CHARACTERS
    if len(clipped) < minimum:
        return False
    segments.append(clipped)
    return len(clipped) < len(text) or sum(len(segment) for segment in segments) >= maximum


def build_tts_script(event: dict, maximum: int = DEFAULT_MAX_CHARACTERS) -> str:
    """Return title, summary, reason and selected body paragraphs within a hard limit."""
    maximum = max(120, min(1200, int(maximum)))
    segments: list[str] = []
    if _append_segment(segments, event.get("zh_title"), maximum):
        return "\n".join(segments)
    if _append_segment(segments, event.get("zh_summary"), maximum):
        return "\n".join(segments)

    reason = LEADING_REASON_RE.sub("", str(event.get("reason") or ""))
    if reason and _append_segment(segments, f"推荐理由：{reason}", maximum):
        return "\n".join(segments)

    candidates = list(_structured_candidates(event)) or list(_legacy_candidates(event))
    for candidate in candidates:
        if _append_segment(segments, candidate, maximum):
            break
        if len(segments) >= 8:
            break
    return "\n".join(segments)


def narration_hash(text: str, voice_version: str, text_version: str = TEXT_VERSION) -> str:
    payload = "\0".join((text_version, voice_version, text)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
