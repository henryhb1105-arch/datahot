#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1.1：读取 latest.json（事件结构），生成首页 + 每个事件的站内详情页（带 OG meta）"""
import base64, hashlib, io, json, html, os, re, shutil
import qrcode
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from urllib.parse import quote, urlparse
from agent_page import AGENT_PAGE_CSS, publish_skill_bundle, render_agent_body
from agent_feed import build_agent_feed, validate_agent_feed
from content_blocks import (
    blocks_plain_text, render_blocks_html, sanitize_blocks, sanitize_url,
    trim_article_blocks,
)
from check_links import check_site_links, format_broken_links
from feed import build_atom_feed, validate_atom_feed
from lite_data import (
    DEFAULT_PAGE_SIZE, FIRST_PAGE_SOURCE_CAPS, HOME_WINDOW_DAYS,
    build_lite_payload, event_timestamp, find_forbidden_fields,
    is_list_eligible, rank_hot_events, rank_timeline_events,
    select_home_events, select_timeline_events,
)
from weekly_brief import valid_brief as valid_weekly_brief
from taxonomy import CATEGORY_LABELS, normalize_category_labels
from site_config import SITE_BASE_URL, SITE_HOST
from social_cards import social_image_for_event
from seo import absolute_public_url, public_sitemap_paths, write_search_discovery
from indexnow import write_key_file as write_indexnow_key_file

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DETAIL_DIR = SITE / "e"
QR_DIR = SITE / "qr"
TOPIC_DIR = SITE / "topics"
WEEKLY_DIR = SITE / "weekly"
ANALYTICS_ASSET = ROOT / "pipeline" / "assets" / "analytics.js"
CONTENT_FEEDBACK_ASSET = ROOT / "pipeline" / "assets" / "content-feedback.js"
HOME_ASSET = ROOT / "pipeline" / "assets" / "home.js"
FOR_ME_ASSET = ROOT / "pipeline" / "assets" / "for-me.js"
FAVORITES_ASSET = ROOT / "pipeline" / "assets" / "favorites.js"
DETAIL_ASSET = ROOT / "pipeline" / "assets" / "detail.js"
TTS_ASSET = ROOT / "pipeline" / "assets" / "tts-player.js"
TTS_MANIFEST = SITE / "data" / "tts-manifest.json"
TZ = timezone(timedelta(hours=8))
SITE_BASE = SITE_BASE_URL
BLUESKY_DID = "did:plc:hw6oq3mktrtycjkskm4nokbl"
BLUESKY_HANDLE = "datahot.xiahongbin.com"
BLUESKY_PROFILE_URL = f"https://bsky.app/profile/{BLUESKY_HANDLE}"
BLUESKY_FOOTER_LINK = (
    f'<a href="{BLUESKY_PROFILE_URL}" target="_blank" rel="noopener noreferrer" '
    'data-analytics="outbound" data-source="Bluesky" '
    'style="color:var(--sub);text-decoration:underline">Bluesky</a>'
)
CAT_BADGE = {
    "agent": "b-agent", "platform": "b-platform", "bi": "b-bi",
    "product": "b-product", "insight": "b-insight",
}
CAT_LABEL = CATEGORY_LABELS
WEEK_CN = "一二三四五六日"
HEAT_FORMULA = "内容质量45% + 趋势55%（48小时半衰新鲜度、社区信号与多信源印证）"
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
 "radar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M13.5 10.5 18 6"/></svg>',
 "file": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h8l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M14 2v5h5M9 13h6M9 17h6"/></svg>',
 "list": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6h12M9 12h12M9 18h12"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/></svg>',
 "more": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/></svg>',
 "rss": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1.5"/></svg>',
 "star": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4 6.1 20.5l1.2-6.5L2.5 9.4l6.6-.9 2.9-6z"/></svg>',
 "bookmark": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-4.5L5 21V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v17z"/></svg>',
 "headphones": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14v-2a8 8 0 0 1 16 0v2"/><path d="M18 19h1a2 2 0 0 0 2-2v-2a2 2 0 0 0-2-2h-1v6zM6 19H5a2 2 0 0 1-2-2v-2a2 2 0 0 1 2-2h1v6z"/></svg>',
 "x": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
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

# 首页筛选允许标签重叠；主题地图则提供稳定的阅读层级。
TOPIC_TECH_MAINLINES = (
    "Data Agent", "语义层", "平台AI化", "BI变局", "湖仓", "实时分析", "数据人",
)
TOPIC_BUSINESS_SCENES = (
    "组织人才", "财务经营", "销售增长", "客户运营", "供应链", "风险管理",
)
TOPIC_CHILDREN = {"Data Agent": ("ChatBI",)}
TOPIC_PARENTS = {
    child: parent
    for parent, children in TOPIC_CHILDREN.items()
    for child in children
}
TOPIC_RECENT_DAYS = 7
TOPIC_READING_LIMIT = 3
TOPIC_UPDATE_PAGE_SIZE = 10

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
            f'<button class="fchip" type="button" aria-pressed="false" data-topic="{esc(name)}">'
            f'{esc(HOME_FILTER_TOPIC_LABELS.get(name, name))}</button>'
        )
        if name == "Data Agent":
            parts.append('<button class="fchip" type="button" aria-pressed="false" data-category="insight">AI分析</button>')
    if "Data Agent" not in active_topics:
        parts.insert(0, '<button class="fchip" type="button" aria-pressed="false" data-category="insight">AI分析</button>')
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
        return "RSS"
    if stype == "community":
        return "社区"
    return "RSS"

