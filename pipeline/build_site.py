#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1.1：读取 latest.json（事件结构），生成首页 + 每个事件的站内详情页（带 OG meta）"""
import base64, hashlib, json, html, os, re, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from urllib.parse import urlparse
from content_blocks import render_blocks_html, sanitize_blocks, sanitize_url
from check_links import check_site_links, format_broken_links
from feed import build_atom_feed, validate_atom_feed
from lite_data import (
    DEFAULT_PAGE_SIZE, FIRST_PAGE_SOURCE_CAPS, HOME_WINDOW_DAYS,
    build_lite_payload, event_timestamp, find_forbidden_fields,
    is_list_eligible, rank_hot_events, rank_timeline_events,
    select_home_events, select_timeline_events,
)
from weekly_brief import valid_brief as valid_weekly_brief

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DETAIL_DIR = SITE / "e"
TOPIC_DIR = SITE / "topics"
WEEKLY_DIR = SITE / "weekly"
ANALYTICS_ASSET = ROOT / "pipeline" / "assets" / "analytics.js"
HOME_ASSET = ROOT / "pipeline" / "assets" / "home.js"
TTS_ASSET = ROOT / "pipeline" / "assets" / "tts-player.js"
TTS_MANIFEST = SITE / "data" / "tts-manifest.json"
TZ = timezone(timedelta(hours=8))
CAT_BADGE = {
    "agent": "b-agent", "platform": "b-platform", "bi": "b-bi",
    "product": "b-product", "insight": "b-insight",
}
CAT_LABEL = {
    "agent": "Data Agent", "platform": "AI 数据平台", "bi": "BI 与可视化",
    "product": "数据产品", "insight": "AI 分析与洞察",
}
WEEK_CN = "一二三四五六日"
HEAT_FORMULA = "AI重要性50% + 新鲜度20% + 社区信号15%(封顶) + 多信源15%"
UPDATE_MECHANISM = (
    "DataHot 通常在北京时间 02:17、08:17、14:17、20:17 自动启动更新。"
    "完成信源采集、筛选去重、AI 整理和静态发布后，页面时间才会变化，"
    "因此可能比计划时间晚几分钟。"
)

ICONS = {
 "flame": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22c4.4 0 8-3.5 8-7.8 0-3.9-2.9-6-4.6-9.1C14.9 3.6 13.4 2.4 12 2c-.4 2.9-1.9 4.4-3.4 6C6.6 9.6 4 11.6 4 15.1 4 19 7.6 22 12 22z"/></svg>',
 "map": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/></svg>',
 "search": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>',
 "clock": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>',
 "building": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V8l7-5 7 5v13"/><path d="M9 10h1.5M9 14h1.5M13.5 10H15M13.5 14H15"/></svg>',
 "tag": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2H2v10l9.3 9.3a2 2 0 0 0 2.8 0l7-7a2 2 0 0 0 0-2.8L12 2z"/><circle cx="7.5" cy="7.5" r="1.3"/></svg>',
 "calendar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
 "arrow": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17 17 7M8 7h9v9"/></svg>',
 "image": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.5"/><path d="M3 17l5-5 4 4 3-3 6 6"/></svg>',
 "link": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg>',
 "share": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 8l5-5 5 5"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg>',
 "sparkle": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 4.8L18.7 9.7l-4.8 1.9L12 16.4l-1.9-4.8-4.8-1.9 4.8-1.9L12 3z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8.8-2z"/></svg>',
 "file": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h8l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M14 2v5h5M9 13h6M9 17h6"/></svg>',
 "list": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6h12M9 12h12M9 18h12"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/></svg>',
 "more": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/></svg>',
 "rss": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1.5"/></svg>',
 "star": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4 6.1 20.5l1.2-6.5L2.5 9.4l6.6-.9 2.9-6z"/></svg>',
 "bookmark": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-4.5L5 21V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v17z"/></svg>',
 "headphones": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14v-2a8 8 0 0 1 16 0v2"/><path d="M18 19h1a2 2 0 0 0 2-2v-2a2 2 0 0 0-2-2h-1v6zM6 19H5a2 2 0 0 1-2-2v-2a2 2 0 0 1 2-2h1v6z"/></svg>',
}
def ic(name, size=15):
    return ICONS[name].replace("<svg ", '<svg width="{}" height="{}" style="vertical-align:-2px" aria-hidden="true" '.format(size, size))

TOPICS_META = json.load(open(ROOT / "pipeline" / "topics.json"))
SOURCES_META = {x["name"]: x for x in json.load(open(ROOT / "pipeline" / "sources.json"))}

HOME_FILTER_TOPIC_ORDER = (
    "Data Agent", "平台AI化", "语义层", "实时分析", "ChatBI",
    "湖仓", "BI变局", "数据人", "组织人才",
)
HOME_FILTER_TOPIC_LABELS = {
    "Data Agent": "Agent",
    "平台AI化": "AI平台",
    "实时分析": "实时",
}

def src_display(name):
    """信源显示名：站内术语转外部可读 + 英文语境半角括号"""
    if name == "主编收录":
        return "DataHot 精选"
    return re.sub(r"（(?=[A-Za-z])", " (", name).replace("）", ")")


def render_home_filter_chips(timeline_events):
    """Render stable home-filter order while preserving canonical filter values."""
    active_topics = {t for e in timeline_events for t in e.get("topics", [])}
    configured_topics = [topic["name"] for topic in TOPICS_META]
    preferred = [name for name in HOME_FILTER_TOPIC_ORDER if name in active_topics]
    remaining = [
        name for name in configured_topics
        if name in active_topics and name not in HOME_FILTER_TOPIC_ORDER
    ]
    parts = []
    for name in (*preferred, *remaining):
        parts.append(
            f'<span class="fchip" data-topic="{esc(name)}">'
            f'{esc(HOME_FILTER_TOPIC_LABELS.get(name, name))}</span>'
        )
        if name == "Data Agent":
            parts.append('<span class="fchip" data-category="insight">AI分析</span>')
    if "Data Agent" not in active_topics:
        parts.insert(0, '<span class="fchip" data-category="insight">AI分析</span>')
    return "".join(parts)

def src_badge(source_name):
    """信源类型标识：公众号/RSS/官网/HN/Bluesky/收录（参考 AI HOT 的信源标注）"""
    if source_name.startswith("公众号"):
        return "公众号"
    if source_name.startswith("X 线索·"):
        return "X 线索"
    if source_name == "主编收录":
        return "收录"
    meta = SOURCES_META.get(source_name, {})
    kind, stype = meta.get("kind", ""), meta.get("type", "")
    if kind == "bluesky":
        return "Bluesky"
    if kind == "hn_algolia":
        return "HN"
    if kind in ("sitemap", "snowflake_rn"):
        return "官网"
    if stype == "vendor":
        return "官网·RSS"
    if stype == "community":
        return "社区"
    return "RSS"

def source_public_url(source):
    """Return a reader-safe source URL without exposing sitemap endpoints."""
    kind_fallbacks = {
        "hn_algolia": "https://news.ycombinator.com/",
        "bluesky": "https://bsky.app/",
    }
    candidates = [source.get("url"), *(source.get("urls") or [])]
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        candidate = sanitize_url(candidate)
        if not candidate:
            continue
        parsed = urlparse(candidate)
        if source.get("kind") == "sitemap" and candidate in (source.get("urls") or []):
            return f"{parsed.scheme}://{parsed.netloc}/"
        return candidate
    return kind_fallbacks.get(source.get("kind"), "")
TOPIC_SLUG = {t["name"]: t["slug"] for t in TOPICS_META}