def source_public_url(source):
    """Return a reader-safe source URL without exposing sitemap endpoints."""
    kind_fallbacks = {
        "hn_algolia": "https://news.ycombinator.com/",
        "bluesky": "https://bsky.app/",
    }
    candidates = [source.get("homepage"), source.get("url"), *(source.get("urls") or [])]
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
@media(max-width:1199px){.d-only{display:none}}
.chip{display:inline-block;font-size:11px;background:#eef2ff;color:var(--blue);border-radius:99px;padding:1px 10px;text-decoration:none}
.tlsearch{margin-left:auto;border:1px solid var(--line);border-radius:99px;padding:5px 12px;font-size:12.5px;width:120px;outline:none;background:var(--card)}
.tlsearch:focus{width:160px;border-color:var(--accent);transition:width .2s}
.chiprow{display:flex;flex-wrap:nowrap;gap:8px;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;scrollbar-width:none;padding:4px 18px 12px 0;margin-bottom:4px;position:relative;scroll-padding-inline:8px}
.chiprow::after{display:block;content:"";position:sticky;right:0;flex:0 0 18px;width:18px;margin-left:-18px;background:linear-gradient(to right,transparent,var(--bg));pointer-events:none}
.chiprow::-webkit-scrollbar{display:none}
.chiprow .fchip{appearance:none;flex-shrink:0;min-height:36px;font:inherit;font-size:12.5px;line-height:1.4;border:1px solid var(--line);border-radius:99px;padding:4px 14px;color:var(--sub);cursor:pointer;background:var(--card)}
.chiprow .fchip.on{background:var(--ink);color:#fff;border-color:var(--ink);font-weight:600}
@media(max-width:600px){
  .home-page>.wrap{padding-left:var(--mobile-page-left);padding-right:var(--mobile-page-right)}
  .chiprow{gap:6px;margin-left:calc(-1 * var(--mobile-page-left));margin-right:calc(-1 * var(--mobile-page-right));padding:4px calc(var(--mobile-page-right) + 18px) 12px var(--mobile-page-left);scroll-padding-left:var(--mobile-page-left);scroll-padding-right:var(--mobile-page-right)}
  .chiprow .fchip{font-size:12px;padding:4px 12px;min-height:44px;display:inline-flex;align-items:center}
}
@media (prefers-color-scheme: dark){
  .chip{background:rgba(110,168,255,.16);color:#6ea8ff}
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
.source-principle{font-size:12px;line-height:1.75;color:var(--sub);margin:0}
@media(max-width:600px){
  .source-page{padding:22px 18px 52px}
  .source-intro{margin-bottom:25px}
  .source-intro h1{font-size:24px}
  .source-row{gap:8px}
  .source-name{font-size:13px;min-height:44px}
  .source-focus{max-width:45%;font-size:11px}
  .source-disabled .source-row{display:block}
  .source-disabled-reason{max-width:none;margin:4px 0 0;text-align:left}
  .source-contribute{align-items:flex-start;flex-direction:column;gap:12px}
}
.crow{display:flex;align-items:baseline;gap:8px;padding:9px 0;border-bottom:1px solid var(--soft);text-decoration:none;color:var(--ink)}
.crow:last-child{border-bottom:none}
.cpin{width:18px;flex-shrink:0;font-size:12px}
.ctitle{font-size:13.5px;font-weight:600;line-height:1.55;flex:1}
.cmeta{font-size:11px;color:var(--sub);white-space:nowrap}
.favbtn{appearance:none;min-width:36px;min-height:36px;border:none;background:none;color:var(--sub);cursor:pointer;padding:6px;display:inline-flex;align-items:center;justify-content:center;border-radius:50%}
.favbtn.on{color:var(--accent)}
.favbtn.on svg{fill:currentColor}
.favbtn svg{pointer-events:none}
.favbtn .sbtn-label{pointer-events:none}
.fav-toast{position:fixed;left:50%;bottom:28px;z-index:100;display:flex;align-items:center;gap:12px;max-width:calc(100vw - 28px);min-height:44px;padding:8px 10px 8px 16px;border-radius:99px;background:rgba(26,29,35,.94);box-shadow:0 10px 30px rgba(0,0,0,.18);color:#fff;font-size:13px;line-height:1.4;opacity:0;pointer-events:none;transform:translate(-50%,12px);transition:opacity .2s ease,transform .2s ease}
.fav-toast.show{opacity:1;pointer-events:auto;transform:translate(-50%,0)}
.fav-toast-action{appearance:none;min-height:36px;border:0;border-radius:99px;padding:6px 12px;background:rgba(255,255,255,.14);color:#fff;font:inherit;font-size:12px;font-weight:750;cursor:pointer;white-space:nowrap}
.fav-entry{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;color:var(--sub);white-space:nowrap;text-decoration:none}
.privacy-btn{min-height:44px;border:none;background:var(--accent);color:#fff;border-radius:99px;padding:9px 16px;font-size:12.5px;font-weight:650;cursor:pointer;margin:4px 6px 4px 0}
.privacy-btn.ghost{background:var(--card);color:var(--ink);border:1px solid var(--line)}
.load-more{display:block;margin:18px auto 4px;border:1px solid var(--line);background:var(--card);color:var(--txt2);border-radius:99px;padding:9px 22px;font-size:12.5px;font-weight:650;cursor:pointer}
.load-more[hidden]{display:none}
.load-more[disabled]{opacity:.65;cursor:default}
.filter-error b{display:block;margin-bottom:5px;color:var(--ink);font-size:14px}
.filter-error p{margin:0;color:var(--sub);font-size:12.5px;line-height:1.7}
.filter-error-actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.filter-error-actions button{min-height:44px;border:1px solid var(--line);border-radius:99px;padding:8px 15px;background:var(--card);color:var(--ink);font:inherit;font-size:12.5px;font-weight:650;cursor:pointer}
.filter-error-actions button:first-child{border-color:var(--accent);background:var(--accent);color:#fff}
.weekly-strip{display:flex;align-items:stretch;min-height:52px;margin-bottom:16px;border:1px solid var(--line);border-radius:var(--radius);background:var(--card);overflow:hidden}
.weekly-strip[hidden]{display:none}
.weekly-strip-link{display:flex;align-items:center;gap:10px;min-width:0;min-height:52px;flex:1;padding:0 4px 0 14px;color:var(--ink);text-decoration:none}
.weekly-strip-label{flex:0 0 auto;border-radius:99px;padding:3px 8px;background:var(--accent-soft);color:var(--accent);font-size:11px;font-weight:750;white-space:nowrap}
.weekly-strip-title{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;font-weight:700}
.weekly-strip-view{flex:0 0 auto;color:var(--accent);font-size:12px;font-weight:700;white-space:nowrap}
.weekly-dismiss{appearance:none;display:inline-flex;align-items:center;justify-content:center;flex:0 0 44px;width:44px;min-height:44px;margin:4px;border:0;border-radius:50%;background:transparent;color:var(--sub);cursor:pointer}
.weekly-dismiss svg{pointer-events:none}
.today-hot{margin-bottom:12px;border:1px solid var(--line);border-radius:var(--radius);background:var(--card);overflow:hidden}
.today-hot-head{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:34px;padding:0 12px;border-bottom:1px solid var(--soft)}
.today-hot-head h2{margin:0;font-size:12px;line-height:1.3;font-weight:800;letter-spacing:.04em;color:var(--ink)}
.today-hot-more{flex:0 0 auto;color:var(--accent);font-size:11.5px;font-weight:700;text-decoration:none;white-space:nowrap}
.today-hot-list{display:block}
.today-hot-row{display:grid;grid-template-columns:22px minmax(0,1fr) auto;align-items:center;gap:8px;min-height:35px;padding:0 12px;color:var(--ink);text-decoration:none}
.today-hot-row+.today-hot-row{border-top:1px solid var(--soft)}
.today-hot-rank{display:inline-flex;align-items:center;justify-content:center;width:19px;height:19px;border-radius:5px;background:var(--soft);color:var(--sub);font-size:10px;font-weight:800;font-variant-numeric:tabular-nums}
.today-hot-row.is-lead .today-hot-rank{background:var(--accent);color:#fff}
.today-hot-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px;font-weight:650}
.today-hot-row.is-lead .today-hot-title{font-weight:750}
.today-hot-heat{display:inline-flex;align-items:center;gap:3px;flex:0 0 auto;color:var(--accent);font-size:11px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.top-rank{flex:0 0 auto;border-radius:5px;padding:2px 6px;background:var(--accent);color:#fff;font-size:10px;font-weight:800;line-height:1.3;white-space:nowrap}
.vendor-card-head{justify-content:space-between}
.vendor-card-title{display:inline-flex;align-items:center;gap:6px}
.vendor-card-link{margin-left:auto;color:var(--accent);font-size:11px;font-weight:650;text-decoration:none;white-space:nowrap}
.vendor-row{color:var(--ink);text-decoration:none}
@media(max-width:360px){
  .weekly-strip-link{gap:7px;padding-left:10px}
  .weekly-strip-label{padding:3px 7px}
  .weekly-strip-view-arrow{display:none}
}
@media(max-width:600px){
  .weekly-strip{min-height:48px;margin-bottom:10px}
  .weekly-strip-link{min-height:48px}
  .today-hot{margin-bottom:8px}
  .today-hot-head{min-height:32px;padding:0 10px}
  .today-hot-head h2{font-size:11.5px}
  .today-hot-more{font-size:11px}
  .today-hot-row{grid-template-columns:20px minmax(0,1fr) auto;gap:7px;min-height:34px;padding:0 10px}
  .today-hot-rank{width:18px;height:18px;font-size:9.5px}
  .today-hot-title{font-size:12px}
  .today-hot-heat{font-size:10.5px}
  .top-rank{padding:2px 5px;font-size:9.5px}
}
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
.weekly-evidence-row span:first-child{font-size:13px;line-height:1.55;flex:1}
.weekly-evidence-row span:last-child{font-size:10.5px;color:var(--sub);white-space:nowrap}
.weekly-archive{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 22px}
.weekly-archive a{font-size:12px;color:var(--sub);border:1px solid var(--line);border-radius:99px;padding:5px 10px;text-decoration:none}
.weekly-archive a.on{border-color:var(--accent);color:var(--accent)}
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
.hrow .hm{font-size:11px;color:var(--sub);white-space:nowrap}
.rank-page{padding:28px 20px 60px;max-width:900px}
.rank-head{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}
.rank-head h1{display:flex;align-items:center;gap:7px;font-size:20px;line-height:1.4;margin:0}
.rank-head p{font-size:12px;color:var(--sub);margin:0}
.rank-list{padding:6px 18px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius)}
.rank-row{display:grid;grid-template-columns:26px minmax(0,1fr) minmax(150px,auto);align-items:center;gap:12px;min-height:48px;padding:12px 0;border-bottom:1px solid var(--soft);color:var(--ink);text-decoration:none}
.rank-row:last-child{border-bottom:none}
.rank-no{font-size:14px;font-weight:750;color:var(--sub);font-variant-numeric:tabular-nums;text-align:center}
.rank-no.is-top{color:var(--accent);font-size:16px;font-weight:850}
.rank-title{min-width:0;font-size:14px;font-weight:650;line-height:1.5}
.rank-meta{display:flex;align-items:center;justify-content:flex-end;gap:9px;min-width:0;max-width:280px;color:var(--sub);font-size:11px}
.rank-source{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rank-heat{display:inline-flex;align-items:center;gap:3px;flex:0 0 auto;color:var(--accent);font-weight:700;white-space:nowrap}
.rank-note{margin-top:8px;color:var(--sub);font-size:12px}
.rank-note summary{display:flex;align-items:center;width:max-content;max-width:100%;min-height:44px;cursor:pointer;list-style:none}
.rank-note summary::-webkit-details-marker{display:none}
.rank-note summary::after{content:" ↓";margin-left:4px}
.rank-note[open] summary::after{content:" ↑"}
.rank-note p{margin:0 0 8px;line-height:1.7}
@media(max-width:600px){
  .rank-page{padding:18px 14px calc(32px + env(safe-area-inset-bottom))}
  .rank-head{display:block;margin-bottom:14px}
  .rank-head h1{font-size:22px}
  .rank-head p{margin-top:4px;font-size:12px}
  .rank-list{display:grid;gap:10px;padding:0;background:transparent;border:0;border-radius:0}
  .rank-row{grid-template-columns:30px minmax(0,1fr);grid-template-rows:auto auto;align-items:start;gap:5px 10px;min-height:76px;padding:13px 14px;background:var(--card);border:1px solid var(--line);border-radius:12px}
  .rank-row:last-child{border-bottom:1px solid var(--line)}
  .rank-no{grid-row:1/3;padding-top:1px;font-size:14px;text-align:left}
  .rank-no.is-top{font-size:17px}
  .rank-title{display:-webkit-box;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:2;font-size:15px;line-height:1.5}
  .rank-meta{grid-column:2;justify-content:flex-start;max-width:none;width:100%;gap:8px}
  .rank-source{flex:1}
  .rank-note{margin-top:4px}
}
.srcbadge{font-size:10px;border:1px solid var(--line);border-radius:5px;padding:0 5px;color:var(--sub);flex-shrink:0;line-height:1.6}
.sidebar{display:none}
@media(min-width:1200px){
  body.has-sb{padding-left:224px}
  body.has-sb>header{display:none}
  .sidebar{display:flex;position:fixed;left:0;top:0;bottom:0;width:224px;flex-direction:column;background:var(--card);border-right:1px solid var(--line);padding:22px 16px;z-index:40}
  .sidebar .slogo{font-size:20px;font-weight:800;margin-bottom:26px}
  .sidebar .slogo em{font-style:normal;color:var(--accent)}
  .sidebar .sidebar-nav{display:grid}
  .sidebar a.mi{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:10px;font-size:14px;color:var(--sub);text-decoration:none;margin-bottom:2px}
  .sidebar a.mi.on{background:var(--ink);color:var(--bg);font-weight:600}
  .sidebar .sidebar-tools{margin-top:auto;padding-top:14px;border-top:1px solid var(--line)}
  .sidebar .sidebar-tools a.mi{margin-bottom:0;font-size:12.5px}
  .sidebar .sfoot{margin-top:10px;font-size:11.5px;color:var(--sub);line-height:1.8}
}
.hot .hsum{font-size:12.5px;color:var(--txt2);line-height:1.65;margin:6px 0 10px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.hot .htime{margin-left:auto;font-size:11px;color:var(--sub)}
.hot .sources{align-items:center}
.hot .sources .favbtn{flex:0 0 auto;margin:-8px -8px -8px 0}
.tabbar{display:none}
.more-mask,.more-sheet{display:none}
@media(max-width:1199px){
  body{padding-bottom:64px}
  footer{padding-bottom:96px}
  body.mobile-section{padding-top:env(safe-area-inset-top)}
  .section-brand-header,.detail-brand-header{display:none}
  .tabbar{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));position:fixed;bottom:0;left:0;right:0;background:var(--tabbar-bg);backdrop-filter:blur(10px);border-top:1px solid var(--line);z-index:70;padding:0 0 env(safe-area-inset-bottom)}
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
  .more-close{appearance:none;border:0;background:var(--soft);color:var(--sub);width:44px;height:44px;border-radius:50%;font-size:18px;cursor:pointer}
  .more-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .more-link{display:flex;align-items:center;gap:11px;min-height:58px;padding:11px 12px;border:1px solid var(--line);border-radius:12px;background:var(--bg);text-decoration:none;color:var(--ink)}
  .more-link .more-icon{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;background:var(--accent-soft);color:var(--accent);flex:0 0 auto}
  .more-link span:last-child{min-width:0;font-size:13px;font-weight:650}
  .more-link.on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
  body.more-open{overflow:hidden}
}
.fchip:focus-visible,.timeline-clear:focus-visible,.favbtn:focus-visible,.fav-toast-action:focus-visible,.favorites-search:focus-visible,.favorites-filter:focus-visible,.favorites-empty-cta:focus-visible,.favorite-card-main:focus-visible,.load-more:focus-visible,.weekly-strip-link:focus-visible,.weekly-dismiss:focus-visible,.today-hot-row:focus-visible,.today-hot-more:focus-visible,.rank-row:focus-visible,.rank-note summary:focus-visible,.more-close:focus-visible,.more-link:focus-visible,.tabbar a:focus-visible,.tabbar button:focus-visible,.sidebar a:focus-visible,.source-name:focus-visible,.source-cta:focus-visible,.tcard-main:focus-visible,.tchild-link:focus-visible,.scenario-row:focus-visible,.topic-back:focus-visible,.topic-follow:focus-visible,.topic-recent-card:focus-visible,.topic-update-row:focus-visible,.topic-load-more:focus-visible,.topic-vendors summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:600px){.favbtn{min-width:44px;min-height:44px}}
@media(prefers-reduced-motion:reduce){
  *,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
}
.topic-map-page,.topic-page{max-width:900px;padding-top:28px;padding-bottom:60px}
.topic-map-intro{font-size:13px;color:var(--sub);line-height:1.7;margin:-4px 0 26px}
.topic-family{margin-top:26px}
.topic-family:first-of-type{margin-top:0}
.topic-family-head{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}
.topic-family-head h2{font-size:17px;font-weight:800}
.topic-family-head p{font-size:12px;color:var(--sub)}
.tgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;min-width:0}
@media(max-width:960px){.tgrid{grid-template-columns:minmax(0,1fr)}}
.tcard{min-width:0;width:100%;overflow:hidden;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);display:flex;flex-direction:column;transition:.15s}
.tcard-main{display:block;min-width:0;padding:18px 20px;text-decoration:none;color:var(--ink);flex:1}
.tcard h3{font-size:17px;font-weight:800;margin-bottom:6px}
.tcard .td{font-size:12.5px;color:var(--sub);line-height:1.6;margin-bottom:12px}
.topic-counts{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;font-weight:650}
.topic-counts .recent{color:var(--accent)}
.topic-counts .total{color:var(--sub);font-weight:500}
.tchildren{display:flex;align-items:center;gap:7px;border-top:1px solid var(--soft);padding:10px 20px;font-size:11.5px;color:var(--sub)}
.tchild-link{display:inline-flex;align-items:center;min-height:30px;border-radius:99px;background:var(--accent-soft);color:var(--accent);font-weight:650;padding:3px 10px;text-decoration:none}
.scenario-list{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
.scenario-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 16px;align-items:center;min-height:58px;padding:10px 16px;border-bottom:1px solid var(--soft);color:var(--ink);text-decoration:none}
.scenario-row:last-child{border-bottom:none}
.scenario-copy{min-width:0}
.scenario-name{display:block;font-size:14px;font-weight:750}
.scenario-desc{display:block;margin-top:2px;font-size:11.5px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.scenario-count{font-size:11.5px;color:var(--sub);white-space:nowrap}
.scenario-count.is-active{color:var(--accent);font-weight:650}
.topic-hero{margin-bottom:24px}
.topic-back{display:inline-flex;align-items:center;min-height:36px;color:var(--sub);font-size:13px;text-decoration:none}
.topic-hero h1{font-size:28px;font-weight:800;margin:10px 0 6px}
.topic-hero-desc{font-size:14px;color:var(--sub);line-height:1.7;margin:0 0 8px}
.topic-follow{display:inline-flex;align-items:center;justify-content:center;min-height:40px;margin:7px 0 4px;padding:0 12px;border:1px solid var(--line);border-radius:9px;background:var(--card);color:var(--ink);font-size:12.5px;font-weight:700;text-decoration:none}
.topic-parent{font-size:12px;color:var(--sub);margin-top:9px}
.topic-parent a{color:var(--accent);font-weight:650;text-decoration:none}
.topic-section{margin-top:24px}
.topic-section-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:10px}
.topic-section-head h2{font-size:16px;font-weight:800}
.topic-section-head p{font-size:11.5px;color:var(--sub);text-align:right}
.topic-recent-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.topic-recent-wrap{position:relative;min-width:0}
.topic-recent-card{min-width:0;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:14px;text-decoration:none;color:var(--ink)}
.topic-recent-wrap .topic-recent-card{display:block;height:100%;padding-right:54px}
.topic-recent-fav{position:absolute;top:7px;right:7px;z-index:2}
.topic-recent-card h3{font-size:14px;line-height:1.55;margin:6px 0}
.topic-recent-card p{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;font-size:12px;line-height:1.65;color:var(--txt2)}
.topic-recent-meta{font-size:10.5px;color:var(--sub)}
.topic-empty{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:15px 16px;color:var(--sub);font-size:12.5px}
.topic-reading{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:6px 16px 10px}
.topic-updates{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
.topic-update-row{display:grid;grid-template-columns:88px minmax(0,1fr) 150px;gap:12px;align-items:center;min-height:52px;padding:9px 14px;border-bottom:1px solid var(--soft);color:var(--ink);text-decoration:none}
.topic-update-row:last-child{border-bottom:none}
.topic-update-row.is-extra{display:none}
.topic-update-date{font-size:11px;color:var(--sub);font-variant-numeric:tabular-nums}
.topic-update-title{min-width:0;font-size:13px;font-weight:650;line-height:1.5}
.topic-update-source{min-width:0;font-size:11px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right}
.topic-load-more{appearance:none;width:100%;min-height:48px;margin-top:10px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);font-size:12.5px;font-weight:650;cursor:pointer}
.topic-vendors{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:0 14px}
.topic-vendors summary{display:flex;align-items:center;justify-content:space-between;min-height:48px;font-size:12.5px;font-weight:650;cursor:pointer;list-style:none}
.topic-vendors summary::-webkit-details-marker{display:none}
.topic-vendors summary span{color:var(--sub);font-size:11px;font-weight:500}
.topic-vendors[open] summary span{color:var(--accent)}
.topic-vendors .vendors{padding:0 0 14px;margin-top:0}
@media(max-width:720px){.topic-recent-grid{grid-template-columns:minmax(0,1fr)}}
@media(max-width:600px){
  .topic-map-page,.topic-page{padding-top:18px;padding-right:var(--mobile-page-right);padding-left:var(--mobile-page-left)}
  .topic-map-intro{margin-bottom:22px}
  .topic-family-head{display:block}
  .topic-family-head p{margin-top:3px}
  .tcard-main{padding:15px 16px}
  .tchildren{padding:8px 16px}
  .scenario-row{padding:10px 14px}
  .scenario-desc{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
  .topic-hero h1{font-size:26px}
  .topic-follow{min-height:44px}
  .topic-section-head{display:block}
  .topic-section-head p{text-align:left;margin-top:3px}
  .topic-update-row{grid-template-columns:70px minmax(0,1fr);gap:3px 10px;padding:10px 12px}
  .topic-update-source{grid-column:2;text-align:left}
}
.favorites-page{max-width:900px;min-height:calc(100vh - 145px);padding:28px 20px 60px}
.favorites-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:18px}
.favorites-title{display:flex;align-items:center;gap:8px;margin:0;font-size:22px;line-height:1.35}
.favorites-count{color:var(--sub);font-size:12px;font-weight:500;white-space:nowrap}
.favorites-trust{margin:6px 0 0;color:var(--sub);font-size:12px;line-height:1.6}
.favorites-trust a{color:inherit;text-decoration:underline;text-underline-offset:2px}
.favorites-tools{margin-bottom:16px}
.favorites-search{width:min(360px,100%);min-height:44px;border:1px solid var(--line);border-radius:99px;padding:9px 15px;background:var(--card);color:var(--ink);font:inherit;font-size:13px;outline:none}
.favorites-search:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.favorites-filters{display:flex;gap:7px;overflow-x:auto;margin-top:10px;padding-bottom:2px;scrollbar-width:none}
.favorites-filters::-webkit-scrollbar{display:none}
.favorites-filter{appearance:none;flex:0 0 auto;min-height:36px;border:1px solid var(--line);border-radius:99px;padding:6px 13px;background:var(--card);color:var(--sub);font:inherit;font-size:12px;cursor:pointer}
.favorites-filter.on{border-color:var(--ink);background:var(--ink);color:var(--bg);font-weight:700}
.favorites-group{margin:0 0 18px}
.favorites-group h2{margin:0 0 8px;color:var(--sub);font-size:12px;font-weight:700}
.favorites-list{display:grid;gap:10px}
.favorite-card{display:grid;grid-template-columns:minmax(0,1fr) 48px;align-items:start;background:var(--card);border:1px solid var(--line);border-radius:var(--radius)}
.favorite-card-main{min-width:0;padding:15px 4px 15px 17px;color:var(--ink);text-decoration:none}
.favorite-card-top{display:flex;align-items:center;gap:7px;margin-bottom:6px;color:var(--sub);font-size:10.5px;line-height:1.4}
.favorite-card-topic{max-width:55%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border-radius:99px;padding:2px 8px;background:var(--soft);color:var(--txt2)}
.favorite-card-saved{margin-left:auto;white-space:nowrap}
.favorite-card h3{margin:0;font-size:15px;line-height:1.5}
.favorite-card-summary{display:-webkit-box;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:2;margin:6px 0 0;color:var(--txt2);font-size:12.5px;line-height:1.65}
.favorite-card-meta{display:flex;align-items:center;gap:7px;margin-top:8px;color:var(--sub);font-size:11px;line-height:1.4}
.favorite-card-meta span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.favorite-card>.favbtn{align-self:center;margin:4px 4px 4px 0}
.favorites-empty{display:grid;place-items:center;min-height:330px;padding:34px 20px;border:1px solid var(--line);border-radius:var(--radius);background:var(--card);text-align:center}
.favorites-empty-inner{max-width:360px}
.favorites-empty-icon{display:grid;place-items:center;width:54px;height:54px;margin:0 auto 14px;border-radius:50%;background:var(--soft);color:var(--sub)}
.favorites-empty h2{margin:0 0 7px;font-size:17px}
.favorites-empty p{margin:0;color:var(--sub);font-size:12.5px;line-height:1.75}
.favorites-empty-cta{display:inline-flex;align-items:center;justify-content:center;min-height:44px;margin-top:17px;border-radius:99px;padding:8px 17px;background:var(--ink);color:var(--bg);font-size:12.5px;font-weight:700;text-decoration:none}
.favorites-loading{padding:22px 0;color:var(--sub);font-size:13px}
@media(max-width:600px){
  .favorites-page{min-height:calc(100dvh - 145px - env(safe-area-inset-bottom));padding:20px 14px calc(36px + env(safe-area-inset-bottom))}
  .favorites-head{display:block;margin-bottom:15px}
  .favorites-title{font-size:21px}
  .favorites-trust{font-size:11.5px}
  .favorites-search{width:100%}
  .favorite-card{grid-template-columns:minmax(0,1fr) 52px}
  .favorite-card-main{padding:14px 2px 14px 14px}
  .favorite-card h3{font-size:15px}
  .favorite-card>.favbtn{margin-right:4px}
  .favorites-empty{min-height:350px;padding:32px 18px}
  .fav-toast{bottom:calc(68px + env(safe-area-inset-bottom))}
}
@media(hover:hover) and (pointer:fine){
  .chip:hover{background:#dbe4ff}
  a.source-name:hover,.crow:hover .ctitle,.fav-entry:hover,.weekly-evidence-row:hover span:first-child,.hrow:hover .ht,.rank-row:hover .rank-title{color:var(--accent)}
  .source-cta:hover{opacity:.86}
  .load-more:hover,.weekly-archive a:hover{border-color:var(--accent);color:var(--accent)}
  .weekly-strip:hover{border-color:var(--accent)}
  .weekly-strip-link:hover .weekly-strip-title,.weekly-dismiss:hover{color:var(--accent)}
  .today-hot-row:hover .today-hot-title,.today-hot-more:hover{color:var(--accent)}
  .sidebar a.mi:hover{background:var(--hover);color:var(--ink)}
  .tcard:hover,.topic-recent-card:hover{border-color:#d1d5db;box-shadow:0 4px 16px rgba(0,0,0,.05)}
  .tcard-main:hover h3,.scenario-row:hover .scenario-name,.topic-update-row:hover .topic-update-title,.topic-follow:hover{color:var(--accent)}
}
@media(prefers-color-scheme:dark) and (hover:hover) and (pointer:fine){
  .chip:hover{background:rgba(110,168,255,.26)}
}
"""

FOR_ME_CSS = """
.for-me-page{max-width:1040px;padding:34px 20px 72px}
.fm-hero{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px;align-items:start;margin-bottom:18px}
.fm-eyebrow{margin:0 0 8px;color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}
.fm-hero h1{margin:0;font-size:38px;line-height:1.05;letter-spacing:-.04em}
.fm-subtitle{margin:10px 0 0;color:var(--txt2);font-size:15px;line-height:1.7}
.fm-customize{appearance:none;min-height:44px;padding:0 16px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);font:inherit;font-size:13px;font-weight:700;cursor:pointer}
.fm-visit{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:3px;padding:13px 16px;border:1px solid var(--line);border-radius:13px;background:var(--card);font-size:12.5px;color:var(--sub)}
.fm-visit strong{color:var(--ink);font-size:13px;white-space:nowrap}
.fm-setup{margin-bottom:24px;padding:20px;border:1px solid color-mix(in srgb,var(--accent) 35%,var(--line));border-radius:16px;background:color-mix(in srgb,var(--accent-soft) 72%,var(--card))}
.fm-setup-head{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin-bottom:14px}
.fm-setup-head h2{margin:0 0 4px;font-size:17px}
.fm-setup-head p{margin:0;color:var(--sub);font-size:12.5px;line-height:1.6}
.fm-progress{color:var(--accent);font-size:12px;font-weight:750;white-space:nowrap}
.fm-suggestions{display:flex;flex-wrap:wrap;gap:9px}
.fm-follow-chip{appearance:none;display:inline-flex;align-items:center;gap:7px;min-height:40px;padding:7px 11px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);font:inherit;font-size:13px;cursor:pointer}
.fm-follow-chip.on{border-color:var(--accent);background:var(--accent);color:#fff}
.fm-follow-kind{font-size:9px;line-height:1.4;padding:2px 5px;border-radius:4px;background:var(--soft);color:var(--sub);font-weight:800;letter-spacing:.05em}
.fm-follow-chip.on .fm-follow-kind{background:rgba(255,255,255,.2);color:#fff}
.fm-privacy{margin:12px 0 0;color:var(--sub);font-size:11.5px}
.fm-loading,.fm-error,.fm-empty{padding:28px 20px;border:1px solid var(--line);border-radius:14px;background:var(--card);color:var(--sub);font-size:13px;line-height:1.8;text-align:center}
.fm-error button{appearance:none;min-height:40px;margin-top:10px;padding:0 14px;border:1px solid var(--line);border-radius:9px;background:var(--bg);color:var(--ink);font:inherit;font-weight:700;cursor:pointer}
.fm-section{margin-top:28px}
.fm-section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:12px}
.fm-section-head h2{margin:0;font-size:19px;letter-spacing:-.01em}
.fm-section-head p{margin:0;color:var(--sub);font-size:12px;text-align:right}
.fm-must-list{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.fm-feed-list,.fm-discovery-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.fm-signal{display:flex;min-width:0;flex-direction:column;padding:17px;border:1px solid var(--line);border-radius:14px;background:var(--card)}
.fm-signal.is-read{opacity:.7}
.fm-signal-top{display:flex;align-items:center;gap:7px;min-width:0;margin-bottom:11px}
.fm-signal-badge,.fm-new{display:inline-flex;align-items:center;min-height:21px;padding:2px 7px;border-radius:99px;background:var(--accent-soft);color:var(--accent);font-size:10px;font-weight:800}
.fm-new{background:var(--accent);color:#fff}
.fm-source{min-width:0;margin-left:auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--sub);font-size:10.5px}
.fm-signal-title{color:var(--ink);font-size:16px;font-weight:760;line-height:1.5;text-decoration:none}
.fm-signal-summary{display:-webkit-box;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:3;margin:9px 0 0;color:var(--txt2);font-size:12.5px;line-height:1.7}
.fm-why{display:flex;align-items:flex-start;gap:7px;margin-top:13px;padding:9px 10px;border-radius:9px;background:var(--soft);color:var(--txt2);font-size:11.5px;line-height:1.55}
.fm-why-label{flex:0 0 auto;color:var(--accent);font-size:10px;font-weight:850}
.fm-impact{margin:10px 0 0;color:var(--txt2);font-size:11.5px;line-height:1.65}
.fm-impact b{color:var(--ink)}
.fm-actions{display:flex;align-items:center;gap:4px;margin-top:auto;padding-top:13px}
.fm-action{appearance:none;min-height:36px;padding:0 9px;border:0;border-radius:8px;background:transparent;color:var(--sub);font:inherit;font-size:11.5px;cursor:pointer}
.fm-action[aria-pressed=true]{background:var(--soft);color:var(--ink);font-weight:700}
.fm-dismiss{margin-left:auto}
.fm-watch-list{display:grid;gap:8px}
.fm-watch-row{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:62px;padding:10px 14px;border:1px solid var(--line);border-radius:12px;background:var(--card)}
.fm-watch-label{display:grid;grid-template-columns:auto auto;align-items:center;gap:3px 8px;min-width:0}
.fm-watch-label b{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13.5px}
.fm-watch-count{grid-column:2;color:var(--sub);font-size:11px}
.fm-watch-remove{appearance:none;min-height:40px;padding:0 9px;border:0;background:transparent;color:var(--sub);font:inherit;font-size:11.5px;cursor:pointer;white-space:nowrap}
.fm-weekly{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px;border:1px solid var(--line);border-radius:14px;background:var(--card);color:var(--ink);text-decoration:none}
.fm-weekly b{display:block;font-size:15px;margin-bottom:5px}
.fm-weekly span{color:var(--sub);font-size:12px}
.fm-weekly-arrow{color:var(--accent)!important;font-size:18px!important}
.fm-customize:focus-visible,.fm-follow-chip:focus-visible,.fm-action:focus-visible,.fm-watch-remove:focus-visible,.fm-error button:focus-visible,.fm-signal-title:focus-visible,.fm-weekly:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(hover:hover) and (pointer:fine){
  .fm-customize:hover,.fm-follow-chip:hover{border-color:var(--accent)}
  .fm-signal:hover{border-color:#d1d5db;box-shadow:0 4px 16px rgba(0,0,0,.05)}
  .fm-signal-title:hover,.fm-watch-remove:hover,.fm-action:hover{color:var(--accent)}
}
@media(max-width:820px){
  .fm-must-list,.fm-feed-list,.fm-discovery-list{grid-template-columns:1fr}
  .fm-signal-summary{-webkit-line-clamp:2}
}
@media(max-width:600px){
  .for-me-page{padding:22px 14px 48px}
  .fm-hero{grid-template-columns:minmax(0,1fr) auto;gap:12px}
  .fm-hero h1{font-size:31px}
  .fm-subtitle{font-size:13.5px}
  .fm-customize{padding:0 12px}
  .fm-visit{display:grid;gap:4px;padding:12px 13px}
  .fm-visit strong{white-space:normal}
  .fm-setup{padding:16px 14px}
  .fm-setup-head{display:block}
  .fm-progress{display:block;margin-top:5px;white-space:normal}
  .fm-follow-chip{min-height:44px}
  .fm-section{margin-top:24px}
  .fm-section-head{display:block}
  .fm-section-head p{margin-top:3px;text-align:left}
  .fm-signal{padding:15px}
  .fm-action,.fm-watch-remove{min-height:44px}
  .fm-weekly{padding:16px}
}
"""

def sidebar(active, gen=None, prefix=""):
    """桌面端左侧菜单栏（≥1200px 显示，窄屏由底部 Tab 承担导航）"""
    menu_active = "home" if active == "hot" else active
    items = [("热榜", "flame", "index.html", "home"),
             ("关注", "radar", "for-me.html", "for-me")]
    if weekly_brief_enabled():
        items.append(("周报", "calendar", "weekly.html", "weekly"))
    items += [("主题", "map", "topics.html", "topics"),
             ("收藏", "star", "favorites.html", "favorites"),
             ("信源", "rss", "sources.html", "sources")]
    menu = '<nav class="sidebar-nav" aria-label="主导航">' + "".join(
        f'<a class="mi{" on" if k == menu_active else ""}" href="{prefix}{u}"'
        f'{" data-smart-home-return" if k == "home" else ""}>{ic(i,16)}{n}</a>'
        for n, i, u, k in items) + "</nav>"
    tools = (
        '<nav class="sidebar-tools" aria-label="工具">'
        f'<a class="mi{" on" if active == "agent" else ""}" href="{prefix}agent.html">'
        f'{ic("sparkle",16)}接入 Agent</a></nav>'
    )
    foot = f'更新 {gen.strftime("%m-%d %H:%M")}<br>' if gen else ""
    logo_label = ' aria-label="刷新 DataHot 首页" title="刷新首页"' if active == "home" else ""
    return ('<aside class="sidebar">'
            f'<div class="slogo"><a href="{prefix}index.html" data-smart-home-return{logo_label} style="text-decoration:none;color:inherit">Data<em>Hot</em></a></div>'
            + menu +
            tools +
            f'<div class="sfoot">{foot}每 6 小时自动更新 · <a href="https://github.com/henryhb1105-arch/datahot" target="_blank" rel="noopener noreferrer" style="color:var(--sub)">GitHub</a> · {BLUESKY_FOOTER_LINK}<br>数据领域 AI 资讯分享</div></aside>')


def render_home_brand_update(gen):
    """首页品牌刷新入口与可交互的更新机制说明。"""
    return f'''<a class="logo home-logo" href="index.html" data-home-refresh aria-label="刷新 DataHot 首页" title="刷新首页">Data<em>Hot</em><span class="tag">每 6 小时更新</span></a>
  <details class="update-info" data-update-info>
    <summary class="upd-time" aria-describedby="updateMechanism">{ic("clock",12)} {gen.strftime("%m-%d %H:%M")} 更新</summary>
    <div class="update-popover" id="updateMechanism" role="tooltip"><b>页面如何更新</b>{esc(UPDATE_MECHANISM)}</div>
  </details>'''


def render_timeline_toolbar(total_count):
    """首页时间轴工具栏：标题、搜索与数量在窄屏保持单行。"""
    return f'''<div class="section-title timeline-toolbar">
  <h2>{ic("calendar",18)} 时间轴</h2>
  <div class="timeline-searchbox">
    <input id="q" class="tlsearch" placeholder="搜索" aria-label="搜索时间轴" title="搜索范围：全部在站时间轴的标题、摘要与标签">
    <button id="qClear" class="timeline-clear" type="button" style="display:none" aria-label="清除搜索" title="清除搜索">✕</button>
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
    production_host = os.getenv("ANALYTICS_PRODUCTION_HOST", SITE_HOST).strip().lower()
    production_host = production_host if re.fullmatch(r"[a-z0-9.-]+", production_host) else SITE_HOST
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


def favorites_head(prefix=""):
    return f'<script defer src="{prefix}favorites.js"></script>'

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
             ("关注", ic("radar",20), "for-me.html", "for-me"),
             ("主题", ic("map",20), "topics.html", "topics"),
             ("收藏", ic("star",20), "favorites.html", "favorites")]
    primary = "".join(
        f'<a href="{prefix}{u}" class="{"on" if k == active else ""}"'
        f'{" data-home-top" if k == "home" else ""}><span class="ico">{i}</span><span>{n}</span></a>'
        for n, i, u, k in items)
    more_items = []
    if weekly_brief_enabled():
        more_items.append(("每周简报", "calendar", "weekly.html", "weekly"))
    more_items += [
        ("完整榜单", "list", "hot.html", "hot"),
        ("信源", "rss", "sources.html", "sources"),
        ("接入 Agent", "sparkle", "agent.html", "agent"),
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
<div class="more-mask" data-more-mask aria-hidden="true"></div>
<section class="more-sheet" id="mobileMoreSheet" role="dialog" aria-modal="true" aria-labelledby="mobileMoreTitle" aria-hidden="true">
  <div class="more-handle" aria-hidden="true"></div>
  <div class="more-head"><h2 id="mobileMoreTitle">更多</h2><button class="more-close" type="button" data-more-close aria-label="关闭更多导航">×</button></div>
  <div class="more-grid">{more_links}</div>
</section>
<script>
(function(){{
  var homeLink=document.querySelector('[data-home-top]');
  if(homeLink) homeLink.addEventListener('click',function(event){{
    if(document.body&&document.body.classList.contains('home-page')) return;
    var button=event.button==null?0:event.button;
    if(event.defaultPrevented||button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey) return;
    try{{
      var current=new URL(window.location.href);
      var target=new URL(homeLink.href,current);
      var source=new URL(document.referrer,current);
      var targetRoot=target.pathname.replace(/index\.html$/,'');
      var sourceIsHome=source.origin===target.origin&&(source.pathname===target.pathname||source.pathname===targetRoot);
      if(!sourceIsHome||window.history.length<=1) return;
      window.sessionStorage.setItem('datahotForceHomeTop','1');
      event.preventDefault();window.history.back();
    }}catch(error){{}}
  }});
  var trigger=document.querySelector('[data-more-open]');
  var sheet=document.getElementById('mobileMoreSheet');
  var mask=document.querySelector('[data-more-mask]');
  var closeBtn=document.querySelector('[data-more-close]');
  if(!trigger||!sheet||!mask||!closeBtn) return;
  var background=Array.from(document.body.children).filter(function(node){{return node!==sheet&&node!==mask&&node.tagName!=='SCRIPT'}});
  function setMore(open){{
    if(!open) background.forEach(function(node){{node.removeAttribute('inert')}});
    trigger.setAttribute('aria-expanded',open?'true':'false');
    sheet.setAttribute('aria-hidden',open?'false':'true');
    sheet.classList.toggle('show',open);
    mask.classList.toggle('show',open);
    document.body.classList.toggle('more-open',open);
    if(open){{background.forEach(function(node){{node.setAttribute('inert','')}});closeBtn.focus()}}else trigger.focus();
  }}
  trigger.addEventListener('click',function(){{setMore(true)}});
  closeBtn.addEventListener('click',function(){{setMore(false)}});
  mask.addEventListener('click',function(){{setMore(false)}});
  document.addEventListener('keydown',function(event){{
    if(!sheet.classList.contains('show')) return;
    if(event.key==='Escape'){{setMore(false);return}}
    if(event.key!=='Tab') return;
    var focusable=Array.from(sheet.querySelectorAll('a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])'));
    if(!focusable.length) return;
    var first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey&&document.activeElement===first){{event.preventDefault();last.focus()}}
    else if(!event.shiftKey&&document.activeElement===last){{event.preventDefault();first.focus()}}
  }});
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
        "img-src 'self' data: blob:",
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


def favorite_snapshot(e):
    """Return the metadata-only record persisted by the local favourites client."""
    primary = (e.get("items") or [{}])[0]
    return {
        "event_id": safe_event_id(e.get("event_id")),
        "title": str(e.get("zh_title") or ""),
        "summary": str(e.get("zh_summary") or ""),
        "source": src_display(str(primary.get("source") or "")),
        "category": str(e.get("category") or ""),
        "topics": [str(topic) for topic in (e.get("topics") or []) if str(topic).strip()],
        "published": str(e.get("published") or e.get("first_seen") or ""),
        "original_url": _safe_source_url(primary.get("link")),
    }


def favorite_button(e, *, class_name="favbtn", icon_size=15, label=""):
    record = esc(json.dumps(favorite_snapshot(e), ensure_ascii=False, separators=(",", ":")))
    event_id = safe_event_id(e.get("event_id"))
    label_html = f'<span class="sbtn-label">{esc(label)}</span>' if label else ""
    return (
        f'<button class="{esc(class_name)}" type="button" data-fav="{event_id}" '
        f'data-fav-record="{record}" title="收藏" aria-label="收藏" aria-pressed="false">'
        f'{ic("bookmark", icon_size)}{label_html}</button>'
    )

def render_card(e, prefix="", top_rank=None):
    event_id = safe_event_id(e["event_id"])
    status_label = "精选" if e.get("star") else ""
    if not status_label and is_classic_review(e):
        status_label = "经典回顾"
    status_class = " is-featured" if status_label else ""
    status_text = f"{status_label} {e['heat']}" if status_label else str(e["heat"])
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
    rank_html = (
        f'<span class="top-rank" aria-label="热点第 {int(top_rank)} 名">TOP {int(top_rank)}</span>'
        if top_rank else ""
    )
    return f'''<div class="item" data-cat="{esc(e["category"])}" data-topics="{esc("|".join(e.get("topics", [])))}" data-link="{url}" data-analytics-list="1" data-event-id="{event_id}" data-category="{esc(e["category"])}" data-source="{esc(e["items"][0]["source"])}">
      <div class="top card-meta"><span class="card-source"><span class="srcbadge">{src_badge(e["items"][0]["source"])}</span><span class="card-source-name">{esc(src_display(e["items"][0]["source"]))}</span><span class="card-time">{card_time(e)}</span></span>
      {rank_html}
      <span class="heatnum{status_class}" title="热度分：{HEAT_FORMULA}">{ic("flame",13)} {esc(status_text)}</span>
      {favorite_button(e)}</div>
      <h3><a href="{url}">{esc(e["zh_title"])}</a></h3>
      <p class="sum">{esc(e["zh_summary"])}</p>{also}{reason}{vbox}
    </div>'''


def render_today_hot(events):
    """Render a compact TOP 3 index; full cards remain in the timeline."""
    ranked = list(events or [])[:3]
    if not ranked:
        return ""
    rows = []
    for rank, event in enumerate(ranked, 1):
        event_id = safe_event_id(event["event_id"])
        lead_class = " is-lead" if rank == 1 else ""
        rows.append(f'''<a class="today-hot-row{lead_class}" href="{detail_url(event)}" data-event-id="{event_id}" data-analytics="today_hot" aria-label="TOP {rank}：{esc(event["zh_title"])}，热度 {int(event.get("heat") or 0)}">
    <span class="today-hot-rank" aria-hidden="true">{rank}</span>
    <span class="today-hot-title">{esc(event["zh_title"])}</span>
    <span class="today-hot-heat">{ic("flame",11)} {int(event.get("heat") or 0)}</span>
  </a>''')
    return f'''<section class="today-hot" aria-labelledby="todayHotTitle">
  <div class="today-hot-head"><h2 id="todayHotTitle">今日热榜</h2><a class="today-hot-more" href="hot.html" aria-label="查看完整榜单">完整榜单 →</a></div>
  <div class="today-hot-list">{"".join(rows)}</div>
</section>'''

def title_bigrams(t):
    t = re.sub(r"[^\w一-鿿]+", "", (t or "").lower())
    return {t[i:i+2] for i in range(len(t) - 1)} if len(t) > 1 else {t} if t else set()

def sim(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _event_terms(event, key):
    return {
        str(value).strip().casefold()
        for value in (event.get(key) or [])
        if str(value).strip()
    }


def related_event_score(event, candidate):
    """Return a conservative relevance score, or None when evidence is weak."""
    shared_topics = _event_terms(event, "topics") & _event_terms(candidate, "topics")
    shared_vendors = _event_terms(event, "vendors") & _event_terms(candidate, "vendors")
    title_similarity = sim(
        title_bigrams(event.get("zh_title", "")),
        title_bigrams(candidate.get("zh_title", "")),
    )
    signals = sum((bool(shared_topics), bool(shared_vendors), title_similarity >= 0.14))
    if signals < 2:
        return None
    same_category = event.get("category") == candidate.get("category")
    return (
        signals,
        min(len(shared_topics), 3),
        min(len(shared_vendors), 3),
        title_similarity,
        int(same_category),
        int(candidate.get("importance") or 0),
    )


def select_related_events(event, all_events, limit=3):
    scored = []
    for candidate in all_events:
        if candidate.get("event_id") == event.get("event_id"):
            continue
        score = related_event_score(event, candidate)
        if score is not None:
            scored.append((score, candidate))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [candidate for _score, candidate in scored[:limit]]


def article_toc_entries(blocks, minimum=6):
    headings = []
    for block in blocks:
        if block.get("type") != "heading":
            continue
        label = blocks_plain_text([block]).strip()
        if not label:
            continue
        headings.append({
            "id": f"article-section-{len(headings) + 1}",
            "label": label[:120],
            "level": min(4, max(2, int(block.get("level") or 2))),
        })
    return headings if len(headings) >= minimum else []


def render_article_toc(entries):
    if not entries:
        return "", ""
    links = "".join(
        f'<li class="toc-level-{entry["level"]}"><a href="#{entry["id"]}" '
        f'data-toc-link data-toc-target="{entry["id"]}">{esc(entry["label"])}</a></li>'
        for entry in entries
    )
    mobile = (
        '<details class="article-toc-mobile">'
        f'<summary>本文目录 <span>{len(entries)} 节</span></summary>'
        f'<ol>{links}</ol></details>'
    )
    desktop = (
        '<aside class="article-toc-rail" aria-label="本文目录">'
        f'<div class="article-toc-title">本文目录 <span>{len(entries)} 节</span></div>'
        f'<ol>{links}</ol></aside>'
    )
    return mobile, desktop

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
        'aria-expanded="false" aria-controls="ttsPlayer" aria-label="速听" title="速听">'
        f'{ic("headphones",15)} <span class="sbtn-label" data-tts-open-label>速听</span></button>'
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
    related = select_related_events(e, all_events)
    rel_html = "".join(
        f'<a class="vendor-row" href="../{detail_url(x)}">'
        f'<span class="n">›</span><span class="related-title">{esc(x["zh_title"])}</span>'
        f'<span class="related-meta">{esc(x.get("category_label") or x.get("category") or "同主题")}</span></a>'
        for x in related
    )
    related_html = (
        f'<section class="card related-events" aria-labelledby="relatedEventsTitle">'
        f'<h4 id="relatedEventsTitle">{ic("list")} 相关事件</h4>{rel_html}</section>'
        if rel_html else ""
    )
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
    feedback_context = esc(json.dumps({
        "topics": list(e.get("topics") or [])[:8],
        "vendors": list(e.get("vendors") or [])[:8],
        "source": main_src_name,
    }, ensure_ascii=False, separators=(",", ":")))
    feedback_html = f'''<section class="content-feedback" data-content-feedback data-event-id="{event_id}" data-feedback-context="{feedback_context}" aria-labelledby="contentFeedbackTitle">
  <div class="content-feedback-main">
    <div><h2 id="contentFeedbackTitle">这篇内容对你有用吗？</h2><p data-feedback-status aria-live="polite">反馈只用于改善内容筛选，不等同于收藏</p></div>
    <div class="content-feedback-actions">
      <button type="button" data-feedback-value="useful" aria-pressed="false">有用</button>
      <button type="button" data-feedback-value="not_useful" aria-pressed="false">没用</button>
    </div>
  </div>
  <div class="content-feedback-reasons" data-feedback-reasons="useful" hidden aria-label="有用的原因">
    <span>可选原因</span><button type="button" data-feedback-reason="solid">内容扎实</button><button type="button" data-feedback-reason="relevant">贴合工作</button><button type="button" data-feedback-reason="novel">提供新观点</button><button type="button" data-feedback-reason="source_discovery">发现好信源</button>
  </div>
  <div class="content-feedback-reasons" data-feedback-reasons="not_useful" hidden aria-label="没用的原因">
    <span>可选原因</span><button type="button" data-feedback-reason="irrelevant">不相关</button><button type="button" data-feedback-reason="shallow">太浅</button><button type="button" data-feedback-reason="marketing">营销软文</button><button type="button" data-feedback-reason="duplicate">内容重复</button><button type="button" data-feedback-reason="body_quality">正文质量差</button>
  </div>
</section>'''
    main_source_meta = (
        f'<a class="meta-source-link" href="{main_link}" target="_blank" '
        f'rel="noopener noreferrer" data-analytics="outbound" data-source="{main_src}" '
        f'aria-label="查看 {esc(src_display(main_src_name))} 原文">'
        f'<span>{esc(src_display(main_src_name))}</span>{ic("arrow", 12)}</a>'
        if main_url else
        f'<span class="meta-source-text">{esc(src_display(main_src_name))}</span>'
    )
    original_footer_link = (
        f'<a class="original-footer-link" href="{main_link}" target="_blank" '
        f'rel="noopener noreferrer" data-analytics="outbound" data-source="{main_src}">'
        f'<span>查看原文</span>{ic("arrow",14)}</a>'
        if main_url else ""
    )
    # blocks-v1 先经本地白名单清洗再渲染；异常或旧数据安全降级到 full_zh。
    safe_blocks, _display_quality = trim_article_blocks(
        sanitize_blocks(e.get("content_blocks", []), main_url)
    )
    if (
        len(safe_blocks) >= 2 and safe_blocks[0].get("type") == "figure"
        and not (safe_blocks[0].get("alt") or safe_blocks[0].get("caption"))
        and safe_blocks[1].get("type") == "heading"
    ):
        safe_blocks = safe_blocks[1:]
    if safe_blocks and safe_blocks[0].get("type") == "heading":
        import difflib as _dl
        leading = blocks_plain_text([safe_blocks[0]]).strip()
        known_titles = [e.get("zh_title", ""), primary_item.get("title", "")]
        if leading and max(
            (_dl.SequenceMatcher(None, leading.casefold(), title.casefold()).ratio() for title in known_titles if title),
            default=0,
        ) >= 0.72:
            safe_blocks = safe_blocks[1:]
    render_media = os.getenv("MEDIA_BLOCKS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
    toc_entries = article_toc_entries(safe_blocks)
    heading_ids = [entry["id"] for entry in toc_entries]
    full_paras = (
        render_blocks_html(safe_blocks, render_media=render_media, heading_ids=heading_ids)
        if safe_blocks else ""
    )
    if not full_paras:
        paras_all = [pp.strip() for pp in re.split(r"\n\s*\n", e.get("full_zh", "")) if pp.strip()]
        if paras_all and paras_all[0].startswith("## "):
            import difflib as _dl
            if _dl.SequenceMatcher(None, paras_all[0][3:], e["zh_title"]).ratio() > 0.6:
                paras_all = paras_all[1:]
        legacy_labels = [para[3:].strip() for para in paras_all if para.startswith("## ") and para[3:].strip()]
        if len(legacy_labels) >= 6:
            toc_entries = [
                {"id": f"article-section-{index}", "label": label[:120], "level": 3}
                for index, label in enumerate(legacy_labels, 1)
            ]
        legacy_heading_index = 0
        for para in paras_all:
            if para.startswith("## "):
                navigation_attrs = ""
                if toc_entries:
                    navigation_attrs = (
                        f' id="{toc_entries[legacy_heading_index]["id"]}" data-article-heading'
                    )
                    legacy_heading_index += 1
                full_paras += f'<h5 class="fh"{navigation_attrs}>{esc(para[3:])}</h5>'
            elif para.startswith("【"):
                full_paras += f'<p class="fwarn">{esc(para)}</p>'
            else:
                full_paras += "".join(f"<p>{esc(x)}</p>" for x in para.split("\n") if x.strip())
    content_mode = e.get("content_mode") or "legacy_ai"
    if content_mode == "translated":
        content_title = "译文"
        content_badge = "AI 逐段翻译"
        content_note = ""
        meta_mode_label = "AI 逐段翻译"
    elif content_mode == "original" and e.get("source_language") == "zh":
        content_title = "原文"
        content_badge = ""
        content_note = "正文来自 RSS 或原网页；DataHot 仅做安全清洗和版式整理，未使用 AI 改写"
        meta_mode_label = "原文"
    elif content_mode == "original":
        content_title = "原文"
        content_badge = ""
        content_note = "当前直接显示原文，自动翻译暂不可用；未进行 AI 摘写或重组"
        meta_mode_label = "原文 · 未翻译"
    elif content_mode == "ai_fallback":
        content_title = "内容摘要"
        content_badge = "原文不可用 · 降级展示"
        content_note = "未获得可用全文，当前为降级内容，仅供定位原始信源"
        meta_mode_label = "内容摘要"
    else:
        content_title = "历史编译稿"
        content_badge = "旧版 AI 基于原文编译"
        content_note = "这是改版前生成的历史 AI 编译内容，后续将由原文或忠实译文替换"
        meta_mode_label = "历史编译稿"
    toc_mobile_html, toc_rail_html = render_article_toc(toc_entries)
    progress_html = (
        '<span class="reading-progress" aria-hidden="true"><span data-reading-progress></span></span>'
        if toc_entries else ""
    )
    full_block = ""
    if full_paras:
        badge_html = f' <span class="content-origin-badge">{content_badge}</span>' if content_badge else ""
        note_html = f'<div class="disclaimer">{content_note}</div>' if content_note else ""
        footer_html = (
            f'<div class="content-footer">{note_html}{original_footer_link}</div>'
            if note_html or original_footer_link else ""
        )
        full_block = f'''<section class="content-section" aria-labelledby="articleBodyTitle">
  <div class="content-heading"><h2 id="articleBodyTitle">{ic("file")} {content_title}</h2>{badge_html}</div>
  <div class="fulltext">{full_paras}</div>
  {footer_html}
</section>'''
    brief_reason = clean_reason(e.get("reason", ""))
    brief_html = f'''<details class="article-brief" open>
  <summary>DataHot 速览</summary>
  <div class="article-brief-body"><p>{esc(e["zh_summary"])}</p>
  {f'<p class="brief-why"><b>为什么值得关注：</b>{esc(brief_reason)}</p>' if brief_reason else ''}</div>
</details>'''
    topic_html = (
        f'<div class="vendors article-tags" aria-label="文章主题">{vtags}</div>'
        if vtags else ""
    )
    page_url = f"{SITE_BASE}/e/{event_id}.html"
    social_image = social_image_for_event(e, SITE_BASE)
    if social_image:
        social_image_meta = (
            f'<meta property="og:image" content="{esc(social_image["url"])}">\n'
            f'<meta property="og:image:alt" content="{esc(social_image["alt"])}">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:image" content="{esc(social_image["url"])}">\n'
            f'<meta name="twitter:image:alt" content="{esc(social_image["alt"])}">'
        )
    else:
        social_image_meta = '<meta name="twitter:card" content="summary">'
    jsonld_payload = {
        "@context": "https://schema.org", "@type": "NewsArticle",
        "headline": e["zh_title"], "description": e["zh_summary"][:150],
        "datePublished": e["published"], "inLanguage": "zh-CN",
        "publisher": {"@type": "Organization", "name": "DataHot"},
    }
    if main_url:
        jsonld_payload["isBasedOn"] = main_url
    if social_image:
        jsonld_payload["image"] = social_image["url"]
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
{social_image_meta}
<link rel="icon" href="../favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="../icons/favicon-32.png">
<link rel="apple-touch-icon" href="../icons/apple-touch-icon.png">
<meta name="theme-color" content="#1a1d23">
{feed_discovery()}
{analytics_head("../")}
{favorites_head("../")}
<script defer src="../content-feedback.js"></script>
<script defer src="../detail.js"></script>
<script type="application/ld+json">{jsonld}</script>
<style>{css}
{SHARED_CSS}
.article{{max-width:1040px;margin:0 auto;padding:36px 20px 60px}}
.article-layout{{max-width:1000px;margin:0 auto}}
.article-content{{max-width:840px;margin:0 auto}}
.article-layout.has-toc{{display:grid;grid-template-columns:minmax(0,840px) 144px;gap:16px;align-items:start}}
.article-layout.has-toc .article-content{{min-width:0;margin:0}}
.article .back{{font-size:13px;color:var(--sub);display:inline-block;margin-bottom:18px}}
.article h1{{max-width:700px;font-size:30px;font-weight:800;line-height:1.38;margin:14px auto 20px}}
.article .meta{{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--sub);flex-wrap:wrap}}
.article .meta,.article-brief,.tts-player{{max-width:700px;margin-left:auto;margin-right:auto}}
.meta-source-link{{display:inline-flex;align-items:center;gap:3px;color:var(--txt3);font-weight:650;text-decoration:none}}
.meta-source-link svg{{flex:0 0 auto}}
.meta-source-text{{color:var(--txt3);font-weight:650}}
.meta-content-mode{{display:inline-flex;align-items:center;min-height:22px;padding:2px 8px;border-radius:99px;background:var(--soft);color:var(--txt2);font-size:10.5px;font-weight:700}}
.article .card{{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px 22px;margin:18px 0}}
.article h4{{font-size:14px;font-weight:800;margin-bottom:10px}}
.article-brief{{border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-top:18px;margin-bottom:30px}}
.article-brief>summary{{cursor:pointer;list-style:none;padding:13px 0;font-size:13px;font-weight:750;color:var(--txt2)}}
.article-brief>summary::-webkit-details-marker{{display:none}}
.article-brief>summary::after{{content:" ↓";color:var(--sub)}}
.article-brief[open]>summary::after{{content:" ↑"}}
.article-brief-body{{padding:0 0 16px;color:var(--txt3)}}
.article-brief-body p{{font-size:14px;line-height:1.8;margin:0}}
.article-brief-body .brief-why{{margin-top:9px;color:var(--txt2)}}
.content-section{{margin:0 0 30px}}
.content-heading{{max-width:700px;margin:0 auto 22px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:10px}}
.content-heading h2{{display:flex;align-items:center;gap:7px;font-size:15px;line-height:1.5;margin:0;color:var(--ink)}}
.content-origin-badge{{font-size:11px;color:var(--sub);font-weight:500}}
.article .vendor-row{{text-decoration:none}}
.related-title{{min-width:0;flex:1;line-height:1.55}}
.related-meta{{flex:0 0 auto;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--sub);font-size:11px}}
.article-toc-mobile{{display:none;max-width:700px;margin:0 auto 24px;border:1px solid var(--line);border-radius:10px;background:var(--card)}}
.article-toc-mobile>summary{{display:flex;align-items:center;justify-content:space-between;min-height:46px;padding:0 14px;cursor:pointer;list-style:none;color:var(--ink);font-size:13px;font-weight:750}}
.article-toc-mobile>summary::-webkit-details-marker{{display:none}}
.article-toc-mobile>summary span,.article-toc-title span{{color:var(--sub);font-size:10.5px;font-weight:500}}
.article-toc-mobile ol,.article-toc-rail ol{{list-style:none;margin:0;padding:0}}
.article-toc-mobile ol{{max-height:50vh;overflow-y:auto;padding:0 14px 12px;border-top:1px solid var(--soft)}}
.article-toc-mobile li{{margin:0}}
.article-toc-mobile a{{display:block;padding:8px 0;border-bottom:1px solid var(--soft);color:var(--txt2);font-size:12px;line-height:1.5;text-decoration:none}}
.article-toc-mobile li:last-child a{{border-bottom:0}}
.article-toc-mobile .toc-level-3 a,.article-toc-mobile .toc-level-4 a{{padding-left:12px}}
.article-toc-rail{{position:sticky;top:82px;max-height:calc(100vh - 104px);overflow-y:auto;padding:10px 0 12px 14px;border-left:1px solid var(--line);scrollbar-width:thin}}
.article-toc-title{{display:flex;justify-content:space-between;gap:6px;margin-bottom:7px;color:var(--ink);font-size:11.5px;font-weight:800}}
.article-toc-rail a{{display:block;padding:5px 0;color:var(--sub);font-size:10.5px;line-height:1.45;text-decoration:none}}
.article-toc-rail .toc-level-3 a,.article-toc-rail .toc-level-4 a{{padding-left:9px}}
.article-toc-rail a[aria-current="location"]{{color:var(--accent);font-weight:750}}
[data-article-heading]{{scroll-margin-top:88px}}
.reading-progress{{position:absolute;left:0;right:0;bottom:-1px;height:2px;overflow:hidden;background:transparent}}
.reading-progress>span{{display:block;width:100%;height:100%;background:var(--accent);transform:scaleX(0);transform-origin:left center;will-change:transform}}
.source-section{{border-top:1px solid var(--line);margin:26px 0 18px;padding-top:16px}}
.source-heading{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:4px}}
.source-heading h4{{margin:0}}
.source-summary{{font-size:11.5px;color:var(--sub)}}
.source-group{{padding:10px 0;border-bottom:1px solid var(--soft)}}
.source-group-head{{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--txt3);margin-bottom:2px}}
.source-group-head b{{font-weight:700}}
.source-group-head span{{font-size:10.5px;color:var(--sub)}}
.source-report{{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:baseline;gap:14px;padding:4px 0;color:var(--ink);text-decoration:none;font-size:13px;line-height:1.55}}
.source-report-title{{min-width:0;overflow-wrap:anywhere}}
.source-report-date{{font-size:11px;color:var(--sub);font-variant-numeric:tabular-nums;white-space:nowrap}}
.source-more{{padding-top:8px}}
.source-more>summary{{width:max-content;max-width:100%;font-size:12px;color:var(--accent);cursor:pointer;list-style:none;padding:4px 0}}
.source-more>summary::-webkit-details-marker{{display:none}}
.source-more>summary::after{{content:" ↓"}}
.source-more[open]>summary::after{{content:" ↑"}}
.content-feedback{{max-width:700px;margin:28px auto 22px;padding:18px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}}
.content-feedback-main{{display:flex;align-items:center;justify-content:space-between;gap:18px}}
.content-feedback h2{{font-size:14px;line-height:1.5;margin:0 0 3px;color:var(--ink)}}
.content-feedback p{{font-size:11.5px;line-height:1.5;margin:0;color:var(--sub)}}
.content-feedback-actions{{display:flex;gap:8px;flex:0 0 auto}}
.content-feedback button{{min-height:38px;border:1px solid var(--line);border-radius:99px;background:var(--card);color:var(--txt2);font-size:12px;font-weight:700;padding:7px 14px;cursor:pointer}}
.content-feedback button.on{{border-color:var(--accent);background:var(--accent-soft);color:var(--accent)}}
.content-feedback-reasons{{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:12px}}
.content-feedback-reasons[hidden]{{display:none}}
.content-feedback-reasons span{{font-size:11px;color:var(--sub)}}
.content-feedback-reasons button{{min-height:32px;font-size:11px;font-weight:600;padding:5px 10px}}
@media(max-width:600px){{.content-feedback-main{{align-items:flex-start;flex-direction:column;gap:12px}}.content-feedback-actions{{width:100%}}.content-feedback-actions button{{flex:1}}}}
@media(max-width:600px){{.source-report{{grid-template-columns:1fr;gap:0}}.source-report-date{{margin-top:1px}}}}
.fulltext>:not(.cb-figure):not(.cb-table-shell){{max-width:700px;margin-left:auto;margin-right:auto}}
.fulltext .cb-heading{{font-size:19px;line-height:1.55;margin-top:32px;margin-bottom:12px;color:var(--ink)}}
.fulltext p{{margin-top:0;margin-bottom:18px}}
.fulltext strong{{font-weight:750;color:var(--ink)}}
.fulltext em{{font-style:italic}}
.fulltext a{{color:var(--blue);text-decoration:underline;text-underline-offset:2px;overflow-wrap:anywhere}}
.fulltext ul,.fulltext ol{{padding-left:26px;margin-top:10px;margin-bottom:22px}}
.fulltext li{{margin:6px 0;padding-left:2px}}
.fulltext blockquote{{margin-top:20px;margin-bottom:20px;padding:12px 18px;border-left:4px solid var(--accent);background:var(--soft);border-radius:0 8px 8px 0;color:var(--txt2)}}
.fulltext code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:var(--soft);border:1px solid var(--line);border-radius:5px;padding:1px 5px}}
.fulltext pre{{overflow:auto;background:#171a20;color:#e8ebf0;border-radius:10px;padding:14px 16px;margin:16px 0;line-height:1.65}}
.fulltext pre code{{background:none;border:none;padding:0;color:inherit}}
.cb-table-shell{{position:relative;margin:16px 0}}
.cb-table{{overflow-x:auto;overscroll-behavior-inline:contain;-webkit-overflow-scrolling:touch;margin:0;border:1px solid var(--line);border-radius:9px}}
.cb-table:focus-visible{{outline:2px solid var(--blue);outline-offset:2px}}
.cb-table table{{border-collapse:collapse;width:100%;min-width:480px;font-size:13px}}
.cb-table th,.cb-table td{{padding:9px 12px;border-bottom:1px solid var(--line);border-right:1px solid var(--line);text-align:left;vertical-align:top}}
.cb-table th{{background:var(--soft);color:var(--ink);font-weight:700}}
.cb-table tr:last-child td{{border-bottom:none}}
.cb-table th:first-child,.cb-table td:first-child{{position:sticky;left:0;z-index:1;background:var(--card);box-shadow:1px 0 0 var(--line)}}
.cb-table th:first-child{{z-index:2;background:var(--soft)}}
.table-scroll-hint{{display:none;position:absolute;right:8px;bottom:8px;z-index:3;padding:4px 8px;border-radius:99px;background:rgba(26,29,35,.88);color:#fff;font-size:10.5px;font-weight:700;pointer-events:none;box-shadow:0 3px 12px rgba(0,0,0,.16)}}
.cb-table-shell.is-overflowing:not(.has-scrolled) .table-scroll-hint{{display:block}}
.cb-table-shell.is-overflowing:not(.at-end)::after{{content:"";position:absolute;top:1px;right:1px;bottom:1px;width:24px;border-radius:0 8px 8px 0;background:linear-gradient(90deg,transparent,var(--card));pointer-events:none}}
.cb-figure{{margin:20px 0;background:var(--soft);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
.cb-media-link{{display:block;background:#f5f7fa;text-decoration:none}}
.cb-figure img{{display:block;width:100%;height:auto;max-height:72vh;object-fit:contain;margin:0 auto}}
@media(max-width:600px){{.cb-figure{{margin:16px -8px;border-radius:9px}}.cb-table-shell{{max-width:100%;margin-left:0;margin-right:0}}}}
@media (prefers-color-scheme: dark){{.cb-media-link{{background:#171a20}}}}
.tone-accent{{color:var(--accent);font-weight:650}}.tone-warning{{color:var(--amber);font-weight:650}}
.tone-positive{{color:var(--green);font-weight:650}}.tone-info{{color:var(--blue);font-weight:650}}.tone-emphasis{{color:var(--ink);font-weight:650}}
.cta{{display:inline-block;background:var(--accent);color:#fff;font-size:14px;font-weight:700;border-radius:10px;padding:11px 26px;margin:6px 0 4px}}
.fulltext h5.fh{{font-size:15px;font-weight:800;color:var(--ink);margin:20px 0 8px;padding-left:10px;border-left:3px solid var(--accent)}}
.fulltext p.fwarn{{font-size:12.5px;color:var(--amber);background:var(--accent-soft);border-radius:8px;padding:8px 12px}}
.fulltext p,.fulltext li{{font-size:16px;line-height:1.86;color:var(--txt3)}}
.tts-player{{display:grid;grid-template-columns:auto auto minmax(120px,1fr) auto auto;align-items:center;gap:10px 12px;background:linear-gradient(135deg,var(--card),var(--soft));border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:2px 0 18px}}
.tts-player[hidden]{{display:none}}
.tts-copy{{display:flex;flex-direction:column;min-width:112px;line-height:1.35}}
.tts-copy b{{font-size:12.5px;color:var(--ink)}}
.tts-copy span{{font-size:10.5px;color:var(--sub);margin-top:2px}}
.tts-toggle{{min-width:58px;min-height:44px;border:0;border-radius:99px;background:var(--ink);color:var(--card);font-size:12px;font-weight:750;padding:7px 13px;cursor:pointer}}
.tts-progress{{width:100%;accent-color:var(--accent);cursor:pointer}}
.tts-time{{font-size:11px;color:var(--sub);font-variant-numeric:tabular-nums;white-space:nowrap}}
.tts-rate-label{{font-size:10.5px;color:var(--sub);display:flex;align-items:center;gap:4px}}
.tts-rate-label select{{border:1px solid var(--line);border-radius:7px;background:var(--card);color:var(--ink);font-size:11px;padding:4px 5px}}
@media(max-width:600px){{.tts-player{{grid-template-columns:1fr auto auto;gap:9px;padding:11px 12px}}.tts-copy{{grid-column:1/-1;grid-row:1;flex-direction:row;align-items:baseline;gap:8px}}.tts-toggle{{grid-column:1;grid-row:2}}.tts-time{{grid-column:2;grid-row:2}}.tts-rate-label{{grid-column:3;grid-row:2}}.tts-progress{{grid-column:1/-1;grid-row:3}}}}
@media(prefers-reduced-motion:reduce){{.tts-player *{{scroll-behavior:auto!important;transition:none!important}}}}
@media(hover:hover) and (pointer:fine){{
  .article .back:hover,.meta-source-link:hover,.source-report:hover .source-report-title,.original-footer-link:hover,.article-toc-mobile a:hover,.article-toc-rail a:hover{{color:var(--accent)}}
  .cta:hover{{opacity:.9}}
}}
.content-footer{{max-width:700px;display:flex;align-items:center;justify-content:flex-end;gap:12px;border-top:1px dashed var(--line);padding-top:10px;margin:20px auto 0}}
.disclaimer{{flex:1;font-size:12px;color:var(--sub)}}
.original-footer-link{{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:44px;padding:7px 12px;border-radius:99px;color:var(--blue);font-size:12.5px;font-weight:700;text-decoration:none;white-space:nowrap}}
.original-footer-link:focus-visible,.meta-source-link:focus-visible,.article-toc-mobile summary:focus-visible,.article-toc-mobile a:focus-visible,.article-toc-rail a:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
@media(max-width:1199px){{.article-layout.has-toc{{display:block}}.article-layout.has-toc .article-content{{margin:0 auto}}.article-toc-rail{{display:none}}.article-toc-mobile{{display:block}}}}
@media(max-width:600px){{.article{{padding-left:16px;padding-right:16px}}.article h1{{font-size:24px;line-height:1.45}}.fulltext>:not(.cb-figure):not(.cb-table-shell){{max-width:none}}.fulltext p,.fulltext li{{font-size:16px;line-height:1.82}}.content-footer{{align-items:flex-start;flex-direction:column;gap:4px}}.original-footer-link{{align-self:flex-end}}.related-meta{{max-width:88px}}}}
</style></head><body class="has-sb mobile-detail" data-page="detail" data-event-id="{event_id}" data-category="{esc(e["category"])}" data-source="{main_src}">
{sidebar("home", prefix="../")}
<header class="detail-brand-header"><div class="wrap nav">
  <div class="logo"><a href="../index.html" data-smart-home-return>Data<em>Hot</em></a><span class="tag">每 6 小时更新</span></div>
</div></header>
<div class="article">
  <div class="topbar detail-context">
    <a class="back" href="../index.html" data-smart-back aria-label="返回"><span aria-hidden="true">←</span><span class="back-label">返回</span></a>
    <span class="sharebtns">
      {favorite_button(e, class_name="sbtn ghost favbtn", label="收藏")}
{("      " + tts_button) if tts_button else ""}
      <button class="sbtn ghost" type="button" data-share-action="poster" data-poster-qr-src="../qr/{event_id}.png" title="海报" aria-label="海报">{ic("image",15)}<span class="sbtn-label">海报</span></button>
      <button class="sbtn" type="button" data-share-action="open" title="分享" aria-label="分享">{ic("share",15)}<span class="sbtn-label">分享</span></button>
    </span>
    {progress_html}
  </div>
  <div class="article-layout{' has-toc' if toc_entries else ''}">
  <main class="article-content">
  <div class="meta">
    <span class="srcbadge">{src_badge(main_src_name)}</span>
    {main_source_meta}
    <span class="meta-content-mode">{esc(meta_mode_label)}</span>
    {'<span class="star">精选</span>' if e.get("star") else ''}
    <span title="发布时间">{("发布 " + fmt_date(e["published"])) if e.get("published") else "收录 " + fmt_date(e.get("first_seen"))}</span>
    {f'<span style="color:var(--sub);font-size:11px" title="DataHot 收录此内容的时间">收录于 {md(e.get("first_seen"))}</span>' if e.get("published") and e.get("first_seen") and e["published"][:10] != e["first_seen"][:10] else ""}
  </div>
  <h1>{esc(e["zh_title"])}</h1>
{("  " + tts_player) if tts_player else ""}
  {brief_html}
  {toc_mobile_html}
  {full_block}
  {topic_html}
{supplement_sources}
  {feedback_html}
  {related_html}
  </main>
  {toc_rail_html}
  </div>
</div>
<footer>DataHot，数据领域AI资讯分享 · <a href="../privacy.html">隐私</a> · <a href="https://github.com/henryhb1105-arch/datahot" target="_blank" rel="noopener noreferrer" style="color:var(--sub);text-decoration:underline">GitHub 开源</a> · {BLUESKY_FOOTER_LINK}</footer>
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
        "qr": f'../qr/{safe_event_id(e["event_id"])}.png',
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
.sharebtns{display:flex;justify-content:flex-end;gap:8px;min-width:0;max-width:100%;margin-left:auto}
.sharebtns .sbtn{min-width:76px}
.sbtn{display:inline-flex;align-items:center;justify-content:center;gap:4px;flex:0 0 auto;min-height:44px;white-space:nowrap;line-height:1.2;border:none;background:var(--accent);color:#fff;border-radius:99px;padding:7px 14px;font-size:12.5px;font-weight:600;cursor:pointer}
.sbtn svg{flex:0 0 auto}
.sbtn.ghost{background:var(--card);color:var(--ink);border:1px solid var(--line)}
.sbtn:active{transform:scale(.95)}
.topbar.detail-context{position:sticky;top:0;z-index:55;margin:-36px -20px 16px;padding:calc(10px + env(safe-area-inset-top)) 20px 10px;background:var(--header-bg);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.topbar.detail-context .back{display:inline-flex;align-items:center;justify-content:center;align-self:center;min-width:88px;min-height:44px;margin-bottom:0;padding:0 14px;border-radius:99px;font-size:14px;font-weight:650;color:var(--ink);text-decoration:none}
.topbar.detail-context .back{gap:5px}
.topbar.detail-context .back:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:600px){
.article{padding:20px 14px 48px}
.topbar{align-items:center;flex-direction:row;gap:8px}
.topbar.detail-context{margin:-20px -14px 14px;padding:calc(10px + env(safe-area-inset-top)) 14px 10px}
.topbar.detail-context .back{align-self:center}
.sharebtns{width:auto;gap:4px;overflow:visible;padding-bottom:0}
.sharebtns .sbtn{width:56px;min-width:56px;height:44px;padding:0 6px;font-size:12px}
.sharebtns .sbtn-label{display:inline}
}
@media(max-width:359px){
.topbar.detail-context .back{width:44px;min-width:44px;padding:0}
.topbar.detail-context .back-label{display:none}
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
.sh-save,.sh-close{display:inline-flex;align-items:center;justify-content:center;min-height:44px;border:none;border-radius:99px;padding:11px 22px;font-size:14px;font-weight:600;cursor:pointer;text-decoration:none}
.sbtn:focus-visible,.sh-opt:focus-visible,.sh-cancel:focus-visible,.sh-save:focus-visible,.sh-close:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
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
  function fallbackCopy(text){
    var i=document.createElement('input');i.value=text;i.setAttribute('readonly','');document.body.appendChild(i);i.select();
    var ok=false;try{ok=document.execCommand('copy');}catch(e){ok=false}i.remove();return ok;
  }
  var copied=navigator.clipboard&&navigator.clipboard.writeText
    ?navigator.clipboard.writeText(SH_EV.url).then(function(){return true},function(){return fallbackCopy(SH_EV.url)})
    :Promise.resolve(fallbackCopy(SH_EV.url));
  copied.then(function(ok){shToast(ok?'链接已复制，去粘贴吧':'复制失败，请手动复制链接');});
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
  x.drawImage(qrImg,74,y+46,130,130);
  x.fillStyle=P.name;x.font='700 30px -apple-system,PingFang SC,sans-serif';
  x.fillText('扫码阅读全文或忠实译文',240,y+60);
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
var posterURL=null,posterDark=null,posterLoading=false;
function openPoster(){
  var dark=window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches;
  if(posterURL&&posterDark===dark){showPoster();return;}
  if(posterLoading){return;}
  posterLoading=true;
  posterDark=dark;
  var qr=new Image();
  qr.onload=function(){
    try{posterURL=drawPoster(qr,dark);posterLoading=false;showPoster();}
    catch(error){posterLoading=false;posterURL=null;shToast('海报生成失败，请稍后重试');}
  };
  qr.onerror=function(){posterLoading=false;posterURL=null;shToast('海报生成失败，请稍后重试');};
  qr.src=SH_EV.qr;
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
  document.getElementById('shPoster').classList.add('show');
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

def _topic_reference_time(events, reference_time=None):
    if reference_time is not None:
        return reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=TZ)
    timestamps = [event_timestamp(event) for event in events]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(timestamps) if timestamps else datetime.now(TZ)


def _topic_sorted_events(events):
    floor = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def key(event):
        timestamp = event_timestamp(event) or floor
        try:
            importance = int(event.get("importance", 50))
        except (TypeError, ValueError):
            importance = 50
        try:
            heat = int(event.get("heat", 0))
        except (TypeError, ValueError):
            heat = 0
        return timestamp, importance, heat

    return sorted(events, key=key, reverse=True)


def _topic_recent_events(events, reference_time):
    window = timedelta(days=TOPIC_RECENT_DAYS)
    recent = []
    for event in events:
        timestamp = event_timestamp(event)
        age = reference_time - timestamp.astimezone(reference_time.tzinfo) if timestamp else None
        if age is not None and timedelta(0) <= age <= window:
            recent.append(event)
    return _topic_sorted_events(recent)


def _topic_event_date(event):
    timestamp = event_timestamp(event)
    return timestamp.astimezone(TZ).strftime("%Y-%m-%d") if timestamp else "未知日期"


def _topic_event_source(event):
    items = event.get("items") or []
    return src_display(items[0].get("source", "")) if items else ""


def render_topics_map(events, css, reference_time=None):
    """主题地图页：稳定呈现技术主线，业务场景作为第二层导航。"""
    reference_time = _topic_reference_time(events, reference_time)
    meta_by_name = {topic["name"]: topic for topic in TOPICS_META}

    cards = []
    for name in TOPIC_TECH_MAINLINES:
        topic = meta_by_name.get(name)
        if not topic:
            continue
        topic_events = [event for event in events if name in event.get("topics", [])]
        if not topic_events:
            continue
        recent_count = len(_topic_recent_events(topic_events, reference_time))
        children = []
        for child_name in TOPIC_CHILDREN.get(name, ()):
            child = meta_by_name.get(child_name)
            if child and any(child_name in event.get("topics", []) for event in events):
                children.append(
                    f'<a class="tchild-link" href="topics/{child["slug"]}.html">{esc(child_name)}</a>'
                )
        children_html = (
            f'<div class="tchildren"><span>子议题</span>{"".join(children)}</div>'
            if children else ""
        )
        recent_copy = f"近 7 天新增 {recent_count}" if recent_count else "近 7 天暂无新增"
        cards.append(f'''<article class="tcard">
  <a class="tcard-main" href="topics/{topic["slug"]}.html">
    <h3>{esc(name)}</h3>
    <div class="td">{esc(topic["desc"])}</div>
    <div class="topic-counts"><span class="recent">{recent_copy}</span><span class="total">累计 {len(topic_events)}</span></div>
  </a>{children_html}
</article>''')

    scenarios = []
    for name in TOPIC_BUSINESS_SCENES:
        topic = meta_by_name.get(name)
        if not topic:
            continue
        topic_events = [event for event in events if name in event.get("topics", [])]
        if not topic_events:
            continue
        recent_count = len(_topic_recent_events(topic_events, reference_time))
        count_class = "scenario-count is-active" if recent_count else "scenario-count"
        count_copy = (
            f"近 7 天 +{recent_count} · 累计 {len(topic_events)}"
            if recent_count else f"观察中 · 累计 {len(topic_events)}"
        )
        scenarios.append(f'''<a class="scenario-row" href="topics/{topic["slug"]}.html">
  <span class="scenario-copy"><span class="scenario-name">{esc(name)}</span><span class="scenario-desc">{esc(topic["desc"])}</span></span>
  <span class="{count_class}">{count_copy}</span>
</a>''')

    body = f'''
<main class="wrap topic-map-page">
  <div class="section-title"><h1 style="font-size:20px">{ic("map",18)} 主题地图</h1><span>理解长期变化 · 按议题持续追踪</span></div>
  <p class="topic-map-intro">按长期议题理解数据与 AI 的变化，在业务场景中找到与你有关的内容。</p>
  <section class="topic-family" aria-labelledby="techMainlines">
    <div class="topic-family-head"><h2 id="techMainlines">技术主线</h2><p>稳定的长期议题，不按短期热度排名</p></div>
    <div class="tgrid">{"".join(cards)}</div>
  </section>
  <section class="topic-family" aria-labelledby="businessScenes">
    <div class="topic-family-head"><h2 id="businessScenes">业务场景</h2><p>用分析回答具体业务问题</p></div>
    <div class="scenario-list">{"".join(scenarios)}</div>
  </section>
</main>'''
    return page_shell(
        "主题地图 · DataHot", "按主题理解数据领域持续演进的技术主线与业务场景",
        css, body, tabbar("topics"), active="topics", canonical_path="topics.html",
    )


def render_topic_page(t, events, css, reference_time=None):
    """单个主题页：近期进展、入门阅读与渐进式历史动态。"""
    reference_time = _topic_reference_time(events, reference_time)
    topic_events = _topic_sorted_events([
        event for event in events if t["name"] in event.get("topics", [])
    ])
    recent = _topic_recent_events(topic_events, reference_time)
    vendors = sorted({vendor for event in topic_events for vendor in event.get("vendors", [])})

    recent_cards = "".join(f'''<article class="topic-recent-wrap" data-event-id="{safe_event_id(event["event_id"])}">
  <a class="topic-recent-card" href="../{detail_url(event)}">
  <span class="topic-recent-meta">{_topic_event_date(event)} · {esc(_topic_event_source(event))}</span>
  <h3>{esc(event["zh_title"])}</h3>
  <p>{esc(event.get("zh_summary", ""))}</p>
</a>
  {favorite_button(event, class_name="favbtn topic-recent-fav")}
</article>''' for event in recent[:3])
    recent_html = (
        f'<div class="topic-recent-grid">{recent_cards}</div>'
        if recent_cards else '<div class="topic-empty">近 7 天暂无新增，以下保留该主题的历史脉络。</div>'
    )

    reading = sorted(
        (event for event in topic_events if event.get("shelf") == "evergreen"),
        key=lambda event: (
            not event.get("pinned"),
            -int(event.get("importance", 50) or 50),
            -(event_timestamp(event) or datetime(1970, 1, 1, tzinfo=timezone.utc)).timestamp(),
        ),
    )[:TOPIC_READING_LIMIT]
    reading_html = ""
    if reading:
        rows = "".join(f'''<a class="crow" href="../{detail_url(event)}">
  <span class="cpin">{"📌" if event.get("pinned") else ""}</span>
  <span class="ctitle">{esc(event["zh_title"])}</span>
  <span class="cmeta">{_topic_event_date(event)}</span>
</a>''' for event in reading)
        reading_html = f'''
  <section class="topic-section" aria-labelledby="topicReading">
    <div class="topic-section-head"><h2 id="topicReading">{ic("bookmark",14)} 入门阅读</h2><p>精选长期内容，最多 {TOPIC_READING_LIMIT} 篇</p></div>
    <div class="topic-reading">{rows}</div>
  </section>'''

    update_rows = []
    for index, event in enumerate(topic_events):
        extra_class = " is-extra" if index >= TOPIC_UPDATE_PAGE_SIZE else ""
        update_rows.append(f'''<a class="topic-update-row{extra_class}" data-topic-update href="../{detail_url(event)}">
  <time class="topic-update-date">{_topic_event_date(event)}</time>
  <span class="topic-update-title">{esc(event["zh_title"])}</span>
  <span class="topic-update-source">{esc(_topic_event_source(event))}</span>
</a>''')
    visible_count = min(TOPIC_UPDATE_PAGE_SIZE, len(topic_events))
    load_more = ""
    progressive_fallback = ""
    if len(topic_events) > TOPIC_UPDATE_PAGE_SIZE:
        load_more = (
            f'<button class="topic-load-more" type="button" data-topic-load-more '
            f'data-step="{TOPIC_UPDATE_PAGE_SIZE}" aria-controls="topicUpdates">'
            f'加载更多（{visible_count}/{len(topic_events)}）</button>'
        )
        progressive_fallback = '''<noscript><style>
.topic-update-row.is-extra{display:grid!important}.topic-load-more{display:none!important}
</style></noscript>
<script>
document.addEventListener('DOMContentLoaded',function(){
  var button=document.querySelector('[data-topic-load-more]');
  if(!button){return;}
  var rows=Array.from(document.querySelectorAll('[data-topic-update]'));
  var step=parseInt(button.getAttribute('data-step')||'10',10);
  var shown=rows.filter(function(row){return !row.classList.contains('is-extra');}).length;
  button.addEventListener('click',function(){
    rows.slice(shown,shown+step).forEach(function(row){row.classList.remove('is-extra');});
    shown=Math.min(shown+step,rows.length);
    if(shown>=rows.length){button.remove();return;}
    button.textContent='加载更多（'+shown+'/'+rows.length+'）';
  });
});
</script>'''

    vendor_html = ""
    if vendors:
        vtags = "".join(f'<span class="vtag">{esc(vendor)}</span>' for vendor in vendors)
        vendor_html = f'''
  <section class="topic-section" aria-label="相关厂商">
    <details class="topic-vendors"><summary>涉及 {len(vendors)} 个厂商 <span>展开查看</span></summary><div class="vendors">{vtags}</div></details>
  </section>'''

    parent_html = ""
    parent_name = TOPIC_PARENTS.get(t["name"])
    if parent_name:
        parent = next((topic for topic in TOPICS_META if topic["name"] == parent_name), None)
        if parent:
            parent_html = f'<p class="topic-parent">所属主线：<a href="{parent["slug"]}.html">{esc(parent_name)}</a></p>'

    body = f'''
<main class="wrap topic-page">
  <header class="topic-hero">
    <a class="topic-back" href="../topics.html">← 主题地图</a>
    <h1>{esc(t["name"])}</h1>
    <p class="topic-hero-desc">{esc(t["desc"])}</p>
    <a class="topic-follow" href="../for-me.html?follow=topic:{quote(t['name'], safe='')}">＋ 关注此主题，在 For Me 查看</a>
    <div class="topic-counts"><span class="recent">近 7 天新增 {len(recent)}</span><span class="total">累计 {len(topic_events)} · 每 6 小时更新</span></div>
    {parent_html}
  </header>
  <section class="topic-section" aria-labelledby="recentProgress">
    <div class="topic-section-head"><h2 id="recentProgress">近期进展</h2><p>最近 7 天内最新的 3 条</p></div>
    {recent_html}
  </section>
  {reading_html}
  <section class="topic-section" aria-labelledby="allUpdates">
    <div class="topic-section-head"><h2 id="allUpdates">全部动态</h2><p>按发布时间倒序</p></div>
    <div class="topic-updates" id="topicUpdates">{"".join(update_rows)}</div>
    {load_more}
  </section>
  {vendor_html}
</main>
{progressive_fallback}'''
    return page_shell(
        f"{t['name']} · DataHot 主题", t["desc"], css, body,
        tabbar("topics", "../"), prefix="../", active="topics",
        canonical_path=f"topics/{t['slug']}.html",
    )

def page_shell(
    title, desc, css, body, tabbar_html, prefix="", active="", *,
    canonical_path=None, indexable=True,
):
    canonical_head = ""
    if canonical_path is not None:
        page_url = absolute_public_url(canonical_path, SITE_BASE)
        canonical_head = (
            f'<link rel="canonical" href="{page_url}">\n'
            f'<meta property="og:url" content="{page_url}">'
        )
    robots_head = "" if indexable else '<meta name="robots" content="noindex,follow">'
    return finalize_html_security(f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
{canonical_head}
{robots_head}
<link rel="icon" href="{prefix}favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="{prefix}icons/apple-touch-icon.png">
<meta name="theme-color" content="#1a1d23">
{feed_discovery()}
{analytics_head(prefix)}
{favorites_head(prefix)}
<style>{css}
{SHARED_CSS}
</style></head><body class="has-sb mobile-section" data-nav-active="{esc(active)}">
{sidebar(active, prefix=prefix)}
<header class="section-brand-header"><div class="wrap nav">
  <div class="logo"><a href="{prefix}index.html" style="text-decoration:none">Data<em>Hot</em></a><span class="tag">每 6 小时更新</span></div>
</div></header>
{body}
<footer>DataHot，数据领域AI资讯分享 · <a href="{prefix}privacy.html">隐私</a> · <a href="https://github.com/henryhb1105-arch/datahot" target="_blank" rel="noopener noreferrer" style="color:var(--sub);text-decoration:underline">GitHub 开源</a> · {BLUESKY_FOOTER_LINK}</footer>
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
    <p>DataHot 当前监控 {len(enabled_sources)} 个信源，覆盖 Data Agent、AI 数据平台、BI、数据产品和 AI分析，每 6 小时更新。最后更新 {gen.strftime("%m-%d %H:%M")}。</p>
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
                      tabbar("sources"), prefix="", active="sources", canonical_path="sources.html")

def render_hot_page(events, css, reference_time=None):
    """完整榜单：热度 TOP 9"""
    top = rank_hot_events(
        events, limit=9, source_cap=2, reference_time=reference_time,
    )
    row_parts = []
    for i, event in enumerate(top, 1):
        source = src_display(event["items"][0]["source"])
        extra = f' · 另有{len(event["items"]) - 1}家' if len(event["items"]) > 1 else ""
        top_class = " is-top" if i <= 3 else ""
        row_parts.append(f'''<a class="rank-row" href="{detail_url(event)}">
  <span class="rank-no{top_class}">{i}</span>
  <span class="rank-title">{esc(event["zh_title"])}</span>
  <span class="rank-meta"><span class="rank-source">{esc(source)}{extra}</span><span class="rank-heat">{ic("flame",12)} {event["heat"]}</span></span>
</a>''')
    rows = "".join(row_parts)
    body = f"""
<main class="wrap rank-page">
  <header class="rank-head"><h1>{ic("flame",20)} 完整榜单</h1><p>近 7 天 · TOP 9 · 同源最多 2 条</p></header>
  <div class="rank-list">{rows}</div>
  <details class="rank-note"><summary>热度如何计算</summary><p>{HEAT_FORMULA}；按热度降序，同一信源最多 2 条。</p></details>
</main>"""
    return page_shell(
        "完整榜单 · DataHot", "数据领域近 7 天热度 TOP 9", css, body,
        tabbar("home"), prefix="", active="hot", canonical_path="hot.html",
    )

def render_favorites_page(css, data_url="data/latest-lite.json"):
    """收藏页：本机快照优先，数据索引只用于补全旧版 event_id 收藏。"""
    body = f'''
<main class="wrap favorites-page" data-favorites-page data-favorites-data-url="{esc(data_url)}">
  <header class="favorites-head">
    <div>
      <h1 class="favorites-title">{ic("bookmark",22)} 我的收藏 <span class="favorites-count" id="favoritesCount">0 条</span></h1>
      <p class="favorites-trust">仅保存在当前浏览器 · 不上传；清除浏览器数据可能丢失。<a href="privacy.html">了解隐私</a></p>
    </div>
  </header>
  <section class="favorites-tools" id="favoritesTools" aria-label="查找收藏" hidden>
    <input class="favorites-search" id="favoritesSearch" type="search" placeholder="搜索收藏" aria-label="搜索收藏">
    <div class="favorites-filters" id="favoritesFilters" aria-label="按主题筛选收藏"></div>
  </section>
  <div id="favList" aria-live="polite" aria-busy="true"><div class="favorites-loading">正在读取本机收藏…</div></div>
  <noscript><div class="favorites-empty"><div class="favorites-empty-inner"><h2>需要启用 JavaScript</h2><p>收藏保存在当前浏览器中，启用 JavaScript 后即可读取。</p></div></div></noscript>
</main>'''
    return page_shell(
        "我的收藏 · DataHot", "你收藏的数据领域资讯", css, body,
        tabbar("favorites"), prefix="", active="favorites", indexable=False,
    )


def render_for_me_page(css, data_url="data/latest-lite.json"):
    """For Me：显式关注优先的本地个性化变化入口。"""
    weekly_label = "查看完整每周简报"
    weekly_href = "weekly.html" if weekly_brief_enabled() else "index.html"
    body = f'''
<div id="forMeDataConfig" data-lite-url="{esc(data_url)}" hidden></div>
<main class="wrap for-me-page">
  <header class="fm-hero">
    <div>
      <p class="fm-eyebrow">Your signal radar</p>
      <h1>For Me</h1>
      <p class="fm-subtitle">只看与你相关的重要变化</p>
    </div>
    <button class="fm-customize" id="fmCustomize" type="button" aria-expanded="false" aria-controls="fmSetup">调整关注</button>
    <div class="fm-visit"><span id="fmVisit">正在读取上次访问…</span><strong><span id="fmNewCount">—</span> 条未读变化</strong></div>
  </header>

  <section class="fm-setup" id="fmSetup" aria-labelledby="fmSetupTitle">
    <div class="fm-setup-head">
      <div><h2 id="fmSetupTitle">先选择你关心的内容</h2><p>主题和厂商可以混选，至少选择 3 个</p></div>
      <span class="fm-progress" id="fmProgress">已选择 0/3</span>
    </div>
    <div class="fm-suggestions" id="fmSuggestions" aria-label="可关注的主题与厂商"></div>
    <p class="fm-privacy">关注、已读和反馈只保存在这台设备，不需要登录，也不会上传。</p>
  </section>

  <div class="fm-loading" id="fmLoading" role="status">正在整理与你相关的变化…</div>
  <div class="fm-error" id="fmError" hidden>暂时无法读取最新内容。<br><button type="button">重新加载</button></div>

  <div id="fmContent" hidden>
    <section class="fm-section" id="fmMust" aria-labelledby="fmMustTitle">
      <div class="fm-section-head"><div><h2 id="fmMustTitle">必须知道</h2><p>与你的关注最相关，最多 3 条</p></div></div>
      <div class="fm-must-list" id="fmMustList"></div>
    </section>
    <div class="fm-empty" id="fmEmpty" hidden>暂时没有与你关注对象匹配的变化。可以调整关注，或稍后回来看看。</div>

    <section class="fm-section" id="fmFeed" aria-labelledby="fmFeedTitle">
      <div class="fm-section-head"><h2 id="fmFeedTitle">关注动态</h2><p>按内容质量、近期趋势和与你的适合度排序</p></div>
      <div class="fm-feed-list" id="fmFeedList"></div>
    </section>

    <section class="fm-section" aria-labelledby="fmWatchTitle">
      <div class="fm-section-head"><h2 id="fmWatchTitle">持续关注</h2><p>你的关注对象与当前覆盖</p></div>
      <div class="fm-watch-list" id="fmWatch"></div>
    </section>

    <section class="fm-section" id="fmDiscovery" aria-labelledby="fmDiscoveryTitle" hidden>
      <div class="fm-section-head"><h2 id="fmDiscoveryTitle">可能影响你</h2><p>关注范围外，最多 2 条</p></div>
      <div class="fm-discovery-list" id="fmDiscoveryList"></div>
    </section>

    <section class="fm-section" aria-label="本周回顾">
      <a class="fm-weekly" href="{weekly_href}"><span><b>For Me · 本周回顾</b><span id="fmWeeklyCount">正在整理本周变化</span> · {weekly_label}</span><span class="fm-weekly-arrow" aria-hidden="true">→</span></a>
    </section>
  </div>
  <noscript><div class="fm-error">For Me 需要浏览器 JavaScript 来保存本地关注。你仍可继续使用热榜、主题和周报。</div></noscript>
</main>
<script defer src="for-me.js"></script>'''
    return page_shell(
        "For Me · DataHot", "只看与你相关的数据与 AI 重要变化",
        css + FOR_ME_CSS, body, tabbar("for-me"), prefix="", active="for-me",
        indexable=False,
    )


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
        return ""
    return f'''<div class="weekly-strip" id="weeklyTeaser" data-week-id="{esc(brief.get("week_id"))}">
  <a class="weekly-strip-link" href="weekly.html" data-analytics="weekly_brief">
    <span class="weekly-strip-label">每周精选</span>
    <span class="weekly-strip-title">{esc(brief.get("title"))}</span>
    <span class="weekly-strip-view">查看<span class="weekly-strip-view-arrow" aria-hidden="true"> →</span></span>
  </a>
  <button class="weekly-dismiss" id="weeklyDismiss" type="button" aria-label="本周不再显示" title="本周不再显示">
    {ic("x", 16)}
  </button>
</div>'''


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
    canonical_path="weekly.html",
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
            canonical_path=canonical_path,
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
        canonical_path=canonical_path,
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
    <p style="margin-top:10px"><b>For Me、收藏与内容反馈：</b>关注、已读、收藏和文章反馈默认保存在本机，用于立即调整个人排序。匿名统计启用时，文章反馈只会发送事件 ID、“有用/没用”和预设原因，不发送评价文字或正文；关闭匿名统计后不上传。</p>
  </div>
  <div class="scard">
    <div data-analytics-status style="font-size:13px;color:var(--txt2);margin-bottom:12px">读取状态中…</div>
    <button class="privacy-btn" data-analytics-opt-out>关闭匿名统计并删除本机随机 ID</button>
    <button class="privacy-btn ghost" data-analytics-opt-in>恢复匿名统计</button>
  </div>
</div>'''
    return page_shell(
        "隐私与匿名统计 · DataHot", "DataHot 的隐私友好匿名统计说明与关闭开关",
        css, body, tabbar("privacy"), prefix="", active="privacy", canonical_path="privacy.html",
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


def write_qr_assets(all_events, qr_dir=None, site_base=SITE_BASE):
    """Generate same-origin QR PNGs for every stable detail URL and remove stale assets."""
    qr_dir = Path(qr_dir) if qr_dir is not None else QR_DIR
    qr_dir.mkdir(parents=True, exist_ok=True)
    valid_ids = set()
    for event in all_events:
        event_id = safe_event_id(event["event_id"])
        filename = event_id + ".png"
        valid_ids.add(filename)
        detail_url = f'{site_base.rstrip("/")}/e/{event_id}.html'
        code = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=5,
            border=4,
        )
        code.add_data(detail_url)
        code.make(fit=True)
        image = code.make_image(fill_color="black", back_color="white")
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        payload = output.getvalue()
        target = qr_dir / filename
        if not target.exists() or target.read_bytes() != payload:
            target.write_bytes(payload)
    for path in qr_dir.glob("*.png"):
        if path.name not in valid_ids:
            path.unlink()
    return valid_ids


RETIRED_PUBLIC_PAGES = ("classics.html",)


def remove_retired_public_pages(site_root=SITE):
    """删除已下线的公开页面，避免增量构建把旧入口重新发布。"""
    site_root = Path(site_root)
    for name in RETIRED_PUBLIC_PAGES:
        retired_page = site_root / name
        if retired_page.exists():
            retired_page.unlink()


def write_bluesky_handle_verification(site_root=SITE):
    """Publish the DID proof required for the DataHot domain handle."""
    path = Path(site_root) / ".well-known" / "atproto-did"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BLUESKY_DID, encoding="utf-8")
    return path


def main():
    SITE.mkdir(parents=True, exist_ok=True)
    remove_retired_public_pages()
    write_bluesky_handle_verification()
    if not all(asset.exists() for asset in (ANALYTICS_ASSET, CONTENT_FEEDBACK_ASSET, HOME_ASSET, FOR_ME_ASSET, FAVORITES_ASSET, DETAIL_ASSET, TTS_ASSET)):
        raise FileNotFoundError("missing browser asset")
    shutil.copyfile(ANALYTICS_ASSET, SITE / "analytics.js")
    shutil.copyfile(CONTENT_FEEDBACK_ASSET, SITE / "content-feedback.js")
    shutil.copyfile(HOME_ASSET, SITE / "home.js")
    shutil.copyfile(FOR_ME_ASSET, SITE / "for-me.js")
    shutil.copyfile(FAVORITES_ASSET, SITE / "favorites.js")
    shutil.copyfile(DETAIL_ASSET, SITE / "detail.js")
    shutil.copyfile(TTS_ASSET, SITE / "tts-player.js")
    payload = json.load(open(SITE / "data" / "latest.json"))
    all_events = payload["events"]
    normalize_category_labels(all_events)
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
        age = gen - timestamp.astimezone(TZ) if timestamp else None
        if age is not None and timedelta(0) <= age <= window:
            window_events.append(event)
    # 热点保持近 7 天；时间轴使用全部在站合格内容，避免旧洞察无法发现。
    hot_window_events = select_home_events(window_events)
    timeline_events = select_timeline_events(all_events)
    top_events = rank_hot_events(
        hot_window_events, limit=3, source_cap=2, reference_time=gen,
    )
    top_ids = [event["event_id"] for event in top_events]
    top_ranks = {event_id: rank for rank, event_id in enumerate(top_ids, 1)}
    payload["top"] = top_ids
    lite_enabled = lite_home_enabled()
    home_ranking = rank_timeline_events(
        timeline_events, page_size=DEFAULT_PAGE_SIZE,
        source_caps=FIRST_PAGE_SOURCE_CAPS, prevent_adjacent_sources=True,
    )
    home_first_page = home_ranking[:DEFAULT_PAGE_SIZE]
    lite_payload = build_lite_payload(
        all_events, payload["generated_at"], ranking=home_ranking, page_size=DEFAULT_PAGE_SIZE,
        source_badge_resolver=src_badge,
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

    # ── 详情页及其同源海报二维码 ──
    valid_qr_ids = write_qr_assets(all_events)
    valid_ids = write_detail_pages(
        all_events, css, tts_manifest=load_tts_manifest(), site_root=SITE,
    )
    if {Path(name).stem for name in valid_qr_ids} != {Path(name).stem for name in valid_ids}:
        raise RuntimeError("detail pages and local QR assets are inconsistent")
    print(f"[qr] 本地二维码 {len(valid_qr_ids)} 个")

    # ── Agent JSON Feed：供轮询器做增量、阈值与单条推送 ──
    agent_feed_payload = build_agent_feed(
        all_events, payload["generated_at"], site_base=SITE_BASE,
    )
    agent_feed_errors = validate_agent_feed(
        agent_feed_payload, site_base=SITE_BASE, site_root=SITE,
    )
    if agent_feed_errors:
        raise RuntimeError(f"invalid Agent feed: {', '.join(agent_feed_errors[:10])}")
    agent_feed_path = SITE / "data" / "agent-feed.json"
    agent_feed_path.write_bytes(
        (json.dumps(agent_feed_payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    )
    print(f"[agent-feed] schema v1 校验通过：{len(agent_feed_payload['events'])} 条")

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
    (SITE / "topics.html").write_text(
        render_topics_map(qualified_events, css, reference_time=gen), encoding="utf-8",
    )
    valid_topic_slugs = set()
    for t in TOPICS_META:
        if any(t["name"] in e.get("topics", []) for e in qualified_events):
            valid_topic_slugs.add(t["slug"] + ".html")
            (TOPIC_DIR / (t["slug"] + ".html")).write_text(
                render_topic_page(t, qualified_events, css, reference_time=gen), encoding="utf-8",
            )
    for f in TOPIC_DIR.glob("*.html"):
        if f.name not in valid_topic_slugs:
            f.unlink()

    # ── 时间轴 ──
    initial_events = home_first_page if lite_enabled else home_ranking
    days = defaultdict(list)
    for e in initial_events:
        timestamp = event_timestamp(e)
        if timestamp:
            days[timestamp.astimezone(TZ).date()].append(e)
    timeline = ""
    today = gen.astimezone(TZ).date()
    for d in sorted(days, reverse=True):
        head = f'{d.month}月{d.day}日'
        visible_head = f'今天 · {head}' if d == today else head
        info = f'星期{WEEK_CN[d.weekday()]} · {len(days[d])} 个事件'
        timeline += (f'<div class="day" data-day-key="{d.isoformat()}"><div class="day-head">'
                     f'<span class="date" data-date-base="{head}">{visible_head}</span>'
                     f'<span class="info">{info}</span></div>')
        timeline += "\n".join(
            render_card(e, top_rank=top_ranks.get(e["event_id"])) for e in days[d]
        )
        timeline += "</div>"

    # ── 厂商热榜 ──
    vendor_count = defaultdict(int)
    for e in hot_window_events:
        for v in e.get("vendors", []):
            vendor_count[v] += 1
    vrows = "".join(
        f'<a class="vendor-row" href="index.html?q={quote(v, safe="")}" '
        f'aria-label="查看 {esc(v)} 的相关事件"><span class="n">{n}</span>'
        f'<span>{esc(v)}</span><span class="count">{c} 条</span></a>'
        for n, (v, c) in enumerate(sorted(vendor_count.items(), key=lambda x: -x[1])[:8], 1))
    if not vrows:
        vrows = '<div style="font-size:12.5px;color:var(--sub)">暂无数据</div>'

    # 首页筛选顺序保持稳定；短名称只用于显示，底层筛选值继续兼容旧 URL。
    topic_fchips = render_home_filter_chips(timeline_events)
    weekly_teaser = render_weekly_brief_teaser(weekly_brief) if weekly_enabled else ""
    weekly_header_link = f'<a class="tab d-only" href="weekly.html" style="text-decoration:none">{ic("calendar",14)} 周报</a>' if weekly_enabled else ""
    home_config = (
        f'<meta id="homeDataConfig" data-lite-url="data/latest-lite.json" '
        f'data-page-size="{DEFAULT_PAGE_SIZE}" data-total="{len(timeline_events)}" '
        f'data-top-ids="{esc(",".join(top_ids))}">'
        if lite_enabled else ""
    )
    timeline_html = f'<div id="timeline">{timeline}</div>' if lite_enabled else timeline
    load_more = (
        f'<button class="load-more" id="loadMore" type="button" '
        f'{"hidden" if len(timeline_events) <= DEFAULT_PAGE_SIZE else ""}>'
        f'加载更多（{len(home_first_page)}/{len(timeline_events)}）</button>'
        if lite_enabled else ""
    )
    home_asset = '<script defer src="home.js"></script>'

    page = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>DataHot · 数据领域 AI 热榜</title>
<meta name="description" content="监控 Data Agent、AI 数据平台、BI、数据产品、AI分析五个领域的资讯热榜，多信源聚簇 + AI 中文摘要与推荐理由，每 6 小时更新。">
<meta property="og:title" content="DataHot · 数据领域 AI 热榜">
<meta property="og:description" content="Data Agent / AI 数据平台 / BI / 数据产品 / AI分析的热点，每 6 小时自动更新。">
<meta property="og:type" content="website">
<meta property="og:url" content="{SITE_BASE}/">
<meta property="og:site_name" content="DataHot · 数据领域 AI 热榜">
<meta name="twitter:card" content="summary">
<link rel="canonical" href="{SITE_BASE}/">
<link rel="icon" href="favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="icons/favicon-32.png">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<link rel="manifest" href="icons/manifest.json">
<meta name="theme-color" content="#1a1d23">
{feed_discovery()}
{analytics_head("")}
{favorites_head("")}
{home_config}
{home_asset}
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="DataHot">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<style>{css}
{SHARED_CSS}
#ptr{{position:fixed;top:0;left:0;right:0;height:0;overflow:hidden;display:flex;align-items:flex-end;justify-content:center;background:var(--bg);z-index:60;transition:height .12s ease-out}}
#ptr span{{font-size:12.5px;color:var(--sub);padding-bottom:8px}}
</style></head><body class="has-sb home-page" data-page="home">
{sidebar("home", gen)}
<div id="ptr"><span>下拉刷新</span></div>
<header class="home-header"><div class="wrap nav">
  {render_home_brand_update(gen)}
  {weekly_header_link}
  <a class="tab d-only" href="topics.html" style="text-decoration:none">{ic("map",14)} 主题</a>
  <a class="tab d-only" href="sources.html" style="text-decoration:none">{ic("rss",14)} 信源</a>
</div></header>

<div class="wrap"><div class="layout"><main>
  {weekly_teaser}
  {render_today_hot(top_events)}
  {render_timeline_toolbar(len(timeline_events))}
  <div class="chiprow" id="chiprow" role="group" aria-label="筛选时间轴">
    <button class="fchip on" type="button" aria-pressed="true" data-topic="all">全部</button>
    {topic_fchips}
  </div>
  {timeline_html}
  {load_more}
</main>

<aside>
  <div class="card vendor-rank-card"><h4 class="vendor-card-head"><span class="vendor-card-title">{ic("building")} 厂商榜 <span style="font-size:11px;color:var(--sub);font-weight:400">近7天</span></span><a class="vendor-card-link" href="sources.html">全部信源 →</a></h4>{vrows}</div>
</aside>
</div></div>

<footer>DataHot，数据领域AI资讯分享 · <a href="privacy.html">隐私</a> · <a href="https://github.com/henryhb1105-arch/datahot" target="_blank" rel="noopener noreferrer" style="color:var(--sub);text-decoration:underline">GitHub 开源</a> · {BLUESKY_FOOTER_LINK}</footer>
<button id="backToTop" class="back-to-top" type="button" aria-label="回到顶部" title="回到顶部" aria-hidden="true" tabindex="-1"><span aria-hidden="true">↑</span></button>
{tabbar("home")}

<script>
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
  document.querySelectorAll('#chiprow .fchip').forEach(x=>{{x.classList.remove('on');x.setAttribute('aria-pressed','false');}});
  if(!wasOn&&c.dataset.topic!=='all'){{
    c.classList.add('on');
    c.setAttribute('aria-pressed','true');
    const t=c.dataset.topic;
    applyFilter(el=>(el.dataset.topics||'').split('|').includes(t));
  }}else{{
    document.querySelector('[data-topic="all"]').classList.add('on');
    document.querySelector('[data-topic="all"]').setAttribute('aria-pressed','true');
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
    (SITE / "hot.html").write_text(
        render_hot_page(hot_window_events, css, reference_time=gen), encoding="utf-8",
    )
    favorite_data_url = "data/latest-lite.json" if lite_enabled else "data/latest.json"
    (SITE / "favorites.html").write_text(render_favorites_page(css, favorite_data_url), encoding="utf-8")
    (SITE / "for-me.html").write_text(render_for_me_page(css, favorite_data_url), encoding="utf-8")
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
                canonical_path=f"weekly/{filename}",
            ),
            encoding="utf-8",
        )
    for weekly_path in WEEKLY_DIR.glob("*.html"):
        if weekly_path.name not in valid_weekly_pages:
            weekly_path.unlink()
    (SITE / "privacy.html").write_text(render_privacy_page(css), encoding="utf-8")
    (SITE / "agent.html").write_text(
        page_shell(
            "接入 Agent · DataHot",
            "安装 DataHot Skill，让支持 Skills 的 Agent 持续读取最新数据与 AI 资讯。",
            css + AGENT_PAGE_CSS,
            render_agent_body(),
            tabbar("agent"),
            active="agent",
            canonical_path="agent.html",
        ),
        encoding="utf-8",
    )
    publish_skill_bundle(ROOT / "skills" / "datahot-news", SITE / "datahot-skill")

    out = SITE / "index.html"
    out.write_text(page, encoding="utf-8")
    sitemap_paths = public_sitemap_paths(
        valid_ids, valid_topic_slugs, valid_weekly_pages,
        weekly_enabled=weekly_enabled,
    )
    sitemap_count = write_search_discovery(SITE, sitemap_paths, site_base=SITE_BASE)
    print(f"[seo] sitemap.xml + robots.txt 校验通过：{sitemap_count} 个规范 URL")
    indexnow_key = write_indexnow_key_file(SITE)
    print(f"[seo] IndexNow 域名验证文件校验通过：{indexnow_key.name}")
    broken = check_site_links(SITE)
    if broken:
        print(f"[links] 构建失败：发现 {len(broken)} 个失效本地引用")
        print(format_broken_links(broken, SITE))
        raise RuntimeError("generated site contains broken local links")
    print("[links] 本地 href/src 100% 有效")
    print(f"[render] 首页 ({len(page.encode('utf-8')):,} B) + 详情页 {len(valid_ids)} 个")

if __name__ == "__main__":
    main()