SHARED_CSS = """
body{overflow-x:clip}
main,.layout>*,.hotlist>*{min-width:0}
.d-only{display:inline-block}
@media(max-width:960px){.d-only{display:none}}
.chip{display:inline-block;font-size:11px;background:#eef2ff;color:var(--blue);border-radius:99px;padding:1px 10px;text-decoration:none}
.chip:hover{background:#dbe4ff}
.tlsearch{margin-left:auto;border:1px solid var(--line);border-radius:99px;padding:5px 12px;font-size:12.5px;width:120px;outline:none;background:var(--card)}
.tlsearch:focus{width:160px;border-color:var(--accent);transition:width .2s}
.chiprow{display:flex;gap:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;padding:4px 0 12px;margin-bottom:4px;position:relative}
.chiprow::after{content:"";position:sticky;right:0;flex-shrink:0;width:28px;margin-left:-28px;background:linear-gradient(to right,transparent,var(--bg));pointer-events:none}
.chiprow::-webkit-scrollbar{display:none}
.chiprow .fchip{flex-shrink:0;font-size:12.5px;border:1px solid var(--line);border-radius:99px;padding:4px 14px;color:var(--sub);cursor:pointer;background:var(--card)}
.chiprow .fchip.on{background:var(--ink);color:#fff;border-color:var(--ink);font-weight:600}
@media(max-width:600px){
  .chiprow{gap:6px}
  .chiprow .fchip{font-size:12px;padding:4px 12px;min-height:32px;display:inline-flex;align-items:center}
}
@media (prefers-color-scheme: dark){
  .chip{background:rgba(110,168,255,.16);color:#6ea8ff}
  .chip:hover{background:rgba(110,168,255,.26)}
  .chiprow .fchip.on{background:var(--ink);color:#121417;border-color:var(--ink)}
  .chiprow .fchip{background:var(--card);color:var(--sub);border-color:var(--line)}
}
.scard{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 20px;margin-bottom:14px}
.source-page{padding:30px 20px 60px;max-width:820px}
.source-intro{margin-bottom:30px}
.source-intro h1{font-size:27px;line-height:1.35;margin:0 0 10px}
.source-intro p{font-size:14px;line-height:1.8;color:var(--txt2);margin:0;max-width:720px}
.source-alert{margin-top:14px;padding:10px 12px;border-left:3px solid var(--amber);background:var(--soft);border-radius:0 8px 8px 0;font-size:12.5px;line-height:1.7;color:var(--txt2)}
.source-alert b{color:var(--ink);margin-right:6px}
.source-group{margin:0 0 28px}
.source-group-head{display:flex;align-items:baseline;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:8px}
.source-group-head h2{font-size:16px;line-height:1.4;margin:0}
.source-group-head span{font-size:11.5px;color:var(--sub)}
.source-row{display:flex;align-items:center;gap:12px;min-height:49px;border-bottom:1px solid var(--soft)}
.source-name{display:inline-flex;align-items:center;gap:4px;min-width:0;color:var(--ink);font-size:13.5px;font-weight:650;line-height:1.5;text-decoration:none}
a.source-name:hover{color:var(--accent)}
.source-name svg{flex:0 0 auto}
.source-focus{margin-left:auto;color:var(--sub);font-size:11.5px;line-height:1.45;text-align:right}
.source-health{color:var(--amber);font-size:11.5px;white-space:nowrap}
.source-disabled{margin:2px 0 28px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.source-disabled summary{cursor:pointer;padding:13px 0;font-size:13px;font-weight:650;color:var(--txt2)}
.source-disabled .source-row{align-items:flex-start;padding:11px 0;min-height:0}
.source-disabled-reason{margin-left:auto;max-width:62%;font-size:11.5px;line-height:1.6;color:var(--sub);text-align:right}
.source-contribute{display:flex;align-items:center;gap:18px;background:var(--soft);border-radius:var(--radius);padding:17px 18px;margin-bottom:20px}
.source-contribute-copy{min-width:0;flex:1}
.source-contribute h2{font-size:15px;margin:0 0 4px}
.source-contribute p{font-size:12.5px;line-height:1.6;color:var(--sub);margin:0}
.source-cta{display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;border-radius:99px;background:var(--ink);color:var(--bg);padding:8px 14px;font-size:12px;font-weight:650;text-decoration:none}
.source-cta:hover{opacity:.86}
.source-principle{font-size:12px;line-height:1.75;color:var(--sub);margin:0}
@media(max-width:600px){
  .source-page{padding:22px 18px 52px}
  .source-intro{margin-bottom:25px}
  .source-intro h1{font-size:24px}
  .source-row{gap:8px}
  .source-name{font-size:13px}
  .source-focus{max-width:45%;font-size:11px}
  .source-disabled .source-row{display:block}
  .source-disabled-reason{max-width:none;margin:4px 0 0;text-align:left}
  .source-contribute{align-items:flex-start;flex-direction:column;gap:12px}
}
.crow{display:flex;align-items:baseline;gap:8px;padding:9px 0;border-bottom:1px solid var(--soft);text-decoration:none;color:var(--ink)}
.crow:last-child{border-bottom:none}
.crow:hover .ctitle{color:var(--accent)}
.cpin{width:18px;flex-shrink:0;font-size:12px}
.ctitle{font-size:13.5px;font-weight:600;line-height:1.55;flex:1}
.cmeta{font-size:11px;color:var(--sub);white-space:nowrap}
.favbtn{border:none;background:none;color:var(--sub);cursor:pointer;padding:2px;display:inline-flex;align-items:center}
.favbtn.on{color:var(--accent)}
.favbtn.on svg{fill:currentColor}
.favbtn svg{pointer-events:none}
.fav-entry{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;color:var(--sub);white-space:nowrap;text-decoration:none}
.fav-entry:hover{color:var(--accent)}
.privacy-btn{border:none;background:var(--accent);color:#fff;border-radius:99px;padding:9px 16px;font-size:12.5px;font-weight:650;cursor:pointer;margin:4px 6px 4px 0}
.privacy-btn.ghost{background:var(--card);color:var(--ink);border:1px solid var(--line)}
.load-more{display:block;margin:18px auto 4px;border:1px solid var(--line);background:var(--card);color:var(--txt2);border-radius:99px;padding:9px 22px;font-size:12.5px;font-weight:650;cursor:pointer}
.load-more[hidden]{display:none}
.load-more:hover{border-color:var(--accent);color:var(--accent)}
.load-more[disabled]{opacity:.65;cursor:default}
.weekly-teaser{display:block;background:linear-gradient(135deg,#1a1d23,#34302a);color:#fff;border-radius:var(--radius);padding:18px 22px;margin-bottom:22px;text-decoration:none;position:relative;overflow:hidden}
.weekly-teaser:hover{transform:translateY(-1px)}
.weekly-teaser .weekly-kicker{font-size:11px;letter-spacing:1.5px;color:#f5b48a;font-weight:750;margin-bottom:6px}
.weekly-teaser h2{font-size:19px;line-height:1.45;margin:0 0 5px}
.weekly-teaser p{font-size:12.5px;line-height:1.7;color:#e5e7eb;margin:0;max-width:720px}
.weekly-teaser .weekly-meta{font-size:11px;color:#aeb4be;margin-top:8px}
.weekly-waiting{display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:10px 14px;margin-bottom:18px;color:var(--txt2);font-size:12.5px;text-decoration:none}
.weekly-waiting:hover{border-color:var(--accent);color:var(--accent)}
.weekly-waiting b{color:var(--ink);font-size:13px}
.weekly-waiting span:last-child{margin-left:auto;color:var(--sub);font-size:11.5px}
.weekly-summary{background:linear-gradient(135deg,#1a1d23,#34302a);color:#fff;border:0;padding:20px 22px}
.weekly-summary h1{font-size:25px;line-height:1.4;margin:4px 0 8px}
.weekly-summary p{font-size:14px;line-height:1.75;color:#e5e7eb;margin:0}
.weekly-change{padding:9px 0;border-bottom:1px solid rgba(255,255,255,.12);font-size:13px;line-height:1.7;color:#f3f4f6}
.weekly-change:last-child{border-bottom:0}
.weekly-themes{display:grid;gap:14px}
.weekly-theme{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:20px 22px}
.weekly-theme h2{font-size:19px;line-height:1.5;margin:9px 0 12px}
.weekly-theme p{font-size:13.5px;line-height:1.85;color:var(--txt2);margin:0 0 12px}
.weekly-badges{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.weekly-pill{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:99px;padding:3px 8px;font-size:10.5px;color:var(--sub)}
.weekly-pill.priority-now{border-color:#dc2626;color:#b91c1c;background:#fef2f2}
.weekly-pill.priority-test{border-color:#d97706;color:#b45309;background:#fffbeb}
.weekly-pill.priority-watch{border-color:#2563eb;color:#1d4ed8;background:#eff6ff}
.weekly-pill.priority-ignore{color:var(--sub);background:var(--soft)}
.weekly-anchor{background:var(--soft);border-left:3px solid var(--accent);padding:10px 12px;border-radius:0 8px 8px 0;font-size:12.5px;line-height:1.75;color:var(--txt2);margin:0 0 14px}
.weekly-anchor b,.weekly-why b{color:var(--ink)}
.weekly-why{font-size:13px;line-height:1.8;color:var(--txt2);border-top:1px solid var(--soft);padding-top:12px}
.weekly-action{margin-top:12px;background:#fff8ed;border:1px solid #f3d5aa;border-radius:9px;padding:11px 12px;font-size:13px;line-height:1.75;color:var(--txt2)}
.weekly-action b{color:#9a4f08;margin-right:7px}
.weekly-signal-meta{font-size:11px;color:var(--sub);margin-top:12px}
.weekly-secondary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.weekly-secondary .scard{font-size:12.5px;line-height:1.75;color:var(--txt2)}
.weekly-secondary b{display:block;color:var(--ink);font-size:12px;margin-bottom:6px}
.weekly-evidence{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:0 18px}
.weekly-evidence summary{cursor:pointer;padding:15px 0;font-size:13px;font-weight:700;color:var(--ink)}
.weekly-evidence-row{display:flex;gap:12px;align-items:baseline;padding:11px 0;border-top:1px solid var(--soft);text-decoration:none;color:var(--ink)}
.weekly-evidence-row:hover span:first-child{color:var(--accent)}
.weekly-evidence-row span:first-child{font-size:13px;line-height:1.55;flex:1}
.weekly-evidence-row span:last-child{font-size:10.5px;color:var(--sub);white-space:nowrap}
.weekly-archive{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 22px}
.weekly-archive a{font-size:12px;color:var(--sub);border:1px solid var(--line);border-radius:99px;padding:5px 10px;text-decoration:none}
.weekly-archive a:hover,.weekly-archive a.on{border-color:var(--accent);color:var(--accent)}
@media (prefers-color-scheme: dark){
  .weekly-pill.priority-now{border-color:#ef7b7b;color:#ffaaaa;background:rgba(220,38,38,.14)}
  .weekly-pill.priority-test{border-color:#d89a3d;color:#f2bd70;background:rgba(217,119,6,.14)}
  .weekly-pill.priority-watch{border-color:#6ea8ff;color:#9cc3ff;background:rgba(37,99,235,.14)}
  .weekly-action{background:rgba(217,119,6,.12);border-color:rgba(242,189,112,.38);color:var(--txt2)}
  .weekly-action b{color:#f2bd70}
}
@media(max-width:700px){
  .weekly-summary{padding:16px 20px}
  .weekly-summary h1{font-size:23px}
  .weekly-theme{padding:17px}
  .weekly-theme h2{font-size:17px}
  .weekly-secondary{grid-template-columns:1fr}
  .weekly-evidence-row{align-items:flex-start;flex-direction:column;gap:4px}
  .weekly-evidence-row span:last-child{white-space:normal}
}
.hrow{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--soft);text-decoration:none;color:var(--ink)}
.hrow:last-child{border-bottom:none}
.hrow .rk{font-size:15px;font-weight:800;color:var(--accent);width:26px;flex-shrink:0;text-align:center}
.hrow .ht{flex:1;font-size:14px;font-weight:600;line-height:1.5}
.hrow:hover .ht{color:var(--accent)}
.hrow .hm{font-size:11px;color:var(--sub);white-space:nowrap}
.srcbadge{font-size:10px;border:1px solid var(--line);border-radius:5px;padding:0 5px;color:var(--sub);flex-shrink:0;line-height:1.6}
.sidebar{display:none}
@media(min-width:961px){
  body.has-sb{padding-left:224px}
  body.has-sb>header{display:none}
  .sidebar{display:flex;position:fixed;left:0;top:0;bottom:0;width:224px;flex-direction:column;background:var(--card);border-right:1px solid var(--line);padding:22px 16px;z-index:40}
  .sidebar .slogo{font-size:20px;font-weight:800;margin-bottom:26px}
  .sidebar .slogo em{font-style:normal;color:var(--accent)}
  .sidebar a.mi{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:10px;font-size:14px;color:var(--sub);text-decoration:none;margin-bottom:2px}
  .sidebar a.mi:hover{background:var(--hover);color:var(--ink)}
  .sidebar a.mi.on{background:var(--ink);color:var(--bg);font-weight:600}
  .sidebar .sfoot{margin-top:auto;font-size:11.5px;color:var(--sub);line-height:1.8}
}
.hot .hsum{font-size:12.5px;color:var(--txt2);line-height:1.65;margin:6px 0 10px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.hot .htime{margin-left:auto;font-size:11px;color:var(--sub)}
.tabbar{display:none}
.more-mask,.more-sheet{display:none}
@media(max-width:960px){
  body{padding-bottom:64px}
  footer{padding-bottom:96px}
  body.mobile-section{padding-top:env(safe-area-inset-top)}
  .section-brand-header,.detail-brand-header{display:none}
  .tabbar{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));position:fixed;bottom:0;left:0;right:0;background:var(--tabbar-bg);backdrop-filter:blur(10px);border-top:1px solid var(--line);z-index:70;padding:0 0 env(safe-area-inset-bottom)}
  .tabbar a,.tabbar button{appearance:none;border:0;background:transparent;min-width:0;min-height:56px;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:7px 2px 5px;font:inherit;font-size:11px;color:var(--sub);text-decoration:none;gap:2px;cursor:pointer;touch-action:manipulation}
  .tabbar .ico{display:grid;place-items:center;height:22px}
  .tabbar a.on,.tabbar button.on{color:var(--accent);font-weight:650}
  .more-mask{display:block;position:fixed;inset:0;background:rgba(0,0,0,.42);opacity:0;pointer-events:none;transition:opacity .22s ease;z-index:78}
  .more-mask.show{opacity:1;pointer-events:auto}
  .more-sheet{display:block;position:fixed;left:0;right:0;bottom:0;z-index:80;max-height:70vh;overflow:auto;background:var(--card);border-radius:18px 18px 0 0;padding:8px 16px calc(18px + env(safe-area-inset-bottom));box-shadow:0 -14px 40px rgba(0,0,0,.18);transform:translateY(110%);transition:transform .28s cubic-bezier(.32,.72,.35,1)}
  .more-sheet.show{transform:translateY(0)}
  .more-handle{width:36px;height:4px;border-radius:99px;background:var(--line);margin:2px auto 12px}
  .more-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
  .more-head h2{font-size:18px}
  .more-close{appearance:none;border:0;background:var(--soft);color:var(--sub);width:34px;height:34px;border-radius:50%;font-size:18px;cursor:pointer}
  .more-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .more-link{display:flex;align-items:center;gap:11px;min-height:58px;padding:11px 12px;border:1px solid var(--line);border-radius:12px;background:var(--bg);text-decoration:none;color:var(--ink)}
  .more-link .more-icon{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;background:var(--accent-soft);color:var(--accent);flex:0 0 auto}
  .more-link span:last-child{min-width:0;font-size:13px;font-weight:650}
  .more-link.on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
  body.more-open{overflow:hidden}
}
.tgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
@media(max-width:960px){.tgrid{grid-template-columns:1fr}}
.tcard{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;text-decoration:none;display:block;transition:.15s}
.tcard:hover{border-color:#d1d5db;box-shadow:0 4px 16px rgba(0,0,0,.05)}
.tcard h3{font-size:17px;font-weight:800;margin-bottom:6px}
.tcard .td{font-size:12.5px;color:var(--sub);line-height:1.6;margin-bottom:10px}
.tcard .tn{font-size:12px;color:var(--accent);font-weight:700}
.tcard .tt{font-size:12.5px;color:var(--txt2);margin-top:8px;line-height:1.7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
"""

def sidebar(active, gen=None, prefix=""):
    """桌面端左侧菜单栏（≥961px 显示，移动端隐藏，由底部 Tab 承担导航）"""
    items = [("热榜", "flame", "index.html", "home")]
    if weekly_brief_enabled():
        items.append(("每周简报", "calendar", "weekly.html", "weekly"))
    items += [("主题", "map", "topics.html", "topics"),
             ("我的收藏", "star", "favorites.html", "favorites"),
             ("典藏", "bookmark", "classics.html", "classics"), ("完整榜单", "list", "hot.html", "hot"),
             ("信源", "rss", "sources.html", "sources")]
    menu = "".join(
        f'<a class="mi{" on" if k == active else ""}" href="{prefix}{u}">{ic(i,16)}{n}</a>'
        for n, i, u, k in items)
    foot = f'更新 {gen.strftime("%m-%d %H:%M")}<br>' if gen else ""
    logo_label = ' aria-label="刷新 DataHot 首页" title="刷新首页"' if active == "home" else ""
    return ('<aside class="sidebar">'
            f'<div class="slogo"><a href="{prefix}index.html"{logo_label} style="text-decoration:none;color:inherit">Data<em>Hot</em></a></div>'
            + menu +
            f'<div class="sfoot">{foot}每 6 小时自动更新 · <a href="https://github.com/henryhb1105-arch/datahot" target="_blank" rel="noopener noreferrer" style="color:var(--sub)">GitHub</a><br>数据领域 AI 资讯分享</div></aside>')


def render_home_brand_update(gen):
    """首页品牌刷新入口与可交互的更新机制说明。"""
    return f'''<a class="logo home-logo" href="index.html" data-home-refresh aria-label="刷新 DataHot 首页" title="刷新首页">Data<em>Hot</em><span class="tag">每 6 小时更新</span></a>
  <details class="update-info" data-update-info>
    <summary class="upd-time" aria-describedby="updateMechanism">{ic("clock",12)} {gen.strftime("%m-%d %H:%M")} 更新</summary>
    <div class="update-popover" id="updateMechanism" role="tooltip"><b>页面如何更新</b>{esc(UPDATE_MECHANISM)}</div>
  </details>'''


def render_timeline_toolbar(total_count):
    """首页时间轴工具栏：窄屏时标题元信息与搜索分成受控的两行。"""
    return f'''<div class="section-title timeline-toolbar">
  <h2>{ic("calendar",18)} 时间轴</h2>
  <span class="timeline-meta">不限时间 · 每批 {DEFAULT_PAGE_SIZE} 条</span>
  <div class="timeline-searchbox">
    <input id="q" class="tlsearch" placeholder="搜索全部在站事件" title="搜索范围：全部在站时间轴的标题、摘要与标签">
    <span id="qClear" class="timeline-clear" style="display:none" title="清除搜索">✕</span>
  </div>
  <span class="timeline-count">（<span id="rCount">{total_count}</span>）</span>
</div>'''


def home_update_info_script():
    return '''<script>
(function(){
  var info=document.querySelector('[data-update-info]');
  if(!info) return;
  var summary=info.querySelector('summary');
  document.addEventListener('click',function(event){
    if(!info.contains(event.target)) info.removeAttribute('open');
  });
  document.addEventListener('keydown',function(event){
    if(event.key!=='Escape') return;
    info.removeAttribute('open');
    info.classList.add('is-dismissed');
  });
  info.addEventListener('pointerleave',function(){info.classList.remove('is-dismissed')});
  if(summary){
    summary.addEventListener('click',function(){info.classList.remove('is-dismissed')});
    summary.addEventListener('blur',function(){info.classList.remove('is-dismissed')});
  }
})();
</script>'''


def analytics_head(prefix=""):
    enabled_value = os.getenv("ANALYTICS_ENABLED", "false").strip().lower()
    endpoint = os.getenv("ANALYTICS_ENDPOINT", "").strip()
    environment = os.getenv("ANALYTICS_ENV", "production").strip().lower()
    site_id = re.sub(r"[^a-z0-9_-]", "", os.getenv("ANALYTICS_SITE_ID", "datahot").lower())[:40] or "datahot"
    production_host = os.getenv("ANALYTICS_PRODUCTION_HOST", "henryhb1105-arch.github.io").strip().lower()
    production_host = production_host if re.fullmatch(r"[a-z0-9.-]+", production_host) else "henryhb1105-arch.github.io"
    safe_https_endpoint = sanitize_url(endpoint)
    parsed = urlparse(safe_https_endpoint)
    endpoint_valid = bool(parsed.scheme == "https" and parsed.netloc)
    enabled = enabled_value in {"1", "true", "yes", "on"} and environment == "production" and endpoint_valid
    safe_endpoint = safe_https_endpoint if endpoint_valid else ""
    return (
        f'<meta name="datahot-analytics" data-enabled="{str(enabled).lower()}" '
        f'data-endpoint="{esc(safe_endpoint)}" data-site-id="{esc(site_id)}" '
        f'data-environment="{esc(environment)}" data-production-host="{esc(production_host)}">\n'
        f'<script defer src="{prefix}analytics.js"></script>'
    )

def feed_enabled():
    return os.getenv("FEED_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def lite_home_enabled():
    return os.getenv("LITE_HOME_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def feed_discovery():
    if not feed_enabled():
        return ""
    return f'<link rel="alternate" type="application/atom+xml" title="DataHot Feed" href="{SITE_BASE}/feed.xml">'


def weekly_brief_enabled():
    value = os.getenv("WEEKLY_BRIEF_ENABLED", os.getenv("DAILY_BRIEF_ENABLED", "true"))
    return value.strip().lower() in {"1", "true", "yes", "on"}

def tabbar(active, prefix=""):
    items = [("热榜", ic("flame",20), "index.html", "home"),
             ("主题", ic("map",20), "topics.html", "topics"),
             ("收藏", ic("star",20), "favorites.html", "favorites")]
    primary = "".join(
        f'<a href="{prefix}{u}" class="{"on" if k == active else ""}"><span class="ico">{i}</span><span>{n}</span></a>'
        for n, i, u, k in items)
    more_items = []
    if weekly_brief_enabled():
        more_items.append(("每周简报", "calendar", "weekly.html", "weekly"))
    more_items += [
        ("完整榜单", "list", "hot.html", "hot"),
        ("典藏", "bookmark", "classics.html", "classics"),
        ("信源", "rss", "sources.html", "sources"),
        ("隐私说明", "file", "privacy.html", "privacy"),
    ]
    more_keys = {item[3] for item in more_items if item[3] != "hot"}
    more_on = active in more_keys
    more_links = "".join(
        f'<a class="more-link{" on" if key == active else ""}" href="{prefix}{url}">'
        f'<span class="more-icon">{ic(icon,18)}</span><span>{name}</span></a>'
        for name, icon, url, key in more_items)
    return f'''<nav class="tabbar" aria-label="移动端主导航">
  {primary}
  <button class="tabbar-more{" on" if more_on else ""}" type="button" data-more-open aria-expanded="false" aria-controls="mobileMoreSheet"><span class="ico">{ic("more",20)}</span><span>更多</span></button>
</nav>
<div class="more-mask" data-more-mask></div>
<section class="more-sheet" id="mobileMoreSheet" aria-label="更多导航" aria-hidden="true">
  <div class="more-handle" aria-hidden="true"></div>
  <div class="more-head"><h2>更多</h2><button class="more-close" type="button" data-more-close aria-label="关闭更多导航">×</button></div>
  <div class="more-grid">{more_links}</div>
</section>
<script>
(function(){{
  var trigger=document.querySelector('[data-more-open]');
  var sheet=document.getElementById('mobileMoreSheet');
  var mask=document.querySelector('[data-more-mask]');
  var closeBtn=document.querySelector('[data-more-close]');
  if(!trigger||!sheet||!mask||!closeBtn) return;
  function setMore(open){{
    trigger.setAttribute('aria-expanded',open?'true':'false');
    sheet.setAttribute('aria-hidden',open?'false':'true');
    sheet.classList.toggle('show',open);
    mask.classList.toggle('show',open);
    document.body.classList.toggle('more-open',open);
    if(open) closeBtn.focus(); else trigger.focus();
  }}
  trigger.addEventListener('click',function(){{setMore(true)}});
  closeBtn.addEventListener('click',function(){{setMore(false)}});
  mask.addEventListener('click',function(){{setMore(false)}});
  document.addEventListener('keydown',function(event){{if(event.key==='Escape'&&sheet.classList.contains('show')) setMore(false)}});
}})();
</script>'''

def esc(s):
    return html.escape(s or "", quote=True)


EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
INLINE_SCRIPT_RE = re.compile(
    r"<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script\s*>", re.I | re.S,
)
INLINE_EVENT_HANDLER_RE = re.compile(r"<[^>]+\son[a-z]+\s*=", re.I)


def safe_event_id(value):
    """Return a path/attribute-safe event id or fail the build closed."""
    value = str(value or "")
    if not EVENT_ID_RE.fullmatch(value):
        raise ValueError(f"unsafe event_id: {value!r}")
    return value


def json_for_html(value):
    """Serialize JSON without HTML parser breakouts inside script elements."""
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _analytics_connect_origin():
    endpoint = sanitize_url(os.getenv("ANALYTICS_ENDPOINT", "").strip())
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def finalize_html_security(document):
    """Inject a restrictive CSP after all trusted inline scripts are finalized."""
    if INLINE_EVENT_HANDLER_RE.search(document):
        raise ValueError("inline event handlers are forbidden by the site CSP")
    hashes = sorted({
        "'sha256-" + base64.b64encode(
            hashlib.sha256(script.encode("utf-8")).digest()
        ).decode("ascii") + "'"
        for script in INLINE_SCRIPT_RE.findall(document)
    })
    connect_sources = ["'self'"]
    analytics_origin = _analytics_connect_origin()
    if analytics_origin:
        connect_sources.append(analytics_origin)
    directives = [
        "default-src 'self'",
        "base-uri 'none'",
        "object-src 'none'",
        "frame-src 'none'",
        "form-action 'none'",
        "worker-src 'none'",
        "manifest-src 'self'",
        "font-src 'self' data:",
        "media-src 'self' blob:",
        "img-src 'self' data: blob: https://api.qrserver.com",
        "connect-src " + " ".join(connect_sources),
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self'" + ((" " + " ".join(hashes)) if hashes else ""),
        "script-src-attr 'none'",
        "upgrade-insecure-requests",
    ]
    meta = (
        '<meta http-equiv="Content-Security-Policy" content="'
        + "; ".join(directives)
        + '">\n<meta name="referrer" content="strict-origin-when-cross-origin">'
    )
    marker = '<meta charset="UTF-8">'
    if marker not in document:
        raise ValueError("HTML document is missing the UTF-8 charset marker")
    return document.replace(marker, marker + "\n" + meta, 1)

def clean_reason(reason):
    """统一由界面添加“推荐理由：”，避免历史数据中的前缀重复。"""
    return re.sub(r"^\s*推荐理由\s*[:：]\s*", "", reason or "")

def md(iso):
    """MM-DD 格式"""
    if not iso:
        return "未知"
    d = datetime.fromisoformat(iso).astimezone(TZ)
    return f"{d.month:02d}-{d.day:02d}"

def card_time(e):
    """单时间显示：只展示发布时间（<24h→x小时前 / <7天→周几 HH:mm / 更早→MM-DD）；
    无发布时间时用收录时间兜底并明确标注（参考 AI HOT：界面只有发布时间一个概念）"""
    pub, fs = e.get("published"), e.get("first_seen")
    if pub:
        dt = datetime.fromisoformat(pub).astimezone(TZ)
        hrs = (datetime.now(TZ) - dt).total_seconds() / 3600
        if hrs < 1:
            return "刚刚"
        if hrs < 24:
            return f"{int(hrs)} 小时前"
        if hrs < 24 * 7:
            return f"周{WEEK_CN[dt.weekday()]} {dt.strftime('%H:%M')}"
        return md(pub)
    return f"收录 {md(fs)}" if fs else ""

def fmt_time(iso):
    if not iso:
        return ""
    return datetime.fromisoformat(iso).astimezone(TZ).strftime("%H:%M")

def fmt_date(iso):
    if not iso:
        return "未知"
    d = datetime.fromisoformat(iso).astimezone(TZ)
    return d.strftime("%Y-%m-%d %H:%M")

def day_key(iso):
    return datetime.fromisoformat(iso).astimezone(TZ).date()

def detail_url(e):
    return f'e/{safe_event_id(e["event_id"])}.html'

def load_css():
    css = open(ROOT / "ui-mockup" / "index.html").read()
    return css.split("<style>", 1)[1].split("</style>", 1)[0]

def sources_html(e, link=False):
    """信源列表：首页纯展示，详情页带链接（按名称去重，多家同名合并）"""
    parts = []
    seen_src = set()
    for sub in e["items"]:
        if sub["source"] in seen_src:
            continue
        seen_src.add(sub["source"])
        safe_link = _safe_source_url(sub.get("link"))
        if link and safe_link:
            parts.append(f'<a class="src" href="{esc(safe_link)}" target="_blank" rel="noopener noreferrer">{esc(sub["source"])} ↗</a>')
        else:
            parts.append(f'<span class="src">{esc(sub["source"])}</span>')
    return "".join(parts)

def is_classic_review(e):
    """发布超过 30 天的 evergreen 内容 → 打「经典回顾」而非新闻"""
    pub = e.get("published")
    if not pub or e.get("shelf") != "evergreen":
        return False
    return (datetime.now(TZ) - datetime.fromisoformat(pub).astimezone(TZ)).days > 30

def render_card(e, prefix=""):
    event_id = safe_event_id(e["event_id"])
    star = '<span class="star">精选</span>' if e.get("star") else ""
    if is_classic_review(e):
        star += '<span class="star" style="color:var(--purple)">经典回顾</span>'
    star += f'<span title="热度分={HEAT_FORMULA}，满分100">{""}</span>'
    n = len(e["items"])
    also = ""
    if n > 1:
        names = " · ".join(esc(s["source"]) for s in e["items"][1:])
        also = f'<div class="also">另有 <b>{n-1} 家信源</b>报道：{names}</div>'
    reason = (f'<div class="why"><span><span class="w">{ic("sparkle",13)} 推荐理由：</span>'
              f'{esc(clean_reason(e["reason"]))}</span></div>') if e.get("reason") else ""
    tchips = "".join(
        f'<a class="chip" href="{prefix}topics/{TOPIC_SLUG[t]}.html">{esc(t)}</a>'
        for t in e.get("topics", []) if t in TOPIC_SLUG)
    vtags = "".join(f'<span class="vtag">{esc(v)}</span>' for v in e.get("vendors", []))
    vbox = f'<div class="vendors">{tchips}{vtags}</div>' if (tchips or vtags) else ""
    url = prefix + detail_url(e)
    return f'''<div class="item" data-cat="{esc(e["category"])}" data-topics="{esc("|".join(e.get("topics", [])))}" data-link="{url}" data-analytics-list="1" data-event-id="{event_id}" data-category="{esc(e["category"])}" data-source="{esc(e["items"][0]["source"])}">
      <div class="top"><span class="srcbadge">{src_badge(e["items"][0]["source"])}</span><span style="font-weight:600;color:var(--txt3)">{esc(src_display(e["items"][0]["source"]))}</span><span>{card_time(e)}</span>{star}
      <button class="favbtn" data-fav="{event_id}" title="收藏">{ic("star",15)}</button>
      <span class="heatnum" title="热度分：{HEAT_FORMULA}">{ic("flame",13)} {e["heat"]}</span></div>
      <h3><a href="{url}">{esc(e["zh_title"])}</a></h3>
      <p class="sum">{esc(e["zh_summary"])}</p>{also}{reason}{vbox}
    </div>'''

SITE_BASE = "https://henryhb1105-arch.github.io/datahot"

def title_bigrams(t):
    t = re.sub(r"[^\w一-鿿]+", "", (t or "").lower())
    return {t[i:i+2] for i in range(len(t) - 1)} if len(t) > 1 else {t} if t else set()

def sim(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def human_time(iso):
    dt = datetime.fromisoformat(iso).astimezone(TZ)
    delta = datetime.now(TZ) - dt
    if delta.days >= 1:
        return f"{delta.days} 天前"
    h = delta.seconds // 3600
    return f"{h} 小时前" if h >= 1 else "刚刚"

TTS_AUDIO_PATH_RE = re.compile(
    r"^audio/\d{4}/\d{2}/[a-f0-9]{12}-[a-f0-9]{12,64}\.mp3$"
)


def load_tts_manifest(path=TTS_MANIFEST):
    path = Path(path)
    if not path.exists():
        return {"items": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"items": {}}
    return payload if isinstance(payload, dict) and isinstance(payload.get("items"), dict) else {"items": {}}


def tts_item_for_event(manifest, event_id, site_root=SITE):
    item = manifest.get("items", {}).get(event_id) if isinstance(manifest, dict) else None
    if not isinstance(item, dict) or item.get("status") != "ready":
        return None
    audio_path = str(item.get("audio_path") or "")
    if not TTS_AUDIO_PATH_RE.fullmatch(audio_path) or not (Path(site_root) / audio_path).is_file():
        return None
    return item


def render_tts_ui(item):
    if not isinstance(item, dict) or item.get("status") != "ready":
        return "", "", ""
    audio_path = str(item.get("audio_path") or "")
    if not TTS_AUDIO_PATH_RE.fullmatch(audio_path):
        return "", "", ""
    try:
        duration = max(0, int(round(float(item.get("duration_seconds") or 0))))
    except (TypeError, ValueError):
        duration = 0
    button = (
        '<button class="sbtn ghost tts-open" type="button" data-tts-open '
        'aria-expanded="false" aria-controls="ttsPlayer">'
        f'{ic("headphones",13)} <span data-tts-open-label>听这篇</span></button>'
    )
    player = f'''<section class="tts-player" id="ttsPlayer" data-tts-player data-duration="{duration}" hidden aria-label="文章精华朗读">
  <audio data-tts-audio preload="metadata" src="../{esc(audio_path)}"></audio>
  <div class="tts-copy"><b>DataHot 主播</b><span data-tts-status>约 {max(1, round(duration / 60))} 分钟精华朗读</span></div>
  <button class="tts-toggle" type="button" data-tts-toggle aria-label="播放朗读">播放</button>
  <input class="tts-progress" type="range" data-tts-progress min="0" max="{duration}" value="0" step="0.1" aria-label="朗读进度">
  <span class="tts-time" data-tts-time>0:00 / {duration // 60}:{duration % 60:02d}</span>
  <label class="tts-rate-label">语速<select data-tts-rate aria-label="朗读语速">
    <option value="1">1.0×</option><option value="1.2">1.2×</option><option value="1.5">1.5×</option>
  </select></label>
</section>'''
    return button, player, '<script defer src="../tts-player.js"></script>'


def detail_primary_item(event):
    """Return the event's editorial primary item without inferring it from time."""
    items = event.get("items") or []
    if not items:
        raise ValueError("detail event must contain at least one source item")
    primary_id = event.get("primary_item_id")
    if primary_id:
        for item in items:
            if item.get("id") == primary_id:
                return item
    return items[0]


def render_supplement_sources(event, primary_item):
    """Render non-primary reports, grouped by source and kept individually reachable."""
    supplements = [item for item in (event.get("items") or []) if item is not primary_item]
    if not supplements:
        return ""

    grouped = {}
    for item in supplements:
        grouped.setdefault(item.get("source") or "未知来源", []).append(item)

    def report_row(item, source_name):
        title = str(item.get("title") or "查看报道").strip() or "查看报道"
        published = item.get("published")
        date = f'<span class="source-report-date">{fmt_date(published)}</span>' if published else ""
        safe_link = _safe_source_url(item.get("link"))
        if not safe_link:
            return (
                '<div class="source-report source-report-unavailable">'
                f'<span class="source-report-title">{esc(title)}</span>{date}</div>'
            )
        return (
            f'<a class="source-report" href="{esc(safe_link)}" target="_blank" '
            f'rel="noopener noreferrer" data-analytics="outbound" data-source="{esc(source_name)}">'
            f'<span class="source-report-title">{esc(title)} <span aria-hidden="true">↗</span></span>{date}</a>'
        )

    def source_group(source_name, reports):
        rows = "".join(report_row(item, source_name) for item in reports)
        report_count = f'<span>{len(reports)} 篇</span>' if len(reports) > 1 else ""
        return (
            '<div class="source-group">'
            f'<div class="source-group-head"><b>{esc(src_display(source_name))}</b>{report_count}</div>'
            f'{rows}</div>'
        )

    groups = list(grouped.items())
    visible_groups = groups if len(groups) <= 3 else groups[:2]
    hidden_groups = [] if len(groups) <= 3 else groups[2:]
    visible_html = "".join(source_group(name, reports) for name, reports in visible_groups)
    hidden_html = ""
    if hidden_groups:
        remainder = "".join(source_group(name, reports) for name, reports in hidden_groups)
        hidden_html = (
            '<details class="source-more">'
            f'<summary>展开另外 {len(hidden_groups)} 个信源</summary>{remainder}</details>'
        )

    return (
        '<section class="source-section" aria-labelledby="supplementSourcesTitle">'
        '<div class="source-heading">'
        '<h4 id="supplementSourcesTitle">补充来源</h4>'
        f'<span class="source-summary">{len(groups)} 个信源 · {len(supplements)} 篇报道</span>'
        f'</div>{visible_html}{hidden_html}</section>'
    )


def render_detail(e, all_events, css, tts_item=None):
    event_id = safe_event_id(e["event_id"])
    tts_button, tts_player, tts_script = render_tts_ui(tts_item)
    ebg = title_bigrams(e["zh_title"])
    related = sorted(
        (x for x in all_events if x["event_id"] != e["event_id"]),
        key=lambda x: (x["category"] == e["category"], sim(ebg, title_bigrams(x["zh_title"]))),
        reverse=True)[:3]
    rel_html = "".join(
        f'<a class="vendor-row" href="../{detail_url(x)}">'
        f'<span class="n">›</span>{esc(x["zh_title"])}<span class="count">{x["heat"]}</span></a>'
        for x in related) or '<div style="font-size:12.5px;color:var(--sub)">暂无相关事件</div>'
    primary_item = detail_primary_item(e)
    supplement_sources = render_supplement_sources(e, primary_item)
    tchips = "".join(
        f'<a class="chip" href="../topics/{TOPIC_SLUG[t]}.html">{esc(t)}</a>'
        for t in e.get("topics", []) if t in TOPIC_SLUG)
    vtags = tchips + "".join(f'<span class="vtag">{esc(v)}</span>' for v in e.get("vendors", []))
    desc = esc(e["zh_summary"][:150])
    main_url = _safe_source_url(primary_item.get("link"))
    main_link = esc(main_url)
    main_src_name = primary_item["source"]
    main_src = esc(main_src_name)
    original_link = (
        f'<a href="{main_link}" target="_blank" rel="noopener noreferrer" '
        f'data-analytics="outbound" data-source="{main_src}">查看原文 ↗</a>'
        if main_url else '<span class="source-link-unavailable">原文链接不可用</span>'
    )
    original_button = (
        f'<a class="sbtn ghost" href="{main_link}" target="_blank" rel="noopener noreferrer" '
        f'data-analytics="outbound" data-source="{main_src}">原文</a>'
        if main_url else ''
    )
    # blocks-v1 先经本地白名单清洗再渲染；异常或旧数据安全降级到 full_zh。
    safe_blocks = sanitize_blocks(e.get("content_blocks", []), main_url)
    render_media = os.getenv("MEDIA_BLOCKS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
    full_paras = render_blocks_html(safe_blocks, render_media=render_media) if safe_blocks else ""
    if not full_paras:
        paras_all = [pp.strip() for pp in re.split(r"\n\s*\n", e.get("full_zh", "")) if pp.strip()]
        if paras_all and paras_all[0].startswith("## "):
            import difflib as _dl
            if _dl.SequenceMatcher(None, paras_all[0][3:], e["zh_title"]).ratio() > 0.6:
                paras_all = paras_all[1:]
        for para in paras_all:
            if para.startswith("## "):
                full_paras += f'<h5 class="fh">{esc(para[3:])}</h5>'
            elif para.startswith("【"):
                full_paras += f'<p class="fwarn">{esc(para)}</p>'
            else:
                full_paras += "".join(f"<p>{esc(x)}</p>" for x in para.split("\n") if x.strip())
    full_block = ""
    if full_paras:
        full_block = f'''<div class="card"><h4>{ic("file")} 全文编译 <span style="font-size:11px;color:var(--sub);font-weight:400">AI 基于原文编译</span></h4>
  <div class="fulltext">{full_paras}</div>
  <div class="disclaimer">本内容由 AI 基于原文编译生成，仅供参考，版权归原作者与原发布方所有 · {original_link}</div>
</div>'''
    page_url = f"{SITE_BASE}/e/{event_id}.html"
    jsonld_payload = {
        "@context": "https://schema.org", "@type": "NewsArticle",
        "headline": e["zh_title"], "description": e["zh_summary"][:150],
        "datePublished": e["published"], "inLanguage": "zh-CN",
        "publisher": {"@type": "Organization", "name": "DataHot"},
    }
    if main_url:
        jsonld_payload["isBasedOn"] = main_url
    jsonld = json_for_html(jsonld_payload)
    page = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{esc(e["zh_title"])} · DataHot</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{page_url}">
<meta property="og:title" content="{esc(e["zh_title"])}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:url" content="{page_url}">
<meta property="og:site_name" content="DataHot · 数据领域 AI 热榜">
<link rel="icon" href="../favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="../icons/favicon-32.png">
<link rel="apple-touch-icon" href="../icons/apple-touch-icon.png">
<meta name="theme-color" content="#1a1d23">
{feed_discovery()}
{analytics_head("../")}
<script type="application/ld+json">{jsonld}</script>
<style>{css}
{SHARED_CSS}
.article{{max-width:760px;margin:0 auto;padding:36px 20px 60px}}
.article .back{{font-size:13px;color:var(--sub);display:inline-block;margin-bottom:18px}}
.article .back:hover{{color:var(--accent)}}
.article h1{{font-size:24px;font-weight:800;line-height:1.5;margin:12px 0 16px}}
.article .meta{{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--sub);flex-wrap:wrap}}
.article .body{{font-size:15.5px;line-height:1.9;color:var(--txt3);margin:20px 0}}
.article .card{{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px 22px;margin:18px 0}}
.article h4{{font-size:14px;font-weight:800;margin-bottom:10px}}
.article .vendor-row{{text-decoration:none}}
.source-section{{border-top:1px solid var(--line);margin:26px 0 18px;padding-top:16px}}
.source-heading{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:4px}}
.source-heading h4{{margin:0}}
.source-summary{{font-size:11.5px;color:var(--sub)}}
.source-group{{padding:10px 0;border-bottom:1px solid var(--soft)}}
.source-group-head{{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--txt3);margin-bottom:2px}}
.source-group-head b{{font-weight:700}}
.source-group-head span{{font-size:10.5px;color:var(--sub)}}
.source-report{{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:baseline;gap:14px;padding:4px 0;color:var(--ink);text-decoration:none;font-size:13px;line-height:1.55}}
.source-report:hover .source-report-title{{color:var(--accent)}}
.source-report-title{{min-width:0;overflow-wrap:anywhere}}
.source-report-date{{font-size:11px;color:var(--sub);font-variant-numeric:tabular-nums;white-space:nowrap}}
.source-more{{padding-top:8px}}
.source-more>summary{{width:max-content;max-width:100%;font-size:12px;color:var(--accent);cursor:pointer;list-style:none;padding:4px 0}}
.source-more>summary::-webkit-details-marker{{display:none}}
.source-more>summary::after{{content:" ↓"}}
.source-more[open]>summary::after{{content:" ↑"}}
@media(max-width:600px){{.source-report{{grid-template-columns:1fr;gap:0}}.source-report-date{{margin-top:1px}}}}
.fulltext .cb-heading{{font-size:17px;line-height:1.55;margin:24px 0 10px;color:var(--ink)}}
.fulltext p{{margin:0 0 14px}}
.fulltext strong{{font-weight:750;color:var(--ink)}}
.fulltext em{{font-style:italic}}
.fulltext a{{color:var(--blue);text-decoration:underline;text-underline-offset:2px;overflow-wrap:anywhere}}
.fulltext ul,.fulltext ol{{padding-left:24px;margin:8px 0 18px}}
.fulltext li{{margin:6px 0;padding-left:2px}}
.fulltext blockquote{{margin:16px 0;padding:10px 16px;border-left:4px solid var(--accent);background:var(--soft);border-radius:0 8px 8px 0;color:var(--txt2)}}
.fulltext code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:var(--soft);border:1px solid var(--line);border-radius:5px;padding:1px 5px}}
.fulltext pre{{overflow:auto;background:#171a20;color:#e8ebf0;border-radius:10px;padding:14px 16px;margin:16px 0;line-height:1.65}}
.fulltext pre code{{background:none;border:none;padding:0;color:inherit}}
.cb-table{{overflow-x:auto;overscroll-behavior-inline:contain;-webkit-overflow-scrolling:touch;margin:16px 0;border:1px solid var(--line);border-radius:9px}}
.cb-table:focus-visible{{outline:2px solid var(--blue);outline-offset:2px}}
.cb-table table{{border-collapse:collapse;width:100%;min-width:480px;font-size:13px}}
.cb-table th,.cb-table td{{padding:9px 12px;border-bottom:1px solid var(--line);border-right:1px solid var(--line);text-align:left;vertical-align:top}}
.cb-table th{{background:var(--soft);color:var(--ink);font-weight:700}}
.cb-table tr:last-child td{{border-bottom:none}}
.cb-figure{{margin:20px 0;background:var(--soft);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
.cb-media-link{{display:block;background:#f5f7fa;text-decoration:none}}
.cb-figure img{{display:block;width:100%;height:auto;max-height:72vh;object-fit:contain;margin:0 auto}}
.cb-figure figcaption{{display:flex;flex-direction:column;gap:7px;padding:10px 13px;font-size:12px;line-height:1.6;color:var(--txt2)}}
.cb-media-meta{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;color:var(--sub)}}
.cb-media-meta a{{font-size:11.5px}}
.cb-media-source{{margin-right:auto;overflow-wrap:anywhere}}
.cb-media-placeholder{{min-height:150px;display:grid;place-items:center;padding:24px;text-align:center;color:var(--sub);background:linear-gradient(135deg,var(--soft),var(--card))}}
@media(max-width:600px){{.cb-figure{{margin:16px -8px;border-radius:9px}}.cb-figure figcaption{{padding:9px 11px}}.cb-table{{max-width:100%;margin-left:0;margin-right:0}}}}
@media (prefers-color-scheme: dark){{.cb-media-link{{background:#171a20}}}}
.tone-accent{{color:var(--accent);font-weight:650}}.tone-warning{{color:var(--amber);font-weight:650}}
.tone-positive{{color:var(--green);font-weight:650}}.tone-info{{color:var(--blue);font-weight:650}}.tone-emphasis{{color:var(--ink);font-weight:650}}
.cta{{display:inline-block;background:var(--accent);color:#fff;font-size:14px;font-weight:700;border-radius:10px;padding:11px 26px;margin:6px 0 4px}}
.cta:hover{{opacity:.9}}
.fulltext h5.fh{{font-size:15px;font-weight:800;color:var(--ink);margin:20px 0 8px;padding-left:10px;border-left:3px solid var(--accent)}}
.fulltext p.fwarn{{font-size:12.5px;color:var(--amber);background:var(--accent-soft);border-radius:8px;padding:8px 12px}}
.fulltext p{{font-size:15px;line-height:1.95;color:var(--txt3);margin:0 0 14px}}
.tts-player{{display:grid;grid-template-columns:auto auto minmax(120px,1fr) auto auto;align-items:center;gap:10px 12px;background:linear-gradient(135deg,var(--card),var(--soft));border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:2px 0 18px}}
.tts-player[hidden]{{display:none}}
.tts-copy{{display:flex;flex-direction:column;min-width:112px;line-height:1.35}}
.tts-copy b{{font-size:12.5px;color:var(--ink)}}
.tts-copy span{{font-size:10.5px;color:var(--sub);margin-top:2px}}
.tts-toggle{{border:0;border-radius:99px;background:var(--ink);color:var(--card);font-size:12px;font-weight:750;padding:7px 13px;cursor:pointer;min-width:58px}}
.tts-progress{{width:100%;accent-color:var(--accent);cursor:pointer}}
.tts-time{{font-size:11px;color:var(--sub);font-variant-numeric:tabular-nums;white-space:nowrap}}
.tts-rate-label{{font-size:10.5px;color:var(--sub);display:flex;align-items:center;gap:4px}}
.tts-rate-label select{{border:1px solid var(--line);border-radius:7px;background:var(--card);color:var(--ink);font-size:11px;padding:4px 5px}}
@media(max-width:600px){{.tts-player{{grid-template-columns:1fr auto auto;gap:9px;padding:11px 12px}}.tts-copy{{grid-column:1/-1;grid-row:1;flex-direction:row;align-items:baseline;gap:8px}}.tts-toggle{{grid-column:1;grid-row:2}}.tts-time{{grid-column:2;grid-row:2}}.tts-rate-label{{grid-column:3;grid-row:2}}.tts-progress{{grid-column:1/-1;grid-row:3}}}}
@media(prefers-reduced-motion:reduce){{.tts-player *{{scroll-behavior:auto!important;transition:none!important}}}}
.disclaimer{{font-size:12px;color:var(--sub);border-top:1px dashed var(--line);padding-top:10px;margin-top:4px}}
.disclaimer a{{color:var(--accent)}}
</style></head><body class="has-sb mobile-detail" data-page="detail" data-event-id="{event_id}" data-category="{esc(e["category"])}" data-source="{main_src}">
{sidebar("home", prefix="../")}
<header class="detail-brand-header"><div class="wrap nav">
  <div class="logo"><a href="../index.html">Data<em>Hot</em></a><span class="tag">每 6 小时更新</span></div>
</div></header>
<div class="article">
  <div class="topbar detail-context">
    <a class="back" href="../index.html" style="margin-bottom:0">← 返回热榜</a>
    <span class="sharebtns">
      <button class="sbtn ghost favbtn" data-fav="{event_id}" title="收藏">{ic("star",13)}</button>
{("      " + tts_button) if tts_button else ""}
      {original_button}
      <button class="sbtn ghost" type="button" data-share-action="poster">海报</button>
      <button class="sbtn" type="button" data-share-action="open">分享</button>
    </span>
  </div>
  <div class="meta">
    <span class="srcbadge">{src_badge(main_src_name)}</span>
    <span style="font-weight:600;color:var(--txt3)">{esc(src_display(main_src_name))}</span>
    {'<span class="star">精选</span>' if e.get("star") else ''}
    <span title="发布时间">{("发布 " + fmt_date(e["published"])) if e.get("published") else "收录 " + fmt_date(e.get("first_seen"))}</span>
    {f'<span style="color:var(--sub);font-size:11px" title="DataHot 收录此内容的时间">收录于 {md(e.get("first_seen"))}</span>' if e.get("published") and e.get("first_seen") and e["published"][:10] != e["first_seen"][:10] else ""}
    <span style="margin-left:auto" class="heatnum">{ic("flame",13)} {e["heat"]}</span>
  </div>
  <h1>{esc(e["zh_title"])}</h1>
{("  " + tts_player) if tts_player else ""}
  <div class="body">{esc(e["zh_summary"])}</div>
  {f'<div class="why"><span><span class="w">{ic("sparkle",13)} 推荐理由：</span>{esc(clean_reason(e["reason"]))}</span></div>' if e.get("reason") else ""}
  {f'<div class="vendors" style="margin-top:14px">{vtags}</div>' if vtags else ""}
  {full_block}
{supplement_sources}
  <div class="card"><h4>{ic("list")} 相关事件</h4>{rel_html}</div>
</div>
<footer>DataHot，数据领域AI资讯分享 · <a href="../privacy.html">隐私</a> · <a href="https://github.com/henryhb1105-arch/datahot" target="_blank" rel="noopener noreferrer" style="color:var(--sub);text-decoration:underline">GitHub 开源</a></footer>
{tabbar("home", "../")}
{tts_script}
</body></html>'''
    return finalize_html_security(
        page.replace("</body></html>", share_ui(e, page_url) + "</body></html>")
    )

def share_ui(e, page_url):
    """详情页分享组件：Action Sheet（复制链接/海报/系统分享）+ Canvas 海报生成。普通字符串，非 f-string"""
    ev_json = json_for_html({
        "title": e["zh_title"], "summary": e.get("zh_summary", ""),
        "reason": e.get("reason", ""), "topic": (e.get("topics") or [""])[0],
        "heat": e["heat"], "source": src_display(detail_primary_item(e)["source"]),
        "date": (e.get("published") or e.get("first_seen") or "")[:10], "url": page_url,
    })
    return """
<div class="sh-mask" id="shMask" data-share-action="close"></div>
<div class="sh-sheet" id="shSheet"><div class="sh-panel">
  <div class="sh-group">
    <div class="sh-title">分享这条资讯</div>
    <button class="sh-opt" type="button" data-share-action="copy"><svg width="17" height="17" style="vertical-align:-3px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg> 复制链接</button>
    <button class="sh-opt" type="button" data-share-action="native"><svg width="17" height="17" style="vertical-align:-3px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 8l5-5 5 5"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg> 系统分享…</button>
  </div>
  <button class="sh-cancel" type="button" data-share-action="close">取消</button>
</div></div>
<div class="sh-poster-modal" id="shPoster">
  <div class="sh-poster-wrap"><img id="shPosterImg" alt="分享海报"></div>
  <div class="sh-poster-actions">
    <a class="sh-save" id="shSave" href="#" data-share-action="save">保存图片</a>
    <button class="sh-close" type="button" data-share-action="close">关闭</button>
  </div>
  <div class="sh-poster-tip">iOS 也可以长按图片保存</div>
</div>
<div class="sh-toast" id="shToast"></div>
<style>
.topbar{display:flex;align-items:center;justify-content:space-between;gap:12px;min-width:0;margin-bottom:14px}
.topbar .back{flex:0 0 auto;white-space:nowrap}
.sharebtns{display:flex;gap:8px;min-width:0;max-width:100%}
.sbtn{display:inline-flex;align-items:center;justify-content:center;gap:4px;flex:0 0 auto;white-space:nowrap;line-height:1.2;border:none;background:var(--accent);color:#fff;border-radius:99px;padding:7px 14px;font-size:12.5px;font-weight:600;cursor:pointer}
.sbtn svg{flex:0 0 auto}
.sbtn.ghost{background:var(--card);color:var(--ink);border:1px solid var(--line)}
.sbtn:active{transform:scale(.95)}
@media(max-width:960px){
.topbar.detail-context{position:sticky;top:0;z-index:55;margin:-36px -20px 16px;padding:calc(10px + env(safe-area-inset-top)) 20px 10px;background:var(--header-bg);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.topbar.detail-context .back{font-size:14px;font-weight:650;color:var(--ink)}
}
@media(max-width:600px){
.topbar{align-items:stretch;flex-direction:column;gap:10px}
.topbar.detail-context{margin:-20px -14px 14px;padding:calc(10px + env(safe-area-inset-top)) 14px 10px}
.sharebtns{width:100%;gap:6px;overflow-x:auto;padding-bottom:4px;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.sharebtns .sbtn{padding:7px 11px}
.sharebtns::-webkit-scrollbar{display:none}
}
.sh-mask{position:fixed;inset:0;background:rgba(0,0,0,.45);opacity:0;pointer-events:none;transition:.25s;z-index:80}
.sh-mask.show{opacity:1;pointer-events:auto}
.sh-sheet{position:fixed;left:0;right:0;bottom:0;z-index:90;transform:translateY(110%);transition:transform .3s cubic-bezier(.32,.72,.35,1);padding:0 10px calc(10px + env(safe-area-inset-bottom))}
.sh-sheet.show{transform:translateY(0)}
.sh-panel{max-width:430px;margin:0 auto}
.sh-group{background:var(--card);border-radius:16px;overflow:hidden;margin-bottom:8px}
.sh-title{font-size:12px;color:var(--sub);text-align:center;padding:12px;border-bottom:.5px solid var(--line)}
.sh-opt{display:flex;align-items:center;justify-content:center;gap:8px;padding:15px;font-size:16px;font-weight:500;border:none;border-bottom:.5px solid var(--line);cursor:pointer;background:none;width:100%;color:var(--ink)}
.sh-opt:last-child{border-bottom:none}
.sh-opt:active{background:var(--hover)}
.sh-cancel{background:var(--card);border-radius:16px;padding:15px;text-align:center;font-size:16px;font-weight:600;color:var(--blue);cursor:pointer;width:100%;border:none}
.sh-poster-modal{position:fixed;inset:0;z-index:95;background:rgba(15,17,20,.92);display:none;flex-direction:column;align-items:center;justify-content:center;padding:20px}
.sh-poster-modal.show{display:flex}
.sh-poster-wrap{width:min(340px,86vw);border-radius:18px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.sh-poster-wrap img{width:100%;display:block}
.sh-poster-actions{margin-top:18px;display:flex;gap:10px}
.sh-save,.sh-close{border:none;border-radius:99px;padding:11px 22px;font-size:14px;font-weight:600;cursor:pointer;text-decoration:none}
.sh-save{background:var(--accent);color:#fff}
.sh-close{background:rgba(255,255,255,.15);color:#fff}
.sh-poster-tip{margin-top:10px;font-size:11px;color:#8b919b}
.sh-toast{position:fixed;top:18%;left:50%;transform:translateX(-50%);background:rgba(26,29,35,.92);color:#fff;font-size:13px;padding:10px 20px;border-radius:99px;opacity:0;transition:.25s;z-index:99;pointer-events:none}
.sh-toast.show{opacity:1}
</style>
<script>
if(window.CanvasRenderingContext2D&&!CanvasRenderingContext2D.prototype.roundRect){
  CanvasRenderingContext2D.prototype.roundRect=function(x,y,w,h,r){this.rect(x,y,w,h);return this;};
}
function dhFavs(){try{return JSON.parse(localStorage.getItem('dh_favs')||'[]')}catch(e){return[]}}
(function(){
  var favs=dhFavs();
  document.querySelectorAll('[data-fav]').forEach(function(b){
    if(favs.indexOf(b.dataset.fav)>=0) b.classList.add('on');
    b.addEventListener('click',function(ev){
      ev.stopPropagation();
      var f=dhFavs(),id=b.dataset.fav,i=f.indexOf(id);
      if(i>=0){f.splice(i,1);b.classList.remove('on');}else{f.push(id);b.classList.add('on');}
      localStorage.setItem('dh_favs',JSON.stringify(f));
    });
  });
})();
var SH_EV = __EV_JSON__;
function shClose(){
  document.getElementById('shMask').classList.remove('show');
  document.getElementById('shSheet').classList.remove('show');
  document.getElementById('shPoster').classList.remove('show');
}
function openSheet(){
  document.getElementById('shMask').classList.add('show');
  document.getElementById('shSheet').classList.add('show');
}
function shToast(t){
  var el=document.getElementById('shToast'); el.textContent=t; el.classList.add('show');
  setTimeout(function(){el.classList.remove('show')},1600);
}
function shCopy(){
  shClose();
  function done(){shToast('链接已复制，去粘贴吧');}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(SH_EV.url).then(done,done);}
  else{var i=document.createElement('input');i.value=SH_EV.url;document.body.appendChild(i);i.select();try{document.execCommand('copy');}catch(e){} i.remove();done();}
}
function shSaveClick(ev){
  ev.preventDefault();
  if(!posterURL){return;}
  var blob=dataToBlob(posterURL);
  // iOS 相册直存：Web Share API 文件分享 → 原生面板选「存储图像」
  try{
    var file=new File([blob],'datahot-'+SH_EV.title.slice(0,20)+'.png',{type:'image/png'});
    if(navigator.canShare&&navigator.canShare({files:[file]})){
      navigator.share({files:[file],title:SH_EV.title}).then(function(){
        shToast('已调起系统分享，选择"存储图像"即可存入相册');
      }).catch(function(){});
      return;
    }
  }catch(e){}
  // 降级：新标签页打开，长按保存
  var bu=URL.createObjectURL(blob);
  var w=window.open(bu,'_blank');
  if(!w){shToast('请长按图片保存到相册');}
  else{shToast('已在新页面打开，长按图片保存');}
}
function shNative(){
  shClose();
  if(navigator.share){
    navigator.share({title:SH_EV.title,text:(SH_EV.reason||SH_EV.summary).slice(0,60)+' | DataHot',url:SH_EV.url}).catch(function(){});
  }else{shCopy();}
}
function wrapText(ctx,text,x,y,maxW,lineH,maxLines){
  var line='',lines=0;
  for(var i=0;i<text.length;i++){
    var t=line+text[i];
    if(ctx.measureText(t).width>maxW&&line){
      ctx.fillText(line,x,y);y+=lineH;lines++;line=text[i];
      if(lines>=maxLines-1){
        line=line+text.slice(i+1);
        while(ctx.measureText(line+'…').width>maxW&&line.length>1){line=line.slice(0,-1);}
        ctx.fillText(line+'…',x,y);return y+lineH;
      }
    }else{line=t;}
  }
  if(line){ctx.fillText(line,x,y);y+=lineH;}
  return y;
}
function posterPalette(dark){
  return dark ? {
    bg:['#1a1d23','#231d17','#33200f'], title:'#ffffff', sum:'#c9cdd4',
    reasonBg:'rgba(217,79,43,.14)', reasonHd:'#f5b48a', reasonTxt:'#f0d9cf',
    meta:'#8b919b', dash:'rgba(255,255,255,.18)', name:'#ffffff', foot:'#c9cdd4',
    qrBox:'#ffffff', qrBorder:null, topic:'#f5b48a', topicBd:'rgba(245,180,138,.7)'
  } : {
    bg:['#ffffff','#fdf8f4','#fdf0e9'], title:'#1a1d23', sum:'#4b5563',
    reasonBg:'rgba(217,79,43,.07)', reasonHd:'#d94f2b', reasonTxt:'#7c3a24',
    meta:'#6b7280', dash:'rgba(0,0,0,.15)', name:'#1a1d23', foot:'#6b7280',
    qrBox:'#ffffff', qrBorder:'rgba(0,0,0,.12)', topic:'#d94f2b', topicBd:'rgba(217,79,43,.5)'
  };
}
function posterLayout(x,W,P,qrImg){
  // 绘制一遍并返回内容结束 y（用于动态高度）
  var g=x.createLinearGradient(0,0,W,2000);
  g.addColorStop(0,P.bg[0]);g.addColorStop(.55,P.bg[1]);g.addColorStop(1,P.bg[2]);
  x.fillStyle=g;x.fillRect(0,0,W,2000);
  x.fillStyle='#d94f2b';x.beginPath();x.roundRect(64,60,72,72,18);x.fill();
  x.fillStyle='#fff';x.font='800 44px -apple-system,sans-serif';x.textBaseline='middle';
  x.fillText('D',88,98);
  x.fillStyle=P.name;x.font='800 38px -apple-system,sans-serif';x.fillText('DataHot',152,100);
  if(SH_EV.topic){
    x.font='500 26px -apple-system,PingFang SC,sans-serif';
    var tw=x.measureText(SH_EV.topic).width;
    x.strokeStyle=P.topicBd;x.lineWidth=2;
    x.beginPath();x.roundRect(W-64-tw-48,66,tw+48,56,28);x.stroke();
    x.fillStyle=P.topic;x.fillText(SH_EV.topic,W-64-tw-24,96);
  }
  var y=210;x.fillStyle=P.title;x.font='800 58px -apple-system,PingFang SC,sans-serif';x.textBaseline='top';
  y=wrapText(x,SH_EV.title,64,y,W-128,84,3)+16;
  x.fillStyle=P.sum;x.font='400 32px -apple-system,PingFang SC,sans-serif';
  y=wrapText(x,SH_EV.summary,64,y,W-128,52,5)+20;
  if(SH_EV.reason){
    // 先测量推荐理由行数，动态确定色块高度（不再截断在中间）
    var reasonLines=1,rl='',lineW=W-176;
    x.font='400 28px -apple-system,PingFang SC,sans-serif';
    for(var ri=0;ri<SH_EV.reason.length;ri++){
      var rt=rl+SH_EV.reason[ri];
      if(x.measureText(rt).width>lineW&&rl){reasonLines++;rl=SH_EV.reason[ri];}else{rl=rt;}
    }
    reasonLines=Math.min(reasonLines,3);
    var boxH=56+reasonLines*44+22;
    var ry=y+8;
    x.fillStyle=P.reasonBg;x.fillRect(64,ry,W-128,boxH);
    x.fillStyle='#d94f2b';x.fillRect(64,ry,8,boxH);
    x.fillStyle=P.reasonHd;x.font='700 28px -apple-system,PingFang SC,sans-serif';
    x.fillText('推荐理由',92,ry+26);
    x.fillStyle=P.reasonTxt;x.font='400 28px -apple-system,PingFang SC,sans-serif';
    wrapText(x,SH_EV.reason,92,ry+66,W-176,44,3);
    y=ry+boxH+30;
  }
  x.fillStyle=P.meta;x.font='400 26px -apple-system,sans-serif';
  x.fillText('热度 '+SH_EV.heat+' · '+SH_EV.source+' · '+SH_EV.date,64,y+4);
  y=y+4+56;
  // 分隔线 + 二维码区（紧跟内容，不再锚底）
  x.strokeStyle=P.dash;x.setLineDash([8,8]);x.lineWidth=2;
  x.beginPath();x.moveTo(64,y);x.lineTo(W-64,y);x.stroke();x.setLineDash([]);
  x.fillStyle=P.qrBox;x.beginPath();x.roundRect(64,y+36,150,150,14);x.fill();
  if(P.qrBorder){x.strokeStyle=P.qrBorder;x.lineWidth=2;x.beginPath();x.roundRect(64,y+36,150,150,14);x.stroke();}
  if(qrImg){x.drawImage(qrImg,74,y+46,130,130);}
  else{x.fillStyle='#666';x.font='400 22px sans-serif';x.fillText('扫码访问',88,y+118);}
  x.fillStyle=P.name;x.font='700 30px -apple-system,PingFang SC,sans-serif';
  x.fillText('扫码阅读全文编译',240,y+60);
  x.fillStyle=P.foot;x.font='400 24px -apple-system,PingFang SC,sans-serif';
  x.fillText('DataHot · 数据领域 AI 热榜',240,y+110);
  x.fillText('henryhb1105-arch.github.io/datahot',240,y+150);
  return y+186+56; // 二维码块底 + 下边距
}
function drawPoster(qrImg,dark){
  var P=posterPalette(dark),W=1080;
  var m=document.createElement('canvas');m.width=W;m.height=2000;
  var H=posterLayout(m.getContext('2d'),W,P,qrImg);
  var c=document.createElement('canvas');c.width=W;c.height=H;
  posterLayout(c.getContext('2d'),W,P,qrImg);
  return c.toDataURL('image/png');
}
var posterURL=null,posterDark=null;
function openPoster(){
  document.getElementById('shPoster').classList.add('show');
  var dark=window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches;
  if(posterURL&&posterDark===dark){return;}
  posterDark=dark;
  var qr=new Image();qr.crossOrigin='anonymous';
  qr.onload=function(){posterURL=drawPoster(qr,dark);showPoster();};
  qr.onerror=function(){posterURL=drawPoster(null,dark);showPoster();};
  qr.src='https://api.qrserver.com/v1/create-qr-code/?size=240x240&margin=0&data='+encodeURIComponent(SH_EV.url);
}
function dataToBlob(d){
  var p=d.split(','),m=p[0].match(/:(.*?);/)[1],b=atob(p[1]),a=new Uint8Array(b.length);
  for(var i=0;i<b.length;i++){a[i]=b.charCodeAt(i);}
  return new Blob([a],{type:m});
}
function showPoster(){
  document.getElementById('shPosterImg').src=posterURL;
  var a=document.getElementById('shSave');
  a.href=URL.createObjectURL(dataToBlob(posterURL)); a.target='_blank';a.rel='noopener noreferrer';
}
document.querySelectorAll('[data-share-action]').forEach(function(control){
  control.addEventListener('click',function(event){
    var action=control.dataset.shareAction;
    if(action==='open'){openSheet();}
    else if(action==='close'){shClose();}
    else if(action==='copy'){shCopy();}
    else if(action==='poster'){shClose();openPoster();}
    else if(action==='native'){shNative();}
    else if(action==='save'){shSaveClick(event);}
  });
});
</script>""".replace("__EV_JSON__", ev_json)

def render_topics_map(events, css):
    """主题地图页：只展示当前有内容的主题卡片。"""
    cards = ""
    for t in TOPICS_META:
        evs = [e for e in events if t["name"] in e.get("topics", [])]
        if not evs:
            continue
        latest = "".join(f'<div class="tt">· {esc(e["zh_title"][:36])}</div>' for e in evs[:3])
        cards += f'''<a class="tcard" href="topics/{t["slug"]}.html">
  <h3>{esc(t["name"])}</h3>
  <div class="td">{esc(t["desc"])}</div>
  <div class="tn">{len(evs)} 个事件 →</div>{latest}
</a>'''
    return page_shell("主题地图 · DataHot", "按主题看数据领域持续演进的技术与业务叙事", css, f'''
<div class="wrap" style="padding:28px 20px 60px;max-width:900px">
  <div class="section-title"><h2>{ic("map",18)} 主题地图</h2><span>按议题看数据领域 · 持续更新</span></div>
  <div class="tgrid">{cards}</div>
</div>''', tabbar("topics"), active="topics")

def render_topic_page(t, events, css):
    """单个主题页：导语 + 该主题事件时间轴"""
    evs = [e for e in events if t["name"] in e.get("topics", [])]
    vendors = sorted({v for e in evs for v in e.get("vendors", [])})
    vtags = "".join(f'<span class="vtag">{esc(v)}</span>' for v in vendors)
    must = sorted((e for e in evs if e.get("shelf") == "evergreen"),
                  key=lambda e: (not e.get("pinned"), -e.get("importance", 50)))
    must_html = ""
    if must:
        rows = "".join(
            f'<a class="crow" href="../{detail_url(e)}"><span class="cpin">{"📌" if e.get("pinned") else ""}</span>'
            f'<span class="ctitle">{esc(e["zh_title"])}</span><span class="cmeta">{(e.get("published") or e.get("first_seen") or "")[:10]}</span></a>'
            for e in must)
        must_html = f'<div class="scard" style="margin-bottom:18px"><h4 style="margin-bottom:6px">{ic("bookmark",14)} 本主题必读</h4>{rows}</div>'
    days = defaultdict(list)
    for e in evs:
        days[day_key(e.get("first_seen") or e["published"])].append(e)
    timeline = ""
    for d in sorted(days, reverse=True):
        timeline += f'<div class="day"><div class="day-head"><span class="date">{d.month}月{d.day}日</span><span class="info">{len(days[d])} 个事件</span></div>'
        timeline += "\n".join(render_card(e, prefix="../") for e in days[d])
        timeline += "</div>"
    body = f'''
<div class="wrap" style="padding:28px 20px 60px;max-width:900px">
  <a class="back" href="../topics.html" style="font-size:13px;color:var(--sub)">← 主题地图</a>
  <h1 style="font-size:26px;font-weight:800;margin:14px 0 6px">{esc(t["name"])}</h1>
  <p style="font-size:14px;color:var(--sub);margin-bottom:8px">{esc(t["desc"])}</p>
  <p style="font-size:12.5px;color:var(--sub);margin-bottom:18px">近 7 天收录 {len(evs)} 个事件 · 每 6 小时更新</p>
  {f'<div class="vendors" style="margin-bottom:18px">{vtags}</div>' if vtags else ""}
  {must_html}
  {timeline}
</div>'''
    return page_shell(f"{t['name']} · DataHot 主题", t["desc"], css, body, tabbar("topics", "../"), prefix="../", active="topics")

def page_shell(title, desc, css, body, tabbar_html, prefix="", active=""):
    return finalize_html_security(f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="icon" href="{prefix}favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="{prefix}icons/apple-touch-icon.png">
<meta name="theme-color" content="#1a1d23">
{feed_discovery()}
{analytics_head(prefix)}
<style>{css}
{SHARED_CSS}
</style></head><body class="has-sb mobile-section" data-nav-active="{esc(active)}">
{sidebar(active, prefix=prefix)}
<header class="section-brand-header"><div class="wrap nav">
  <div class="logo"><a href="{prefix}index.html" style="text-decoration:none">Data<em>Hot</em></a><span class="tag">每 6 小时更新</span></div>
</div></header>
{body}
<footer>DataHot，数据领域AI资讯分享 · <a href="{prefix}privacy.html">隐私</a> · <a href="https://github.com/henryhb1105-arch/datahot" target="_blank" rel="noopener noreferrer" style="color:var(--sub);text-decoration:underline">GitHub 开源</a></footer>
{tabbar_html}
</body></html>''')

def render_sources_page(events, payload, css):
    """公开信源页：信源目录、异常提示与单一推荐入口。"""
    ss_path = SITE / "data" / "sources_status.json"
    ss = json.load(open(ss_path)) if ss_path.exists() else {}
    all_sources = json.load(open(ROOT / "pipeline" / "sources.json"))
    gen = datetime.fromisoformat(payload["generated_at"])
    enabled_sources = [source for source in all_sources if source.get("enabled")]
    disabled_sources = [source for source in all_sources if not source.get("enabled")]

    def source_row(source, *, disabled=False):
        public_url = source_public_url(source)
        name = esc(source["name"])
        if public_url:
            name_html = (
                f'<a class="source-name" href="{esc(public_url)}" target="_blank" rel="noopener noreferrer" '
                f'data-analytics="outbound" data-source="{esc(source["name"])}">'
                f'{name}{ic("arrow", 13)}</a>'
            )
        else:
            name_html = f'<span class="source-name">{name}</span>'

        if disabled:
            reason = esc(source.get("note") or "暂不更新")
            return (
                f'<div class="source-row">{name_html}'
                f'<span class="source-disabled-reason">{reason}</span></div>'
            )

        focus = " · ".join(
            CAT_LABEL.get(category, category)
            for category in (source.get("focus_categories") or [])
        )
        focus_html = f'<span class="source-focus">{esc(focus)}</span>' if focus else ""
        fails = int((ss.get(source["name"]) or {}).get("fails", 0) or 0)
        health_html = (
            f'<span class="source-health">{"暂时异常" if fails >= 2 else "更新延迟"}</span>'
            if fails else ""
        )
        return f'<div class="source-row">{name_html}{focus_html}{health_html}</div>'

    group_specs = (
        ("官方与厂商", "vendor"),
        ("行业媒体", "media"),
        ("社区", "community"),
    )
    group_html = []
    for label, source_type in group_specs:
        sources = [source for source in enabled_sources if source.get("type") == source_type]
        if not sources:
            continue
        rows = "".join(source_row(source) for source in sources)
        group_html.append(f'''<section class="source-group">
  <div class="source-group-head"><h2>{label}</h2><span>{len(sources)} 个</span></div>
  <div class="source-list">{rows}</div>
</section>''')

    failed_sources = [
        source for source in enabled_sources
        if int((ss.get(source["name"]) or {}).get("fails", 0) or 0) > 0
    ]
    alert_html = ""
    if failed_sources:
        alert_html = (
            f'<div class="source-alert"><b>{len(failed_sources)} 个信源更新异常</b>'
            '其余信源继续正常更新，异常项已在下方标出。</div>'
        )

    disabled_html = ""
    if disabled_sources:
        rows = "".join(source_row(source, disabled=True) for source in disabled_sources)
        disabled_html = f'''<details class="source-disabled">
  <summary>已停用信源（{len(disabled_sources)}）</summary>
  <div class="source-list">{rows}</div>
</details>'''

    body = f'''
<div class="wrap source-page">
  <header class="source-intro">
    <h1>信源</h1>
    <p>DataHot 当前监控 {len(enabled_sources)} 个信源，覆盖 Data Agent、AI 数据平台、BI、数据产品和 AI 分析与洞察，每 6 小时更新。最后更新 {gen.strftime("%m-%d %H:%M")}。</p>
    {alert_html}
  </header>

  {''.join(group_html)}
  {disabled_html}

  <section class="source-contribute">
    <div class="source-contribute-copy">
      <h2>推荐新信源</h2>
      <p>没有你关注的官方博客、行业媒体或数据社区？</p>
    </div>
    <a class="source-cta" href="https://github.com/henryhb1105-arch/datahot/issues/new" target="_blank" rel="noopener noreferrer" data-analytics="outbound">推荐新信源</a>
  </section>

  <p class="source-principle">DataHot 优先收录官方发布、工程实践和有明确数据行业价值的内容；本站仅提供摘要与原文链接。</p>
</div>
'''
    return page_shell("信源 · DataHot", "DataHot 正在监控的公开信源与选源原则", css, body,
                      tabbar("sources"), prefix="", active="sources")

def render_hot_page(events, css):
    """完整榜单：热度 TOP 9"""
    top = rank_hot_events(events, limit=9, source_cap=2)
    rows = "".join(f'''<a class="hrow" href="{detail_url(e)}">
  <span class="rk">{i}</span>
  <span class="ht">{esc(e["zh_title"])}</span>
  <span class="hm">{ic("flame",12)} {e["heat"]} · {esc(e["items"][0]["source"])}{extra}</span>
</a>''' for i, e in enumerate(top, 1)
        for extra in [f' · 另有{len(e["items"])-1}家' if len(e["items"]) > 1 else ""])
    body = f"""
<div class="wrap" style="padding:28px 20px 60px;max-width:900px">
  <div class="section-title"><h2>{ic("flame",18)} 完整榜单</h2><span>近 7 天 · 热度 TOP 9 · 同源最多 2 条</span></div>
  <div class="scard" style="padding:6px 18px">{rows}</div>
  <div style="font-size:12px;color:var(--sub);margin-top:8px">热度 = {HEAT_FORMULA}；相邻位置优先保持信源多样性</div>
</div>"""
    return page_shell("完整榜单 · DataHot", "数据领域近 7 天热度 TOP 9", css, body, tabbar("home"), prefix="", active="hot")

def render_classics_page(events, css):
    """典藏页：evergreen 内容按主题分组沉淀，人工置顶优先，按重要性排序"""
    classics = [e for e in events if e.get("shelf") == "evergreen"]
    classics.sort(key=lambda e: (not e.get("pinned"), -e.get("importance", 50)))
    groups = ""
    used = set()
    for t in TOPICS_META:
        evs = [e for e in classics if t["name"] in e.get("topics", [])]
        if not evs:
            continue
        used.update(e["event_id"] for e in evs)
        rows = "".join(
            f'''<a class="crow" href="{detail_url(e)}">
  <span class="cpin">{"📌" if e.get("pinned") else ""}</span>
  <span class="ctitle">{esc(e["zh_title"])}</span>
  <span class="cmeta">{esc(e["items"][0]["source"])} · {(e.get("published") or e.get("first_seen") or "")[:10]}</span>
</a>''' for e in evs)
        groups += f'<div class="scard"><h4 style="margin-bottom:6px">{ic("bookmark",14)} {esc(t["name"])} <span style="font-size:11px;color:var(--sub);font-weight:400">{len(evs)} 篇</span></h4>{rows}</div>'
    other = [e for e in classics if e["event_id"] not in used]
    if other:
        rows = "".join(
            f'''<a class="crow" href="{detail_url(e)}">
  <span class="cpin">{"📌" if e.get("pinned") else ""}</span>
  <span class="ctitle">{esc(e["zh_title"])}</span>
  <span class="cmeta">{esc(e["items"][0]["source"])} · {(e.get("published") or e.get("first_seen") or "")[:10]}</span>
</a>''' for e in other)
        groups += f'<div class="scard"><h4 style="margin-bottom:6px">{ic("bookmark",14)} 综合 <span style="font-size:11px;color:var(--sub);font-weight:400">{len(other)} 篇</span></h4>{rows}</div>'
    if not classics:
        groups = '<div class="scard" style="color:var(--sub);font-size:13px">典藏池正在积累中——AI 会识别方法论/框架/深度实践类内容自动沉淀，主编也可人工置顶。</div>'
    body = f'''
<div class="wrap" style="padding:28px 20px 60px;max-width:900px">
  <div class="section-title"><h2>{ic("bookmark",18)} 典藏</h2><span>穿越时间的内容 · 方法论 / 框架 / 深度实践</span></div>
  <div class="scard" style="font-size:13px;color:var(--txt2);line-height:1.8">
    这里收录<b>不随时间贬值</b>的内容：经典方法论、框架指南、深度实践。AI 初筛 + 主编人工策展，永久沉淀，按主题分组。共 {len(classics)} 篇。
  </div>
  {groups}
</div>'''
    return page_shell("典藏 · DataHot", "数据领域穿越时间的内容：方法论、框架与深度实践", css, body,
                      tabbar("classics"), prefix="", active="classics")

def render_favorites_page(css, data_url="data/latest-lite.json"):
    """收藏页：只拉 metadata-only 数据；详情正文留在详情页。"""
    body = """
<div class="wrap" style="padding:28px 20px 60px;max-width:900px">
  <div class="section-title"><h2>★ 我的收藏</h2><span>保存在本机浏览器 · 不上传</span></div>
  <div class="scard" style="padding:6px 18px" id="favList"><div style="padding:14px 0;color:var(--sub);font-size:13px">加载中…</div></div>
</div>
<script>
(function(){
  var list=document.getElementById('favList');
  var favs=[];
  try{favs=JSON.parse(localStorage.getItem('dh_favs')||'[]')}catch(e){}
  if(!favs.length){
    list.innerHTML='<div style="padding:20px 0;color:var(--sub);font-size:13px;line-height:1.8">还没有收藏。<br>在时间轴卡片或详情页点 ☆ 星标，内容会出现在这里。</div>';
    return;
  }
  function safe(v){return String(v||'').replace(/[&<>\"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c];});}
  fetch('__DATA_URL__').then(function(r){return r.json();}).then(function(d){
    var map=Object.create(null);
    d.events.forEach(function(e){map[e.event_id]=e;});
    var html='';
    favs.forEach(function(id){
      var e=map[id];
      if(!e) return;
      html+='<a class="hrow" href="e/'+encodeURIComponent(String(e.event_id||''))+'.html">'
        +'<span class="ht">'+safe(e.zh_title)+'</span>'
        +'<span class="hm">'+safe(e.items[0]?e.items[0].source:'')+' · '+safe((e.published||e.first_seen||'').slice(0,10))+'</span></a>';
    });
    list.innerHTML=html||'<div style="padding:20px 0;color:var(--sub);font-size:13px">收藏的内容已过期（超过 7 天的新闻会出池，典藏内容永久保留）。</div>';
  }).catch(function(){
    list.innerHTML='<div style="padding:20px 0;color:var(--sub);font-size:13px">加载失败，请稍后再试。</div>';
  });
})();
</script>"""
    body = body.replace("__DATA_URL__", esc(data_url))
    return page_shell("我的收藏 · DataHot", "你收藏的数据领域资讯", css, body, tabbar("favorites"), prefix="", active="favorites")


def load_weekly_brief(path=None):
    path = Path(path) if path is not None else SITE / "data" / "weekly_brief.json"
    try:
        brief = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return brief if valid_weekly_brief(brief) else None


def load_weekly_archive(path=None):
    path = Path(path) if path is not None else SITE / "data" / "weekly"
    briefs = []
    if not path.exists():
        return briefs
    for item in path.glob("*.json"):
        brief = load_weekly_brief(item)
        if brief:
            briefs.append(brief)
    return sorted(briefs, key=lambda brief: str(brief.get("week_id") or ""), reverse=True)


def render_weekly_brief_teaser(brief):
    if not brief:
        return '''<a class="weekly-waiting" href="weekly.html" data-analytics="weekly_brief">
  <b>每周简报整理中</b>
  <span>首页与热榜可正常浏览 →</span>
</a>'''
    return f'''<a class="weekly-teaser" href="weekly.html" data-analytics="weekly_brief">
  <div class="weekly-kicker">WEEKLY BRIEF · 每周精选</div>
  <h2>{esc(brief.get("title"))}</h2>
  <p>{esc(brief.get("bottom_line"))}</p>
  <div class="weekly-meta">{esc(brief.get("period_start"))} 至 {esc(brief.get("period_end"))} · {len(brief.get("for_you", []))} 个信号 · 约 3 分钟读完 →</div>
</a>'''


def _weekly_archive_nav(archives, current_week_id, *, archive_prefix):
    if not archives:
        return ""
    links = []
    for archive in archives:
        week_id = str(archive.get("week_id") or "")
        if not re.fullmatch(r"\d{4}-W\d{2}", week_id):
            continue
        links.append(
            f'<a class="{"on" if week_id == current_week_id else ""}" '
            f'href="{archive_prefix}{week_id}.html">{esc(week_id)}</a>'
        )
    return f'<div class="weekly-archive"><span style="font-size:12px;color:var(--sub);padding:6px 2px">历史周报</span>{"".join(links)}</div>'


def _safe_source_url(value):
    return sanitize_url(value)


def render_weekly_brief_page(
    brief, events, css, *, prefix="", archives=None, archive_prefix="weekly/",
):
    if not brief:
        body = '''
<div class="wrap" style="padding:28px 20px 60px;max-width:860px">
  <div class="section-title"><h2>每周简报</h2><span>每周一发布</span></div>
  <div class="scard" style="font-size:13.5px;color:var(--txt2);line-height:1.8">本期周报正在进行跨事件聚类、历史基线比较和证据校验。AI 或校验暂时不可用时不会发布规则摘要；首页、热榜和详情页仍可正常浏览。</div>
</div>'''
        return page_shell(
            "每周简报 · DataHot", "DataHot 每周数据 AI 高价值事件简报", css, body,
            tabbar("weekly", prefix), prefix=prefix, active="weekly",
        )

    event_map = {event["event_id"]: event for event in events}
    item_map = {
        str(item.get("event_id") or ""): item
        for item in brief.get("items", []) if isinstance(item, dict)
    }
    signal_map = {
        str(signal.get("signal_id") or ""): signal
        for signal in brief.get("signals", []) if isinstance(signal, dict)
    }
    change_labels = {
        "early_signal": "早期信号", "new": "新出现", "strengthening": "明显增强",
        "continuing": "延续", "cooling": "降温", "unknown": "暂无法判断",
    }
    confidence_labels = {"high": "高置信", "medium": "中等置信", "low": "低置信"}
    priority_classes = {
        "现在行动": "priority-now", "安排测试": "priority-test",
        "继续观察": "priority-watch", "暂时忽略": "priority-ignore",
    }

    theme_rows = []
    for item in brief.get("for_you", []):
        signal = signal_map.get(str(item.get("signal_id") or ""))
        if not signal:
            continue
        priority = str(item.get("priority") or "继续观察")
        theme_rows.append(f'''<article class="weekly-theme">
  <div class="weekly-badges">
    <span class="weekly-pill {priority_classes.get(priority, 'priority-watch')}">{esc(priority)}</span>
    <span class="weekly-pill">{esc(change_labels.get(signal.get("change_type"), signal.get("change_type")))}</span>
    <span class="weekly-pill">{esc(confidence_labels.get(signal.get("confidence"), signal.get("confidence")))}</span>
  </div>
  <h2>{esc(signal.get("title"))}</h2>
  <div class="weekly-anchor"><b>具体锚点</b>　{esc(signal.get("anchor"))}</div>
  <p>{esc(item.get("insight"))}</p>
  <div class="weekly-why"><b>这对你意味着什么</b>　{esc(item.get("why_it_matters"))}</div>
  <div class="weekly-action"><b>{esc(priority)}</b>{esc(item.get("action"))}</div>
  <div class="weekly-signal-meta">{esc(signal.get("baseline_comparison"))} · {esc(signal.get("confidence_reason"))}</div>
</article>''')
    themes = "".join(theme_rows) or '''<div class="scard" style="font-size:13.5px;color:var(--txt2);line-height:1.8">本周没有形成足以改变产品路线或投入判断的新信号。宁缺毋滥，本期不拼凑主题。</div>'''

    evidence_rows = []
    for index_item in brief.get("evidence_index", []):
        event_id = str(index_item.get("event_id") or "")
        stored = item_map.get(event_id, {})
        event = event_map.get(event_id)
        source = stored.get("source") or (((event or {}).get("items") or [{}])[0].get("source") or "")
        if event is not None:
            href = f"{prefix}e/{event_id}.html"
            outbound = ""
            destination = "站内详情"
        else:
            href = _safe_source_url(stored.get("source_url")) or f"{prefix}weekly.html"
            outbound = ' target="_blank" rel="noopener noreferrer" data-analytics="outbound"' if href.startswith("http") else ""
            destination = "原始信源 ↗" if href.startswith("http") else "证据快照"
        evidence_rows.append(f'''<a class="weekly-evidence-row" href="{esc(href)}"{outbound} data-analytics-list="1" data-event-id="{esc(event_id)}" data-source="{esc(source)}">
  <span>{esc(index_item.get("title"))}</span>
  <span>{esc(source)} · {destination}</span>
</a>''')
    evidence = "".join(evidence_rows)
    evidence_section = f'''<details class="weekly-evidence">
  <summary>证据索引 · {len(evidence_rows)} 条（默认折叠）</summary>
  {evidence}
</details>''' if evidence_rows else ""

    baseline = brief.get("baseline") or {}
    baseline_text = {
        "complete": "过去 4 周基线完整",
        "partial": f"历史基线 {int(baseline.get('available_weeks') or 0)}/4 周",
        "missing": "暂无历史基线，按早期信号处理",
    }.get(baseline.get("coverage"), "历史基线待确认")
    archive_nav = _weekly_archive_nav(
        archives or [], str(brief.get("week_id") or ""), archive_prefix=archive_prefix,
    )
    body = f'''
<div class="wrap" style="padding:28px 20px 60px;max-width:860px">
  <div class="section-title"><h2>{ic("calendar",18)} 每周情报</h2><span>{esc(brief.get("period_start"))} 至 {esc(brief.get("period_end"))} · 每周一次</span></div>
  {archive_nav}
  <div class="scard weekly-summary">
    <div class="weekly-kicker">DATAHOT WEEKLY · {esc(brief.get("period_start"))} 至 {esc(brief.get("period_end"))}</div>
    <h1>{esc(brief.get("title"))}</h1>
    <p>{esc(brief.get("bottom_line"))}</p>
    <div class="weekly-meta" style="margin-top:10px;color:#aeb4be;font-size:11px">{len(theme_rows)} 个信号 · 约 3 分钟读完 · {esc(baseline_text)} · {fmt_date(brief.get("generated_at"))} 更新</div>
  </div>
  <div class="section-title"><h2>本周与你有关</h2><span>最多 3 个，不凑数</span></div>
  <div class="weekly-themes">{themes}</div>
  <div class="section-title"><h2>判断边界</h2><span>反证、缺口与下周验证</span></div>
  <div class="weekly-secondary">
    <div class="scard"><b>不要过度解读</b>{esc(brief.get("what_not_to_overread"))}</div>
    <div class="scard"><b>当前不确定性</b>{esc(brief.get("uncertainty"))}</div>
    <div class="scard"><b>下周验证问题</b>{esc(brief.get("next_week_question"))}</div>
  </div>
  {f'<div class="section-title"><h2>证据</h2><span>标题仅在索引中出现</span></div>{evidence_section}' if evidence_section else ''}
</div>'''
    return page_shell(
        f"{brief.get('week_id')} 每周情报 · DataHot", brief.get("bottom_line") or "DataHot 每周情报",
        css, body, tabbar("weekly", prefix), prefix=prefix, active="weekly",
    )


def render_legacy_daily_redirect():
    return finalize_html_security('''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="0; url=weekly.html">
<link rel="canonical" href="weekly.html">
<title>简报已升级 · DataHot</title></head>
<body><p>每日简报已升级为每周简报。<a href="weekly.html">前往最新周报 →</a></p></body></html>''')


def render_privacy_page(css):
    body = f'''
<div class="wrap" style="padding:28px 20px 60px;max-width:760px">
  <div class="section-title"><h2>{ic("file",18)} 隐私与匿名统计</h2><span>最小化 · 可关闭 · 不跨站</span></div>
  <div class="scard" style="font-size:13.5px;color:var(--txt2);line-height:1.85">
    <p>DataHot 的匿名行为统计默认关闭，只有站点配置了 HTTPS 第一方接收端后才会启用。启用时仅记录页面类型、事件 ID、分类、来源、匿名会话与 30 天轮换的随机设备 ID。</p>
    <p style="margin-top:10px"><b>不会采集：</b>正文内容、完整搜索词、Cookie、姓名/邮箱、API Key、浏览器指纹、精确位置或跨站行为。浏览器的 Global Privacy Control / Do Not Track 会被自动尊重。</p>
    <p style="margin-top:10px"><b>搜索：</b>只记录长度区间（1–3 / 4–8 / 9+）和结果数量，不发送输入文字。</p>
  </div>
  <div class="scard">
    <div data-analytics-status style="font-size:13px;color:var(--txt2);margin-bottom:12px">读取状态中…</div>
    <button class="privacy-btn" data-analytics-opt-out>关闭匿名统计并删除本机随机 ID</button>
    <button class="privacy-btn ghost" data-analytics-opt-in>恢复匿名统计</button>
  </div>
</div>'''
    return page_shell(
        "隐私与匿名统计 · DataHot", "DataHot 的隐私友好匿名统计说明与关闭开关",
        css, body, tabbar("privacy"), prefix="", active="privacy",
    )

def write_detail_pages(all_events, css, detail_dir=None, tts_manifest=None, site_root=SITE):
    """All events retained in latest.json keep a stable detail page."""
    detail_dir = Path(detail_dir) if detail_dir is not None else DETAIL_DIR
    detail_dir.mkdir(parents=True, exist_ok=True)
    valid_ids = set()
    tts_manifest = tts_manifest or {"items": {}}
    for event in all_events:
        event_id = safe_event_id(event["event_id"])
        filename = event_id + ".html"
        valid_ids.add(filename)
        (detail_dir / filename).write_text(
            render_detail(
                event, all_events, css,
                tts_item=tts_item_for_event(tts_manifest, event_id, site_root=site_root),
            ), encoding="utf-8",
        )
    for path in detail_dir.glob("*.html"):
        if path.name not in valid_ids:
            path.unlink()
    return valid_ids


def main():
    SITE.mkdir(parents=True, exist_ok=True)
    if not ANALYTICS_ASSET.exists() or not HOME_ASSET.exists() or not TTS_ASSET.exists():
        raise FileNotFoundError("missing browser asset")
    shutil.copyfile(ANALYTICS_ASSET, SITE / "analytics.js")
    shutil.copyfile(HOME_ASSET, SITE / "home.js")
    shutil.copyfile(TTS_ASSET, SITE / "tts-player.js")
    payload = json.load(open(SITE / "data" / "latest.json"))
    all_events = payload["events"]
    for event in all_events:
        safe_event_id(event.get("event_id"))
    qualified_events = [event for event in all_events if is_list_eligible(event)]
    weekly_enabled = weekly_brief_enabled()
    weekly_brief = load_weekly_brief() if weekly_enabled else None
    weekly_archives = load_weekly_archive() if weekly_enabled else []
    if weekly_brief and all(
        item.get("week_id") != weekly_brief.get("week_id") for item in weekly_archives
    ):
        weekly_archives.insert(0, weekly_brief)
    gen = datetime.fromisoformat(payload["generated_at"])
    css = load_css()
    # 首页以发布时间为准；缺少发布时间才使用收录时间，旧文补录不冒充当天新闻。
    window = timedelta(days=HOME_WINDOW_DAYS)
    window_events = []
    for event in all_events:
        timestamp = event_timestamp(event)
        if timestamp and gen - timestamp.astimezone(TZ) <= window:
            window_events.append(event)
    # 热点保持近 7 天；时间轴使用全部在站合格内容，避免旧洞察无法发现。
    hot_window_events = select_home_events(window_events)
    timeline_events = select_timeline_events(all_events)
    lite_enabled = lite_home_enabled()
    home_ranking = rank_timeline_events(
        timeline_events, page_size=DEFAULT_PAGE_SIZE,
        source_caps=FIRST_PAGE_SOURCE_CAPS, prevent_adjacent_sources=True,
    )
    home_first_page = home_ranking[:DEFAULT_PAGE_SIZE]
    lite_payload = build_lite_payload(
        all_events, payload["generated_at"], ranking=home_ranking, page_size=DEFAULT_PAGE_SIZE,
    )
    violations = find_forbidden_fields(lite_payload)
    if violations:
        raise RuntimeError(f"latest-lite.json contains forbidden body fields: {', '.join(violations[:5])}")
    lite_path = SITE / "data" / "latest-lite.json"
    lite_bytes = (json.dumps(lite_payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    full_bytes = (SITE / "data" / "latest.json").stat().st_size
    if len(lite_bytes) >= full_bytes:
        raise RuntimeError(f"latest-lite.json must be smaller than latest.json ({len(lite_bytes)} >= {full_bytes})")
    lite_path.write_bytes(lite_bytes)
    reduction = round((1 - len(lite_bytes) / full_bytes) * 100, 1)
    print(f"[lite] latest.json {full_bytes:,} B → latest-lite.json {len(lite_bytes):,} B（减少 {reduction}%）")

    # ── 详情页 ──
    valid_ids = write_detail_pages(
        all_events, css, tts_manifest=load_tts_manifest(), site_root=SITE,
    )

    # ── Atom 1.0 Feed：只包含 DataHot 摘要与稳定站内详情链接 ──
    feed_path = SITE / "feed.xml"
    if feed_enabled():
        feed_payload = build_atom_feed(hot_window_events, payload["generated_at"], site_base=SITE_BASE)
        feed_errors = validate_atom_feed(feed_payload, site_base=SITE_BASE, site_root=SITE)
        if feed_errors:
            raise RuntimeError(f"invalid Atom feed: {', '.join(feed_errors)}")
        feed_path.write_bytes(feed_payload)
        print(f"[feed] Atom 1.0 校验通过：{feed_payload.count(b'<entry>')} 条")
    elif feed_path.exists():
        feed_path.unlink()

    # ── 主题地图 + 主题页 ──
    TOPIC_DIR.mkdir(parents=True, exist_ok=True)
    (SITE / "topics.html").write_text(render_topics_map(qualified_events, css), encoding="utf-8")
    valid_topic_slugs = set()
    for t in TOPICS_META:
        if any(t["name"] in e.get("topics", []) for e in qualified_events):
            valid_topic_slugs.add(t["slug"] + ".html")
            (TOPIC_DIR / (t["slug"] + ".html")).write_text(render_topic_page(t, qualified_events, css), encoding="utf-8")
    for f in TOPIC_DIR.glob("*.html"):
        if f.name not in valid_topic_slugs:
            f.unlink()

    # ── 热点榜：继续使用近 7 天合格池和来源上限 ──
    hot_cards = ""
    top_ids = [event["event_id"] for event in rank_hot_events(hot_window_events, limit=3, source_cap=2)]
    payload["top"] = top_ids
    for n, eid in enumerate(top_ids, 1):
        e = next((x for x in hot_window_events if x["event_id"] == eid), None)
        if not e:
            continue
        hot_cards += f'''<div class="hot" data-link="{detail_url(e)}" data-analytics-list="1" data-event-id="{safe_event_id(e["event_id"])}" data-category="{esc(e["category"])}" data-source="{esc(e["items"][0]["source"])}"><span class="rank">TOP {n}</span><span class="heat">{ic("flame",12)} {e["heat"]}</span>
        <h3><a href="{detail_url(e)}">{esc(e["zh_title"])}</a></h3>
        <p class="hsum">{esc(e["zh_summary"])}</p>
        <div class="sources"><span class="srcbadge">{src_badge(e["items"][0]["source"])}</span>{sources_html(e)}<span class="htime">{card_time(e)}</span></div></div>'''

    # ── 时间轴 ──
    initial_events = home_first_page if lite_enabled else home_ranking
    days = defaultdict(list)
    for e in initial_events:
        timestamp = event_timestamp(e)
        if timestamp:
            days[timestamp.astimezone(TZ).date()].append(e)
    timeline = ""
    for d in sorted(days, reverse=True):
        head = f'{d.month}月{d.day}日'
        info = f'星期{WEEK_CN[d.weekday()]} · {len(days[d])} 个事件'
        timeline += f'<div class="day"><div class="day-head"><span class="date">{head}</span><span class="info">{info}</span></div>'
        timeline += "\n".join(render_card(e) for e in days[d])
        timeline += "</div>"

    # ── 厂商热榜 ──
    vendor_count = defaultdict(int)
    for e in hot_window_events:
        for v in e.get("vendors", []):
            vendor_count[v] += 1
    vrows = "".join(
        f'<div class="vendor-row"><span class="n">{n}</span>{esc(v)}<span class="count">{c} 条</span></div>'
        for n, (v, c) in enumerate(sorted(vendor_count.items(), key=lambda x: -x[1])[:8], 1))
    if not vrows:
        vrows = '<div style="font-size:12.5px;color:var(--sub)">暂无数据</div>'

    ok = sum(1 for s in payload["sources"] if s["ok"])
    bad = [s["name"] for s in payload["sources"] if not s["ok"]]
    bad_txt = "、".join(bad) if bad else "无"

    # 首页筛选顺序保持稳定；短名称只用于显示，底层筛选值继续兼容旧 URL。
    topic_fchips = render_home_filter_chips(timeline_events)
    weekly_teaser = render_weekly_brief_teaser(weekly_brief) if weekly_enabled else ""
    weekly_header_link = f'<a class="tab d-only" href="weekly.html" style="text-decoration:none">{ic("calendar",14)} 周报</a>' if weekly_enabled else ""
    home_config = (
        f'<meta id="homeDataConfig" data-lite-url="data/latest-lite.json" '
        f'data-page-size="{DEFAULT_PAGE_SIZE}" data-total="{len(timeline_events)}">'
        if lite_enabled else ""
    )
    timeline_html = f'<div id="timeline">{timeline}</div>' if lite_enabled else timeline
    load_more = (
        f'<button class="load-more" id="loadMore" type="button" '
        f'{"hidden" if len(timeline_events) <= DEFAULT_PAGE_SIZE else ""}>'
        f'加载更多（{len(home_first_page)}/{len(timeline_events)}）</button>'
        if lite_enabled else ""
    )
    home_asset = '<script defer src="home.js"></script>' if lite_enabled else ""

    page = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>DataHot · 数据领域 AI 热榜</title>
<meta name="description" content="监控 Data Agent、AI 数据平台、BI、数据产品、AI 分析与洞察五个领域的资讯热榜，多信源聚簇 + AI 中文摘要与推荐理由，每 6 小时更新。">
<meta property="og:title" content="DataHot · 数据领域 AI 热榜">
<meta property="og:description" content="Data Agent / AI 数据平台 / BI / 数据产品 / AI 分析与洞察的热点，每 6 小时自动更新。">
<meta property="og:type" content="website">
<link rel="icon" href="favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="icons/favicon-32.png">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<link rel="manifest" href="icons/manifest.json">
<meta name="theme-color" content="#1a1d23">
{feed_discovery()}
{analytics_head("")}
{home_config}
{home_asset}
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="DataHot">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<style>{css}
{SHARED_CSS}
.item a:hover{{color:var(--accent)}}
.hot a:hover{{color:var(--accent)}}
#ptr{{position:fixed;top:0;left:0;right:0;height:0;overflow:hidden;display:flex;align-items:flex-end;justify-content:center;background:var(--bg);z-index:60;transition:height .12s ease-out}}
#ptr span{{font-size:12.5px;color:var(--sub);padding-bottom:8px}}
</style></head><body class="has-sb home-page" data-page="home">
{sidebar("home", gen)}
<div id="ptr"><span>下拉刷新</span></div>
<header class="home-header"><div class="wrap nav">
  {render_home_brand_update(gen)}
  {weekly_header_link}
  <a class="tab d-only" href="topics.html" style="text-decoration:none">{ic("map",14)} 主题</a>
  <a class="tab d-only" href="classics.html" style="text-decoration:none">{ic("bookmark",14)} 典藏</a>
  <a class="tab d-only" href="sources.html" style="text-decoration:none">{ic("rss",14)} 信源</a>
</div></header>

<div class="wrap"><div class="layout"><main>
  {weekly_teaser}
  <div class="section-title"><h2>{ic("flame",18)} 本期热点</h2><span>多信源聚簇 · 按热度排序</span><a href="hot.html" style="margin-left:auto;font-size:12.5px;color:var(--accent);font-weight:600">完整榜单 →</a></div>
  <div class="hotlist">{hot_cards}</div>
  {render_timeline_toolbar(len(timeline_events))}
  <div class="chiprow" id="chiprow">
    <span class="fchip on" data-topic="all">全部</span>
    {topic_fchips}
  </div>
  {timeline_html}
  {load_more}
</main>

<aside>
  <div class="card"><h4>{ic("building")} 厂商热榜 <span style="font-size:11px;color:var(--sub);font-weight:400">近7天</span></h4>{vrows}</div>
  <div class="card"><h4>{ic("tag")} 栏目说明</h4><div class="legend">
    <div class="row"><span class="badge b-agent">Data Agent</span>ChatBI · NL2SQL · 分析 Agent</div>
    <div class="row"><span class="badge b-platform">AI 数据平台</span>湖仓 · 语义层 · 数据治理</div>
    <div class="row"><span class="badge b-bi">BI 与可视化</span>BI 厂商 · 报表 · 可视化</div>
    <div class="row"><span class="badge b-product">数据产品</span>方法论 · 融资并购 · 报告</div>
    <div class="row"><span class="badge b-insight">AI 分析与洞察</span>组织人才 · 经营增长 · 风险决策</div>
  </div></div>
  <div class="card"><h4>{ic("clock")} 更新状态</h4><div class="status">
    最后更新：<b>{gen.strftime("%Y-%m-%d %H:%M")}</b><br>
    信源正常：<b>{ok}/{len(payload["sources"])}</b> · 在站事件 <b>{len(timeline_events)} 个</b><br>
    信源异常：{esc(bad_txt)}
  </div></div>
</aside>
</div></div>

<footer>DataHot，数据领域AI资讯分享 · <a href="privacy.html">隐私</a> · <a href="https://github.com/henryhb1105-arch/datahot" target="_blank" rel="noopener noreferrer" style="color:var(--sub);text-decoration:underline">GitHub 开源</a></footer>
{tabbar("home")}

<script>
// 收藏（localStorage）
function dhFavs(){{try{{return JSON.parse(localStorage.getItem('dh_favs')||'[]')}}catch(e){{return[]}}}}
function showFavTp(t){{
  let tp=document.getElementById('favtp');
  if(!tp){{tp=document.createElement('div');tp.id='favtp';tp.style.cssText='position:fixed;top:16%;left:50%;transform:translateX(-50%);background:rgba(26,29,35,.92);color:#fff;font-size:13px;padding:9px 20px;border-radius:99px;z-index:99;transition:opacity .3s';document.body.appendChild(tp);}}
  tp.textContent=t;tp.style.opacity='1';clearTimeout(tp._t);tp._t=setTimeout(()=>{{tp.style.opacity='0';}},1400);
}}
function dhInitFav(){{
  const favs=dhFavs();
  document.querySelectorAll('[data-fav]').forEach(b=>{{
    if(b.dataset.favBound==='1') return;
    b.dataset.favBound='1';
    if(favs.includes(b.dataset.fav)) b.classList.add('on');
    b.addEventListener('click',ev=>{{
      ev.stopPropagation();
      let f=dhFavs();const id=b.dataset.fav;const i=f.indexOf(id);
      if(i>=0){{f.splice(i,1);b.classList.remove('on');showFavTp('已取消收藏');}}else{{f.push(id);b.classList.add('on');showFavTp('已收藏 · 底部「收藏」Tab 可见');}}
      localStorage.setItem('dh_favs',JSON.stringify(f));
    }});
  }});
}}
window.dhInitFav=dhInitFav;
dhInitFav();
if(!document.getElementById('homeDataConfig')){{
function applyFilter(pred){{
  let total=0;
  document.querySelectorAll('.item').forEach(el=>{{
    const show=pred(el);el.style.display=show?'':'none';if(show)total++;
  }});
  document.querySelectorAll('.day').forEach(d=>{{
    const all=d.querySelectorAll('.item');
    const vis=Array.from(all).filter(el=>el.style.display!=='none');
    d.style.display=vis.length?'':'none';
    const info=d.querySelector('.info');
    if(info){{
      if(!info.dataset.base)info.dataset.base=info.textContent;
      info.textContent=(vis.length<all.length)?info.dataset.base+' · 筛选后 '+vis.length:info.dataset.base;
    }}
  }});
  const rc=document.getElementById('rCount');
  if(rc)rc.textContent=total;
}}
// 主题筛选条（支持再点取消）
document.querySelectorAll('#chiprow .fchip').forEach(c=>c.addEventListener('click',()=>{{
  const wasOn=c.classList.contains('on');
  document.querySelectorAll('#chiprow .fchip').forEach(x=>x.classList.remove('on'));
  if(!wasOn&&c.dataset.topic!=='all'){{
    c.classList.add('on');
    const t=c.dataset.topic;
    applyFilter(el=>(el.dataset.topics||'').split('|').includes(t));
  }}else{{
    document.querySelector('[data-topic="all"]').classList.add('on');
    applyFilter(()=>true);
  }}
}}));
const qEl=document.getElementById('q'),qClear=document.getElementById('qClear');
function doSearch(){{
  const q=qEl.value.toLowerCase();
  if(qClear)qClear.style.display=q?'':'none';
  applyFilter(el=>el.textContent.toLowerCase().includes(q));
}}
qEl.addEventListener('input',doSearch);
if(qClear)qClear.addEventListener('click',()=>{{qEl.value='';doSearch();}});
// 整卡可点：进入站内详情页
document.querySelectorAll('.item,.hot').forEach(el=>{{
  el.addEventListener('click',e=>{{
    if(e.target.closest('a')||e.target.closest('button')) return;
    const url=el.dataset.link;
    if(url) location.href=url;
  }});
}});
}}
// 移动端下拉刷新
(function(){{
  const ind=document.getElementById('ptr');
  let startY=null,dy=0;
  const THRESH=72;
  window.addEventListener('touchstart',e=>{{
    startY=(window.scrollY<=0)?e.touches[0].clientY:null;
    dy=0;
  }},{{passive:true}});
  window.addEventListener('touchmove',e=>{{
    if(startY===null) return;
    dy=e.touches[0].clientY-startY;
    if(dy<=0||window.scrollY>0){{ind.style.height='0px';return;}}
    if(dy>8&&e.cancelable) e.preventDefault();
    const h=Math.min(dy*0.5,THRESH+20);
    ind.style.height=h+'px';
    ind.firstElementChild.textContent=dy>THRESH?'松开刷新':'下拉刷新';
  }},{{passive:false}});
  window.addEventListener('touchend',()=>{{
    if(dy>THRESH){{
      ind.firstElementChild.textContent='刷新中…';
      location.reload();
    }}else{{
      ind.style.height='0px';
    }}
    startY=null;dy=0;
  }},{{passive:true}});
}})();
</script>
{home_update_info_script()}
</body></html>'''

    page = finalize_html_security(page)
    (SITE / "sources.html").write_text(render_sources_page(timeline_events, payload, css), encoding="utf-8")
    (SITE / "classics.html").write_text(render_classics_page(qualified_events, css), encoding="utf-8")
    (SITE / "hot.html").write_text(render_hot_page(hot_window_events, css), encoding="utf-8")
    favorite_data_url = "data/latest-lite.json" if lite_enabled else "data/latest.json"
    (SITE / "favorites.html").write_text(render_favorites_page(css, favorite_data_url), encoding="utf-8")
    (SITE / "weekly.html").write_text(
        render_weekly_brief_page(
            weekly_brief, all_events, css, archives=weekly_archives,
        ),
        encoding="utf-8",
    )
    (SITE / "daily.html").write_text(render_legacy_daily_redirect(), encoding="utf-8")
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    valid_weekly_pages = set()
    for archive_brief in weekly_archives:
        week_id = str(archive_brief.get("week_id") or "")
        if not re.fullmatch(r"\d{4}-W\d{2}", week_id):
            continue
        filename = f"{week_id}.html"
        valid_weekly_pages.add(filename)
        (WEEKLY_DIR / filename).write_text(
            render_weekly_brief_page(
                archive_brief, all_events, css, prefix="../",
                archives=weekly_archives, archive_prefix="",
            ),
            encoding="utf-8",
        )
    for weekly_path in WEEKLY_DIR.glob("*.html"):
        if weekly_path.name not in valid_weekly_pages:
            weekly_path.unlink()
    (SITE / "privacy.html").write_text(render_privacy_page(css), encoding="utf-8")

    out = SITE / "index.html"
    out.write_text(page, encoding="utf-8")
    broken = check_site_links(SITE)
    if broken:
        print(f"[links] 构建失败：发现 {len(broken)} 个失效本地引用")
        print(format_broken_links(broken, SITE))
        raise RuntimeError("generated site contains broken local links")
    print("[links] 本地 href/src 100% 有效")
    print(f"[render] 首页 ({len(page.encode('utf-8')):,} B) + 详情页 {len(valid_ids)} 个")

if __name__ == "__main__":
    main()
