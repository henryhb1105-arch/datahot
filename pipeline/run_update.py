#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DataHot 更新管道 V1.1
采集 RSS/HN → 正文抓取(HN) → LLM 加工(过滤·摘要·推荐理由) → 事件聚簇 → latest.json
用法：python3 run_update.py
LLM 配置：环境变量 LLM_API_KEY/LLM_BASE_URL/LLM_MODEL 优先，其次 pipeline/config.json
"""
import json, os, re, sys, html, socket, hashlib, urllib.request, urllib.error, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from llm_usage import LLMBudgetExceeded, LLMUsageTracker
from candidate_cache import CandidateCache, candidate_content_hash
from cluster_cache import ClusterDecisionCache, cluster_pair_key
from content_blocks import (
    apply_translations, blocks_plain_text,
    parse_html_blocks_with_report, sanitize_blocks, translation_nodes,
    strip_article_ui_chrome, strip_article_ui_text, trim_article_blocks,
)
from media_cache import (
    MEDIA_CACHE_POLICY_VERSION, RETRYABLE_MEDIA_REASONS,
    cache_event_media, prune_media_cache, same_site_media,
)
from weekly_brief import generate_weekly_brief
from source_controls import (
    accepted_categories_by_source, prefilter_entries, source_candidate_limit,
    source_control_snapshot, source_due,
)
from taxonomy import CATEGORY_LABELS, normalize_category_label, normalize_category_labels
from work_tags import (
    TAXONOMY_VERSION as WORK_TAGS_VERSION,
    merge_work_tags, normalize_work_tags, prompt_instructions as work_tag_prompt,
)
from lite_data import (
    DEFAULT_PAGE_SIZE, FIRST_PAGE_SOURCE_CAPS, rank_hot_events,
    rank_timeline_events,
)
from release_policy import should_retain_event

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DATA = SITE / "data"
ARCHIVE = DATA / "archive"
KEEP_DAYS = 7
EVENT_RETENTION_DAYS = 8  # 保留完整上周，供周一 08:17 生成周报；首页仍只展示近 7 天。
PER_SOURCE_MAX = 20
TZ = timezone(timedelta(hours=8))
LLM_USAGE = LLMUsageTracker(DATA / "llm_usage.json")
CANDIDATE_CACHE = CandidateCache(DATA / "candidate_cache.json")
CLUSTER_CACHE = ClusterDecisionCache(DATA / "cluster_cache.json")
CONTENT_BLOCKS_PROCESSOR_VERSION = "original-first-v7"
ARTICLE_UI_SANITIZER_VERSION = "article-chrome-v3"
TRANSLATION_RETRY_POLICY_VERSION = "faithful-translation-retry-v1"
METADATA_TRANSLATION_POLICY_VERSION = "metadata-translation-backfill-v1"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
      "Accept": "application/rss+xml,application/xml,text/xml,*/*"}

socket.setdefaulttimeout(20)

CATEGORIES_LABEL = CATEGORY_LABELS

TOPICS_META = json.load(open(Path(__file__).resolve().parent / "topics.json"))
TOPIC_NAMES = [t["name"] for t in TOPICS_META]

VENDOR_TAGS = {
    "Databricks Blog": ["Databricks"], "dbt Blog": ["dbt Labs"],
    "ThoughtSpot Blog": ["ThoughtSpot"], "Metabase Blog": ["Metabase"],
    "ClickHouse Blog": ["ClickHouse"], "AWS Big Data Blog": ["AWS"],
    "Fivetran Blog": ["Fivetran"], "StarRocks Blog": ["StarRocks"],
    "Snowflake Engineering（Medium）": ["Snowflake"], "帆软": ["帆软", "FineBI"],
    "Aloudata 动态": ["Aloudata"], "Aloudata 博客": ["Aloudata"],
    "Snowflake Release Notes": ["Snowflake"], "OpenAI News": ["OpenAI"],
    "Claude 官方博客": ["Anthropic", "Claude"],
    "Anthropic Economic Index": ["Anthropic", "Claude"],
    "Indeed Hiring Lab": ["Indeed"], "AIHR": ["AIHR"],
    "Handshake Network Trends": ["Handshake"],
    "Microsoft Power BI（Power Platform Blog）": ["Microsoft", "Power BI"],
    "Tableau Engineering（Medium）": ["Tableau"],
    "Google BigQuery Release Notes": ["Google", "BigQuery"],
    "Google Looker Release Notes": ["Google", "Looker"],
    "Google Cloud Data Analytics Blog": ["Google", "Google Cloud"],
    "Microsoft Fabric Blog": ["Microsoft", "Fabric", "Power BI"],
    "Visier Blog": ["Visier"],
    "DuckDB Engineering Blog": ["DuckDB"],
    "Apache Iceberg Blog": ["Apache Iceberg"],
    "TiDB Blog": ["PingCAP", "TiDB"],
    "Apache Doris Blog": ["Apache Doris"],
}

# ── 基础工具 ──────────────────────────────────────────────
def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return html.unescape(re.sub(r"\s+", " ", s)).strip()

def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:  # ISO 8601（含毫秒/Z 后缀）
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y",
    ):
        try:
            dt = datetime.strptime(s[:25], fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None

def norm_url(u):
    """URL 归一化：去跟踪参数/hash/末尾斜杠，用于同链接去重"""
    p = urllib.parse.urlparse(u.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
         if not k.lower().startswith(("utm_", "ref", "fbclid", "gclid"))]
    return urllib.parse.urlunparse((p.scheme.lower(), p.netloc.lower(),
                                    p.path.rstrip("/"), "", urllib.parse.urlencode(q), ""))

def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def fetch_feed(url):
    raw = fetch_url(url)
    # 修复裸 & 和未声明的 HTML 实体（如 &nbsp;），否则 XML 解析失败
    raw = re.sub(rb'&(?!amp;|lt;|gt;|quot;|apos;|#)', b'&amp;', raw)
    for ent, ch in [(b"&amp;nbsp;", " "), (b"&amp;mdash;", "—"), (b"&amp;ndash;", "–"),
                    (b"&amp;hellip;", "…"), (b"&amp;lsquo;", "'"), (b"&amp;rsquo;", "'"),
                    (b"&amp;ldquo;", """), (b"&amp;rdquo;", """), (b"&amp;middot;", "·")]:
        raw = raw.replace(ent, ch.encode("utf-8"))
    return ET.fromstring(raw)

def text_of(el, *names):
    for n in names:
        c = el.find(n)
        if c is not None and c.text:
            return c.text
        for child in el:
            if child.tag.split("}")[-1] == n and child.text:
                return child.text
    return ""


def rich_html_of(el, *names):
    """Return the first rich feed field without stripping its HTML structure."""
    wanted = [str(name).split("}")[-1] for name in names]
    for name in wanted:
        for child in el:
            if child.tag.split("}")[-1] != name:
                continue
            if child.text:
                return child.text.strip()
            serialized = "".join(ET.tostring(grandchild, encoding="unicode") for grandchild in child)
            # Atom XHTML content is commonly namespace-prefixed after ElementTree
            # serialization.  Strip only tag prefixes/namespace declarations so
            # the local HTML parser can still recognize p/table/figure/img tags.
            serialized = re.sub(r"(<\/?)[A-Za-z_][\w.-]*:", r"\1", serialized)
            serialized = re.sub(r"\s+xmlns(?::[\w.-]+)?=([\"']).*?\1", "", serialized)
            if serialized.strip():
                return serialized.strip()
    return ""

def parse_feed(root_el, source):
    items = []
    for it in root_el.iter("item"):
        rich_content = rich_html_of(it, "encoded", "content", "description", "summary")
        items.append({
            "title": strip_html(text_of(it, "title")),
            "link": text_of(it, "link").strip(),
            "published": parse_date(text_of(it, "pubDate", "published", "updated", "date")),
            "summary": strip_html(rich_content or text_of(it, "description", "summary", "encoded")),
            "feed_content_html": rich_content,
        })
    ns = "{http://www.w3.org/2005/Atom}"
    for it in root_el.iter(ns + "entry"):
        link = ""
        for l in it.iter(ns + "link"):
            if l.get("href") and (l.get("rel") in (None, "alternate")):
                link = l.get("href"); break
        rich_content = rich_html_of(it, "content", "summary")
        items.append({
            "title": strip_html(text_of(it, ns + "title")),
            "link": link,
            "published": parse_date(text_of(it, ns + "published", ns + "updated")),
            "summary": strip_html(rich_content or text_of(it, ns + "summary", ns + "content")),
            "feed_content_html": rich_content,
        })
    return [i for i in items if i["title"] and i["link"]][:PER_SOURCE_MAX]

import math

FRESHNESS_HALF_LIFE_HOURS = 48


def freshness(published, reference_time=None):
    """时间新鲜度 0~1：按真实发布时间以 48 小时为半衰期降温。"""
    if not published:
        return 0.5
    now = reference_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_h = max(
        0,
        (now.astimezone(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 3600,
    )
    return 2 ** (-age_h / FRESHNESS_HALF_LIFE_HOURS)

def community_score(signal):
    """社区信号（HN 赞数 / Bluesky 赞数）对数归一到 0-100，1000 赞 ≈ 满分"""
    if not signal or signal <= 0:
        return 0
    return min(100, round(math.log1p(signal) / math.log1p(1000) * 100))


def _trend_points(published=None, signal=0, extra_sources=0, reference_time=None):
    """Return the legacy 55-point non-quality portion of the heat formula."""
    multi = min(10, 4 * max(0, int(extra_sources or 0)))
    comm = min(10, 0.1 * community_score(signal))
    fresh = 0.35 * freshness(published, reference_time=reference_time) * 100
    return fresh + comm + multi


def calc_trend_score(published=None, signal=0, extra_sources=0, reference_time=None):
    """Recent attention score 0~100, independent from editorial quality."""
    return round(min(100, _trend_points(
        published, signal, extra_sources, reference_time=reference_time,
    ) / 0.55))

def calc_heat(
    importance=50, published=None, signal=0, extra_sources=0,
    reference_time=None,
):
    """兼容综合分：内容质量45% + 独立趋势分55%。

    保持 heat 3.0 的数值语义不变，但把可解释的 quality_score 与
    trend_score 分开持久化，避免把“好”“火”“适合我”混成一个信号。
    """
    return round(min(
        100,
        0.45 * max(0, min(100, int(importance or 0)))
        + _trend_points(
            published, signal, extra_sources, reference_time=reference_time,
        ),
    ))

# ── F5：HN 条目抓原文 ──────────────────────────────────────
def extract_meta_date(html_txt):
    """从 HTML meta/JSON-LD/time 标签提取文章真实发布时间"""
    for pat in (r'property="article:published_time" content="([^"]+)',
                r'"datePublished"\s*:\s*"([^"]+)',
                r'name="date" content="([^"]+)',
                r'itemprop="datePublished"[^>]*content="([^"]+)',
                r'<time[^>]*datetime="([^"]+)"'):
        m = re.search(pat, html_txt)
        if m:
            dt = parse_date(m.group(1)[:30])
            if dt and 2005 <= dt.year <= 2100:
                return dt
    return None

def fetch_article_content(url, max_chars=120000, *, include_report=False):
    """提取安全结构化 blocks，同时保留纯文本兼容输出和可选诊断。"""
    empty_report = {
        "strategy": "fetch_failed", "blocks": 0, "text_chars": 0,
        "figures": 0, "tables": 0, "figures_discovered": 0,
        "figures_selected": 0, "figures_rejected": 0,
    }

    def result(text="", title="", pub_date=None, blocks=None, report=None):
        base = (text, title, pub_date, blocks or [])
        return (*base, report or dict(empty_report)) if include_report else base

    try:
        raw = fetch_url(url, timeout=10)
        try:
            html_txt = raw.decode("utf-8", errors="ignore")
        except Exception:
            return result()
        title = ""
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_txt)
        if m:
            title = strip_html(m.group(1))
            title = re.split(r"[|｜_-]{1,2}\s*(?:Aloudata|官网|博客).*$", title)[0].strip() or title
        pub_date = extract_meta_date(html_txt)
        blocks, parse_report = parse_html_blocks_with_report(html_txt, url)
        no_image_index = False
        for meta_tag in re.findall(r"(?is)<meta\b[^>]*>", html_txt):
            name_match = re.search(r"(?i)\bname\s*=\s*['\"]([^'\"]+)['\"]", meta_tag)
            content_match = re.search(r"(?i)\bcontent\s*=\s*['\"]([^'\"]+)['\"]", meta_tag)
            if (
                name_match and content_match
                and name_match.group(1).strip().casefold() in {"robots", "googlebot"}
                and "noimageindex" in content_match.group(1).casefold()
            ):
                no_image_index = True
                break
        if no_image_index:
            for block in blocks:
                if block.get("type") == "figure":
                    block["media_reason"] = "rights_restricted"
            parse_report["noimageindex"] = True
        text = blocks_plain_text(blocks)
        structural = any(block.get("type") in {"figure", "table"} for block in blocks)
        quality_passed = parse_report.get("quality_status", "pass") == "pass"
        meaningful = quality_passed and (
            len(text) > 400 or (len(text) >= 120 and structural)
        )
        if not meaningful:
            fallback = re.sub(r"(?is)<(script|style|noscript|nav|footer|header)[^>]*>.*?</\1>", " ", html_txt)
            text = strip_html(fallback)
            blocks = []
            parse_report["fallback_reason"] = (
                "content_quality_suspect" if not quality_passed
                else "structured_body_too_short"
            )
        # A whole-page text dump mixes navigation, recommendations and footers and
        # produces the exact "乱糟糟" detail page we want to avoid.  Treat it as
        # unavailable unless the structured extractor found a meaningful article.
        usable_text = text[:max_chars] if meaningful else ""
        return result(usable_text, title, pub_date, blocks, parse_report)
    except Exception as exc:
        report = dict(empty_report)
        report["error"] = type(exc).__name__
        return result(report=report)


def fetch_article_text(url, max_chars=120000):
    """兼容旧调用方：返回 (正文, 标题, meta 发布日期)。"""
    text, title, pub_date, _blocks = fetch_article_content(url, max_chars=max_chars)
    return text, title, pub_date


def prefer_rss_article_content(text, blocks, report, feed_html, article_url):
    """Prefer a full RSS body when it is at least as useful as the web page body."""
    feed_html = str(feed_html or "").strip()
    if not feed_html:
        return text, blocks, report
    feed_blocks, feed_report = parse_html_blocks_with_report(feed_html, article_url)
    feed_text = blocks_plain_text(feed_blocks)
    feed_structural = sum(
        block.get("type") in {"heading", "list", "blockquote", "code", "table", "figure"}
        for block in feed_blocks
    )
    page_structural = sum(
        block.get("type") in {"heading", "list", "blockquote", "code", "table", "figure"}
        for block in blocks
    )
    feed_score = len(feed_text) + feed_structural * 120
    page_score = len(text) + page_structural * 120
    feed_quality_passed = feed_report.get("quality_status", "pass") == "pass"
    if (
        feed_quality_passed and len(feed_text) >= 400
        and (not text or feed_score >= page_score * 0.9)
    ):
        selected_report = dict(feed_report)
        selected_report["strategy"] = "rss_" + str(feed_report.get("strategy") or "content")
        return feed_text, feed_blocks, selected_report
    return text, blocks, report

# ── LLM 配置 ──────────────────────────────────────────────
def load_llm_config():
    key, base, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_BASE_URL"), os.getenv("LLM_MODEL")
    cfg_path = Path(__file__).resolve().parent / "config.json"
    if cfg_path.exists():
        cfg = json.load(open(cfg_path))
        key = key or cfg.get("LLM_API_KEY", "")
        base = base or cfg.get("LLM_BASE_URL", "")
        model = model or cfg.get("LLM_MODEL", "")
    return key, base, model

def parse_llm_json_content(content, *, strict_object=False):
    """Parse one model JSON response; weekly stages reject wrapper text."""
    text = str(content or "").strip()
    if strict_object:
        if not text.startswith("{") or not text.endswith("}"):
            raise ValueError("strict JSON response must contain one bare object")
        value = json.loads(text, strict=False)
    else:
        match = re.search(r"\{.*\}", text, re.S)
        value = json.loads(match.group(0), strict=False) if match else {}
    if not isinstance(value, dict):
        raise ValueError("LLM JSON response must be an object")
    return value


def llm_chat(base, key, model, prompt, timeout=120, max_tokens=None,
             purpose="other", source="", item_id="", strict_object=False):
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if strict_object:
        # DeepSeek V4 defaults to thinking mode, whose reasoning tokens can
        # exhaust max_tokens before ``message.content`` is emitted. Weekly
        # stages need a compact machine-readable result, so request the
        # provider's native JSON mode and explicitly disable thinking.
        payload["response_format"] = {"type": "json_object"}
        payload["thinking"] = {"type": "disabled"}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    estimated_tokens = max(512, len(prompt) // 3 + int(max_tokens or 2048))
    reservation = LLM_USAGE.before_call(
        purpose=purpose, item_id=item_id, estimated_tokens=estimated_tokens,
    )
    response, content = {}, ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            response = json.loads(r.read())
        content = response["choices"][0]["message"]["content"]
        result = parse_llm_json_content(content, strict_object=strict_object)
        LLM_USAGE.record(
            model=model, purpose=purpose, source=source, item_id=item_id,
            prompt_chars=len(prompt), response_chars=len(content), max_tokens=max_tokens,
            usage=response.get("usage"), success=True, reserved_tokens=reservation,
        )
        return result  # strict=False 容忍编译稿中的原始换行
    except Exception as exc:
        LLM_USAGE.record(
            model=model, purpose=purpose, source=source, item_id=item_id,
            prompt_chars=len(prompt), response_chars=len(content), max_tokens=max_tokens,
            usage=response.get("usage"), success=False, error_type=type(exc).__name__,
            reserved_tokens=reservation,
        )
        raise


def generate_weekly_brief_for_events(
    events, cfg, now, *, cache_path=None, output_path=None, archive_dir=None,
):
    """Generate the completed week's immutable brief before other paid work."""
    enabled_value = os.getenv(
        "WEEKLY_BRIEF_ENABLED", os.getenv("DAILY_BRIEF_ENABLED", "true"),
    )
    enabled = enabled_value.strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return None, "disabled"
    key, base, model = cfg
    configured_model = model if key and base and model else ""

    def call(prompt, *, item_id):
        source = "weekly_signals" if ":signals" in item_id else "weekly_personal"
        return llm_chat(
            base, key, model, prompt, max_tokens=3600, strict_object=True,
            purpose="weekly_brief", source=source, item_id=item_id,
        )

    force_value = os.getenv(
        "WEEKLY_BRIEF_FORCE", os.getenv("DAILY_BRIEF_FORCE", "false"),
    )
    force_requested = force_value.strip().lower() in {"1", "true", "yes", "on"}
    # A forgotten repository variable must not turn four scheduled runs into
    # four paid regenerations. Forced replacement is manual-dispatch only.
    force = force_requested and os.getenv("GITHUB_EVENT_NAME", "") == "workflow_dispatch"
    return generate_weekly_brief(
        events,
        now=now,
        model=configured_model,
        llm_generate=call if configured_model else None,
        cache_path=cache_path or DATA / "weekly_brief_cache.json",
        output_path=output_path or DATA / "weekly_brief.json",
        archive_dir=archive_dir or DATA / "weekly",
        force=force,
    )

# ── 全文编译引擎（忠实编译，非摘要）─────────────────────────
COMPILE_RULES = """你是数据领域垂直资讯站的专业编译。把下面的原文编译为面向数据从业者的中文全文编译稿。要求：
1. 完整保留原文的信息、论证过程、关键事实、案例、数据、步骤与结论；不随意省略关键段落、数字、人物、公司、产品与技术细节。
2. 保留原文的结构与逻辑顺序，用「## 」开头的小标题和自然段呈现（小标题据原文标题直译或概括）。
3. 这是全文编译，不是摘要：目标长度约为原文的 40%-70%，宁可长也不可漏。
4. 严格忠于原文，不得编造、补写或评论。若某处原文无法读取或不完整，用【此处原文未能完整读取】标注，不得自行补写。
5. 原文中的导航、订阅框、相关阅读推荐等网页杂质，直接忽略。
只输出编译稿正文（纯文本，段落间两个换行，小标题以「## 」开头）。"""

def compile_fulltext(title, source_text, cfg, *, context=None):
    """忠实编译：短文单遍，长文按段落分块编译后拼接"""
    key, base, model = cfg
    if not (key and base and model and source_text):
        return ""
    context = context or {}
    call_context = {
        "purpose": "compile",
        "source": context.get("source", ""),
        "item_id": context.get("item_id", ""),
    }
    src = source_text[:22000]
    if len(src) <= 6000:
        try:
            return llm_chat_text(base, key, model,
                COMPILE_RULES + "\n\n【原文标题】" + title + "\n\n" + src,
                max_tokens=6000, **call_context)
        except LLMBudgetExceeded as exc:
            print(f"[budget] 跳过全文编译: {title[:40]} | {exc}")
            return ""
    # 按句子边界切块（抓取文本无换行，按句号边界切 ≤3500 字符/块，最多 6 块）
    sents = re.split(r"(?<=[。！？.!?])\s+", src)
    chunks, cur = [], ""
    for sent in sents:
        if len(cur) + len(sent) > 3500 and cur:
            chunks.append(cur)
            if len(chunks) >= 6:
                break
            cur = sent
        else:
            cur = (cur + " " + sent) if cur else sent
    if cur and len(chunks) < 6:
        chunks.append(cur)
    def compile_chunk(i_ch):
        i, ch = i_ch
        for attempt in range(2):  # 空输出（推理预算耗尽）时重试一次
            try:
                part = llm_chat_text(base, key, model,
                COMPILE_RULES + f"\n\n注意：这是文章的第 {i}/{len(chunks)} 部分，只编译本部分的可见内容；若开头或结尾句子被切断，编译可见部分即可，不得补写上下文。\n\n【原文标题】" + title + "\n\n" + ch,
                max_tokens=8000, **call_context)
            except LLMBudgetExceeded as exc:
                print(f"[budget] 跳过全文分块 {i}/{len(chunks)}: {title[:30]} | {exc}")
                return ""
            if part.strip():
                return part.strip()
        return ""
    from concurrent.futures import ThreadPoolExecutor as _TPE
    with _TPE(max_workers=4) as pool:
        parts = list(pool.map(compile_chunk, enumerate(chunks, 1)))
    if len(cur) > len(chunks[-1] if chunks else "") and len(chunks) >= 6:
        parts.append("【此处原文未能完整读取：文章过长，仅编译前 6 部分】")
    return "\n\n".join(p for p in parts if p)

def llm_chat_text(base, key, model, prompt, max_tokens=4096,
                  purpose="other", source="", item_id=""):
    """纯文本版 LLM 调用（编译稿不走 JSON 解析）"""
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                         "max_tokens": max_tokens}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    estimated_tokens = max(512, len(prompt) // 3 + int(max_tokens or 4096))
    reservation = LLM_USAGE.before_call(
        purpose=purpose, item_id=item_id, estimated_tokens=estimated_tokens,
    )
    response, content = {}, ""
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            response = json.loads(r.read())
        content = response["choices"][0]["message"]["content"].strip()
        LLM_USAGE.record(
            model=model, purpose=purpose, source=source, item_id=item_id,
            prompt_chars=len(prompt), response_chars=len(content), max_tokens=max_tokens,
            usage=response.get("usage"), success=True, reserved_tokens=reservation,
        )
        return content
    except Exception as exc:
        LLM_USAGE.record(
            model=model, purpose=purpose, source=source, item_id=item_id,
            prompt_chars=len(prompt), response_chars=len(content), max_tokens=max_tokens,
            usage=response.get("usage"), success=False, error_type=type(exc).__name__,
            reserved_tokens=reservation,
        )
        raise

# ── F4：加固的相关性过滤 + AI 加工 ─────────────────────────
ENRICH_RULES = """你是一个数据领域垂直资讯站的编辑。本站只覆盖五个领域：Data Agent（ChatBI/Text-to-SQL/分析Agent）、AI数据平台（数仓/湖仓/语义层/数据集成治理）、BI与可视化（BI工具/报表）、数据产品（方法论/融资并购/行业报告）、AI分析（用AI或数据分析回答明确业务问题，并形成可用于决策的发现）。

【相关性硬规则】
- 注意：dbt 仅指数据工具 dbt Labs/getdbt；心理疗法 DBT（辩证行为疗法、skills-based treatment 等语境）一律 false
- 反例：推荐 flaminghydra.com 上 Kate Wagner 关于 dbt 的文章——那是心理疗法内容，relevant=false
- 仅当内容直接涉及上述领域时 relevant=true
- 泛AI新闻一律 false：AI消费应用、AI硬件、AI政策八卦、模型发布（与数据场景无关）、AI音乐/绘画/社交等
- 数据分析/数据库/数据基础设施的融资并购、产品发布、技术实践 → true

【AI分析分类边界】
- 只有同时具备以下四项才归入 insight：明确业务问题；有数据/分析/研究依据；给出具体发现或预测；说明可采取的决策或行动
- insight 关注业务问题本身，而不是某个工具的发布。若主语是产品发布、技术实现、融资并购或行业泛观点，仍归入 agent/platform/bi/product
- 只有“AI赋能”“智能洞察”等营销措辞，没有事实、指标、样本或分析过程，不得归入 insight
- insight 的 topics 优先从六个业务场景选 1-2 个：组织人才、财务经营、销售增长、客户运营、供应链、风险管理；原文没有直接支持时不要推测

【示例】
标题 "Databricks launches new semantic layer" → {"relevant": true, ...}
标题 "OpenAI 发布新款AI智能音箱" → {"relevant": false}
标题 "Airbnb 测试 AI 搜索功能" → {"relevant": false}
标题 "360万员工记录揭示AI转型中的技能断层，并给出人才配置建议" → {"relevant": true, "category": "insight", "topics": ["组织人才"], ...}
标题 "Tableau 发布一键生成洞察功能" → {"relevant": true, "category": "bi", ...}

【工作标签】
从下列封闭词表选择。只标记原文直接支持的对象、场景和决策关注；不得推测特定公司的内部需求。每个维度允许为空，宁缺毋滥：
""" + work_tag_prompt() + """

【内容质量】
质量与热度、个人兴趣分开判断。四项各给 0-25 分，并让 quality_score 等于四项之和：
- originality：是否为第一方发布、原创研究、原创技术实践或原始数据，而非转载拼接
- evidence_density：是否有数字、方法、代码、样本、图表或可核验事实
- information_gain：相对常识和营销口号是否提供了明确的新信息
- actionability_depth：是否讲清机制、边界和可采取的行动，而非只有结论

输出 JSON（不要输出多余内容）：
{"relevant": true或false, "zh_title": "中文标题(≤40字)", "zh_summary": "中文摘要3-4句，保留产品名与数字，不得编造原文没有的信息", "reason": "推荐理由：为什么数据从业者应关注，1-2句", "category": "agent|platform|bi|product|insight", "shelf": "news 或 evergreen（方法论/框架/深度实践/报告解读等半年后仍值得读的标 evergreen，发布/融资/版本更新等时效内容标 news）", "topics": ["从主题词表选0-2个：""" + "/".join(TOPIC_NAMES) + """，没有合适的就空数组，宁缺毋滥"], "work_tags": {"product_objects": [], "use_cases": [], "decision_concerns": []}, "vendors": ["提到的数据厂商，如Snowflake/Databricks/PowerBI/帆软等，没有则空数组"], "quality_breakdown": {"originality": 0-25整数, "evidence_density": 0-25整数, "information_gain": 0-25整数, "actionability_depth": 0-25整数}, "quality_score": 1-100整数, "importance": 与quality_score相同的兼容字段}"""

ENRICH_RULE_VERSION = f"enrich-v4-quality-split-{WORK_TAGS_VERSION}"
INSIGHT_ENRICH_RULE_VERSION = f"enrich-insight-v3-quality-split-{WORK_TAGS_VERSION}"
INSIGHT_FOCUS_SOURCES = frozenset({
    "爱分析", "Visier Blog", "Indeed Hiring Lab", "Josh Bersin",
    "AIHR", "Handshake Network Trends", "Anthropic Economic Index",
})
REVIEW_REQUIRED_TIERS = frozenset({"low_precision", "community_targeted", "media_low"})
QUALITY_DIMENSIONS = (
    "originality", "evidence_density", "information_gain", "actionability_depth",
)


def normalize_quality_result(output, fallback=50):
    """Return a bounded score and auditable 4x25 breakdown from model output."""
    raw = output.get("quality_breakdown") if isinstance(output, dict) else None
    breakdown = {}
    if isinstance(raw, dict) and all(name in raw for name in QUALITY_DIMENSIONS):
        for name in QUALITY_DIMENSIONS:
            try:
                breakdown[name] = max(0, min(25, int(raw.get(name, 0))))
            except (TypeError, ValueError):
                breakdown[name] = 0
    if len(breakdown) == len(QUALITY_DIMENSIONS):
        score = sum(breakdown.values())
    else:
        candidate = output.get("quality_score", output.get("importance", fallback))
        try:
            score = int(candidate)
        except (TypeError, ValueError):
            score = int(fallback or 50)
        breakdown = {}
    return max(1, min(100, score)), breakdown


def requires_editorial_review(item):
    """Low-precision/community candidates must pass enrichment to be public."""
    return str(item.get("source_tier") or "") in REVIEW_REQUIRED_TIERS


def _candidate_cache_context(it, model):
    rule_version = (
        INSIGHT_ENRICH_RULE_VERSION
        if it.get("source") in INSIGHT_FOCUS_SOURCES
        else ENRICH_RULE_VERSION
    )
    return {
        "normalized_url": norm_url(it["link"]),
        "source_id": it.get("source", "unknown"),
        "content_hash": candidate_content_hash(it),
        "model": model,
        "rule_version": rule_version,
    }


def _cached_enrichment(it, cached):
    enrichment = cached.get("enrichment") or {}
    for key in (
        "zh_title", "zh_summary", "reason", "category", "category_label",
        "vendors", "topics", "work_tags", "shelf", "importance", "quality_score",
        "quality_breakdown", "trend_score", "heat",
    ):
        if key in enrichment:
            it[key] = enrichment[key]
    normalize_category_label(it)
    quality, breakdown = normalize_quality_result(it, it.get("importance", 50))
    it["quality_score"] = quality
    it["importance"] = quality
    if breakdown:
        it["quality_breakdown"] = breakdown
    it["trend_score"] = calc_trend_score(
        it.get("_pub_dt"), it.get("signal", 0),
    )
    it["heat"] = calc_heat(quality, it.get("_pub_dt"), it.get("signal", 0))
    it["star"] = quality >= 75
    return it


def _cacheable_enrichment(it):
    return {
        key: it[key]
        for key in (
            "zh_title", "zh_summary", "reason", "category", "category_label",
            "vendors", "topics", "work_tags", "shelf", "importance", "quality_score",
            "quality_breakdown", "trend_score", "heat",
        )
        if key in it
    }

RULE_POSITIVE_TERMS = (
    "data", "database", "analytics", "warehouse", "lakehouse", "sql", "dashboard",
    "business intelligence", "semantic layer", "etl", "elt", "dbt", "agent", "数据", "分析", "数仓", "湖仓", "可视化",
    "语义层", "智能体", "数据产品", "报表", "people analytics", "workforce analytics",
    "workforce planning", "attrition", "turnover", "headcount", "talent intelligence",
    "recruiting analytics", "recruitment analytics", "talent acquisition", "compensation",
    "pay equity", "skills gap", "labor market", "labour market", "job postings",
    "organization design", "organisational design", "span of control", "employee engagement",
    "human resources", "hr analytics", "workforce productivity", "组织", "人才", "员工流失",
    "招聘", "薪酬", "人效", "组织效能", "人才盘点", "人才分析", "劳动力市场",
)
RULE_NEGATIVE_TERMS = (
    "smartphone", "gaming", "music generation", "image generation", "dating app",
    "手机", "游戏", "音乐生成", "绘画", "社交应用", "智能音箱",
)


def precheck_candidate_cache(items, cfg):
    """Apply persisted candidate decisions before deterministic rules or fetching."""
    _key, _base, model = cfg
    if not model:
        return items
    kept = []
    for it in items:
        context = _candidate_cache_context(it, model)
        cached = CANDIDATE_CACHE.lookup(**context)
        it["_cache_checked"] = True
        it["_cache_context"] = context
        if cached and cached.get("status") == "rejected":
            print(f"[cache] 已拒绝候选，跳过: {it['title'][:50]}")
            continue
        if cached and cached.get("status") == "error":
            print(f"[cache] 错误退避中，本轮跳过: {it['title'][:50]}")
            continue
        if cached and cached.get("status") == "accepted":
            it["_cache_entry"] = cached
        kept.append(it)
    return kept


def rule_prefilter_candidates(items):
    """Cheap, reversible high-recall filter before clustering and LLM calls."""
    kept = []
    for it in items:
        if it.get("_cache_entry") or it.get("vendor_default"):
            kept.append(it)
            continue
        text = " ".join(
            str(it.get(key) or "") for key in ("title", "summary", "link")
        ).casefold()
        if any(term in text for term in RULE_NEGATIVE_TERMS):
            print(f"[rules] 确定性排除: {it['title'][:50]}")
            continue
        if any(term in text for term in RULE_POSITIVE_TERMS):
            kept.append(it)
        else:
            print(f"[rules] 无数据领域信号: {it['title'][:50]}")
    return kept


EMPTY_SNOWFLAKE_RELEASE_MARKERS = (
    "no significant features, updates, or enhancements to announce",
    "release notes (no announcements)",
    "release notes — no announcements",
    "本次发布没有需要宣布的重大功能、更新或增强",
)


def is_empty_release_note(item):
    """Reject placeholder release-note pages that explicitly announce nothing."""
    if str(item.get("source") or "") != "Snowflake Release Notes":
        return False
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "summary", "article_text")
    ).casefold()
    text = " ".join(text.split())
    return any(marker in text for marker in EMPTY_SNOWFLAKE_RELEASE_MARKERS)


def llm_enrich(items, cfg, *, generate_fulltext=True):
    key, base, model = cfg
    meaningful = []
    for it in items:
        if is_empty_release_note(it):
            print(f"[rules] 空发布说明，剔除: {it['title'][:50]}")
            if model:
                context = it.get("_cache_context") or _candidate_cache_context(it, model)
                CANDIDATE_CACHE.remember(**context, status="rejected")
            continue
        meaningful.append(it)
    items = meaningful
    if not (key and base and model):
        safe = [item for item in items if not requires_editorial_review(item)]
        dropped = len(items) - len(safe)
        print(f"[llm] 未配置 LLM，跳过 AI 加工；低精度候选关闭 {dropped} 条")
        return safe

    def enrich_one(it):
        content = f"标题：{it['title']}\n摘要：{it['summary'][:800]}"
        if it.get("article_text"):
            content += f"\n原文：{it['article_text'][:2200]}"
        note = "\n（注：该条目来自数据领域厂商官方博客，默认相关，除非明显是招聘/活动/公关软文）" if it.get("vendor_default") else ""
        out = llm_chat(
            base, key, model, ENRICH_RULES + "\n\n" + content + note,
            purpose="enrich", source=it.get("source", ""), item_id=it.get("id", ""),
        )
        if out.get("relevant") is False:
            return None
        it["zh_title"] = out.get("zh_title") or it["title"]
        it["zh_summary"] = out.get("zh_summary") or it["summary"][:300]
        it["reason"] = out.get("reason", "")
        if generate_fulltext:
            it["full_zh"] = compile_fulltext(
                it["zh_title"], it.get("article_text") or it.get("summary", ""), cfg,
                context={"source": it.get("source", ""), "item_id": it.get("id", "")},
            )
        cat = out.get("category")
        if cat in CATEGORIES_LABEL:
            it["category"], it["category_label"] = cat, CATEGORIES_LABEL[cat]
        llm_vendors = [v for v in (out.get("vendors") or []) if isinstance(v, str) and v.strip()]
        it["vendors"] = list(dict.fromkeys(it.get("vendors", []) + llm_vendors))[:5]
        it["topics"] = [t for t in (out.get("topics") or []) if t in TOPIC_NAMES][:2]
        it["work_tags"] = normalize_work_tags(out.get("work_tags"))
        it["shelf"] = out.get("shelf") if out.get("shelf") in ("news", "evergreen") else "news"
        quality, breakdown = normalize_quality_result(out, 50)
        it["quality_score"] = quality
        it["importance"] = quality  # 兼容旧客户端和 Agent feed
        if breakdown:
            it["quality_breakdown"] = breakdown
        it["trend_score"] = calc_trend_score(
            it.get("_pub_dt"), it.get("signal", 0),
        )
        it["star"] = quality >= 75  # 精选只看内容质量，不看热度或信源出身
        it["heat"] = calc_heat(quality, it.get("_pub_dt"), it.get("signal", 0))
        return it

    kept, pending = [], []
    cache_contexts = {}
    for it in items:
        context = it.get("_cache_context") or _candidate_cache_context(it, model)
        cache_contexts[it["id"]] = context
        cached = it.get("_cache_entry")
        if not it.get("_cache_checked"):
            cached = CANDIDATE_CACHE.lookup(**context)
        if cached and cached.get("status") == "rejected":
            print(f"[cache] 已拒绝候选，跳过: {it['title'][:50]}")
            continue
        if cached and cached.get("status") == "accepted":
            kept.append(_cached_enrichment(it, cached))
            print(f"[cache] 已接受候选，复用判定: {it['title'][:50]}")
            continue
        if cached and cached.get("status") == "error":
            print(f"[cache] 错误退避中，本轮跳过: {it['title'][:50]}")
            continue
        pending.append(it)

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(enrich_one, it): it for it in pending}
        for fut, it in futures.items():
            context = cache_contexts[it["id"]]
            try:
                res = fut.result()
                if res is None:
                    print(f"[llm] 不相关，剔除: {it['title'][:50]}")
                    CANDIDATE_CACHE.remember(**context, status="rejected")
                else:
                    kept.append(res)
                    CANDIDATE_CACHE.remember(
                        **context, status="accepted", enrichment=_cacheable_enrichment(res),
                    )
            except Exception as e:
                fail_closed = requires_editorial_review(it)
                action = "关闭候选" if fail_closed else "保留原文"
                print(f"[llm] 加工失败（{action}）: {e} | {it['title'][:40]}")
                it["_enrich_error"] = type(e).__name__
                if not fail_closed:
                    kept.append(it)
                CANDIDATE_CACHE.remember(
                    **context, status="error", error_type=type(e).__name__,
                )
    return kept

# ── F1：事件聚簇 ──────────────────────────────────────────
def title_bigrams(t):
    t = re.sub(r"[^\w一-鿿]+", "", (t or "").lower())
    return {t[i:i+2] for i in range(len(t) - 1)} if len(t) > 1 else {t} if t else set()

def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

CLUSTER_RULE_VERSION = "cluster-v1"


def llm_same_event(pairs, cfg):
    """pairs: [(a_desc, b_desc), ...] → [bool]"""
    key, base, model = cfg
    if not (key and base and model):
        return [False] * len(pairs)
    def judge(p):
        try:
            pair_key = cluster_pair_key(p[0], p[1])
            cached = CLUSTER_CACHE.lookup(pair_key, CLUSTER_RULE_VERSION)
            if cached is not None:
                return cached
            pair_id = pair_key[:12]
            out = llm_chat(base, key, model,
                "判断以下两条资讯是否报道同一事件/同一产品发布（同一事件的不同媒体报道算同一事件）。"
                "注意：月度汇总/盘点类文章与其中提到的单项功能发布不算同一事件，除非该功能就是这篇文章的主题。"
                '只输出JSON {"same": true或false}。\n\n'
                f"【A】{p[0][:400]}\n【B】{p[1][:400]}",
                purpose="cluster", source="event-cluster", item_id=pair_id)
            same = out.get("same") is True
            CLUSTER_CACHE.remember(pair_key, CLUSTER_RULE_VERSION, same)
            return same
        except Exception:
            return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        return list(pool.map(judge, pairs))

def event_titles(e):
    """事件的所有标题变体（中文标题 + 各信源原始标题），用于跨语言相似度"""
    return [e.get("zh_title", "")] + [s.get("title", "") for s in e.get("items", [])]

def max_sim(a_titles, b_titles):
    best = 0.0
    for ta in a_titles:
        ba = title_bigrams(ta)
        for tb in b_titles:
            best = max(best, jaccard(ba, title_bigrams(tb)))
    return best


def _item_desc(it):
    return f"标题:{it.get('zh_title') or it.get('title','')} 摘要:{(it.get('zh_summary') or it.get('summary',''))[:200]}"


def _items_comparable(left, right, max_hours=72):
    left_vendors = set(left.get("vendors") or [])
    right_vendors = set(right.get("vendors") or [])
    if left_vendors & right_vendors:
        return True
    left_dt, right_dt = left.get("_pub_dt"), right.get("_pub_dt")
    if left_dt and right_dt:
        return abs((left_dt - right_dt).total_seconds()) <= max_hours * 3600
    return True


def group_candidate_items(items, cfg):
    """Cluster current-run metadata before article fetching or enrichment."""
    groups = []
    for item in items:
        candidates = []
        for group in groups:
            representative = group[0]
            if not _items_comparable(item, representative):
                continue
            similarity = max_sim(
                [item.get("title", "")],
                [member.get("title", "") for member in group],
            )
            if similarity > 0.3:
                candidates.append(group)
        if not candidates:
            groups.append([item])
            continue
        verdicts = llm_same_event(
            [(_item_desc(item), _item_desc(group[0])) for group in candidates], cfg
        )
        hit = next((group for group, same in zip(candidates, verdicts) if same), None)
        if hit is None:
            groups.append([item])
        else:
            hit.append(item)
    return groups


def select_primary_source(group, source_configs):
    """Select one deterministic primary before fetching or LLM metadata work."""
    tier_scores = {
        "structured_high": 100,
        "official_high": 80,
        "community_targeted": 45,
        "media_targeted": 40,
        "low_precision": 25,
        "media_low": 20,
    }
    def score(item):
        config = source_configs.get(item.get("source", ""), {})
        return (
            tier_scores.get(config.get("tier", "default"), 30)
            + int(config.get("weight", 0)) * 5
            + (15 if item.get("vendor_default") else 0)
            + min(20, int(item.get("signal", 0) or 0) // 10)
            + min(10, len(item.get("summary", "")) // 100),
            item.get("published") or "",
            item.get("id") or "",
        )
    return max(group, key=score)


def merge_group_sources(event, group, primary):
    """Attach secondary reports without replacing the primary editorial output."""
    existing_ids = {item.get("id") for item in event.get("items", [])}
    for item in group:
        if item is primary or item.get("id") in existing_ids:
            continue
        event["items"].append({
            "id": item["id"], "source": item["source"], "link": item["link"],
            "published": item.get("published"), "ingested_at": item.get("ingested_at"),
            "title": item["title"],
        })
        existing_ids.add(item.get("id"))
        event["signal"] = max(event.get("signal", 0), item.get("signal", 0))
        event["vendors"] = list(dict.fromkeys(
            event.get("vendors", []) + item.get("vendors", [])
        ))[:5]
    recalc_event_heat(event)


def detect_source_language(text):
    """Small deterministic gate: Chinese goes straight through, others translate."""
    value = str(text or "")
    han = len(re.findall(r"[\u3400-\u9fff]", value))
    kana = len(re.findall(r"[\u3040-\u30ff]", value))
    hangul = len(re.findall(r"[\uac00-\ud7af]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    if kana >= 4 or hangul >= 4:
        return "other"
    if han >= 20 and han / max(1, han + latin) >= 0.16:
        return "zh"
    if han and latin < 10:
        return "zh"
    if latin >= 20:
        return "other"
    return "unknown"


def _content_hash(blocks, text=""):
    payload = (
        json.dumps(sanitize_blocks(blocks), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if blocks else str(text or "").strip()
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24] if payload else ""


def _aligned_translation_blocks(source_blocks, translated_blocks):
    """Recover only a structurally proven translated span from an older parser."""
    source = sanitize_blocks(source_blocks)
    translated = sanitize_blocks(translated_blocks)
    report = {
        "status": "rejected", "reason": "missing_blocks", "anchors": 0,
        "source_blocks": len(source), "stored_blocks": len(translated),
        "source_anchor_ratio": 0.0, "dropped_prefix_blocks": 0,
        "dropped_suffix_blocks": 0,
    }
    if not source or not translated:
        return [], report
    translated_positions = {
        block.get("id"): index for index, block in enumerate(translated) if block.get("id")
    }
    pairs = [
        (index, translated_positions[block.get("id")])
        for index, block in enumerate(source)
        if block.get("id") in translated_positions
    ]
    report["anchors"] = len(pairs)
    report["source_anchor_ratio"] = round(len(pairs) / max(1, len(source)), 4)
    minimum_anchors = min(len(source), max(3, (len(source) * 3 + 4) // 5))
    if len(pairs) < minimum_anchors:
        report["reason"] = "insufficient_stable_ids"
        return [], report
    if any(left[1] >= right[1] for left, right in zip(pairs, pairs[1:])):
        report["reason"] = "anchor_order_changed"
        return [], report
    if pairs[0][0] > 2 or pairs[-1][0] < len(source) - 3:
        report["reason"] = "source_boundaries_unproven"
        return [], report
    start, end = pairs[0][1], pairs[-1][1] + 1
    aligned = translated[start:end]
    if [block.get("type") for block in aligned] != [block.get("type") for block in source]:
        report["reason"] = "block_shape_changed"
        return [], report
    aligned, quality = trim_article_blocks(aligned)
    if quality.get("quality_status") != "pass" or len(aligned) != len(source):
        report["reason"] = "aligned_span_not_clean"
        return [], report
    report.update({
        "status": "aligned", "reason": "", "aligned_blocks": len(aligned),
        "dropped_prefix_blocks": start,
        "dropped_suffix_blocks": len(translated) - end,
    })
    return aligned, report


def _translation_batches(nodes, maximum_chars=None):
    maximum_chars = maximum_chars or _bounded_env_int(
        "CONTENT_TRANSLATION_BATCH_CHARS", 6000, minimum=1000, maximum=12000,
    )
    batches, current, used = [], [], 0
    for node in nodes:
        size = len(node.get("text", ""))
        if current and used + size > maximum_chars:
            batches.append(current)
            current, used = [], 0
        current.append(node)
        used += size
    if current:
        batches.append(current)
    return batches


def _block_translation_prompt(batch, index, total):
    return (
        "你是忠实翻译器。下面 JSON 来自同一篇文章，按原文顺序逐节点翻译成简体中文。"
        "只翻译 text：不得总结、删减、扩写、重组、合并或改变论证顺序；"
        "保留全部事实、数字、专有名词、代码和链接文字。"
        "不新增节点，不输出 HTML/Markdown，不改 id。"
        '只输出 JSON：{"nodes":[{"id":"原id","text":"忠实中文译文"}]}\n'
        f"批次 {index}/{total}：\n"
        + json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
    )


def _plain_translation_prompt(chunk, index, total):
    return (
        "将下面文章片段忠实翻译成简体中文。不得总结、删减、扩写、重组或抽象；"
        "保留段落顺序、事实、数字、专有名词和代码。只输出译文。\n\n"
        f"片段 {index}/{total}：\n{chunk}"
    )


def _estimated_llm_tokens(prompt, max_tokens):
    return max(512, len(prompt) // 3 + int(max_tokens or 0))


def translation_budget_estimate(blocks=None, text=""):
    """Estimate the whole faithful translation before starting any paid batch."""
    source_blocks = sanitize_blocks(blocks or [])
    if source_blocks:
        nodes = translation_nodes(source_blocks, maximum_chars=None)
        batches = _translation_batches(nodes)
        prompts = [
            _block_translation_prompt(batch, index, len(batches))
            for index, batch in enumerate(batches, start=1)
        ]
        retry_batches = _translation_batches(nodes, maximum_chars=3000)
        prompts.extend(
            _block_translation_prompt(batch, index, len(retry_batches))
            for index, batch in enumerate(retry_batches, start=1)
        )
    else:
        chunks = _plain_text_chunks(text)
        prompts = [
            _plain_translation_prompt(chunk, index, len(chunks))
            for index, chunk in enumerate(chunks, start=1)
        ]
    return sum(_estimated_llm_tokens(prompt, 8000) for prompt in prompts)


def translate_article_blocks(blocks, cfg, *, source, item_id, deep=False, purpose=""):
    """Faithfully translate every text node while preserving local structure/IDs."""
    del deep  # 兼容旧调用签名；原文优先方案不再区分“标准/深度编译”。
    key, base, model = cfg
    source_blocks = sanitize_blocks(blocks)
    nodes = translation_nodes(source_blocks, maximum_chars=None)
    if not (key and base and model and nodes):
        return [], {
            "applied": 0, "ignored": 0, "missing": len(nodes),
            "batches": 0, "complete": False,
        }
    translated_nodes = []
    batches = _translation_batches(nodes)
    for index, batch in enumerate(batches, start=1):
        prompt = _block_translation_prompt(batch, index, len(batches))
        out = llm_chat(
            base, key, model, prompt, max_tokens=8000,
            purpose=purpose or "body_translation",
            source=source, item_id=item_id, strict_object=True,
        )
        translated_nodes.extend(out.get("nodes", []))
    translated, stats = apply_translations(source_blocks, translated_nodes)
    returned_ids = {
        str(node.get("id") or "")
        for node in translated_nodes if isinstance(node, dict) and str(node.get("text") or "").strip()
    }
    missing_nodes = [node for node in nodes if node["id"] not in returned_ids]
    retry_batches = _translation_batches(missing_nodes, maximum_chars=3000)
    for index, batch in enumerate(retry_batches, start=1):
        out = llm_chat(
            base, key, model,
            _block_translation_prompt(batch, index, len(retry_batches)),
            max_tokens=8000, purpose=purpose or "body_translation",
            source=source, item_id=item_id, strict_object=True,
        )
        translated_nodes.extend(out.get("nodes", []))
    if retry_batches:
        translated, stats = apply_translations(source_blocks, translated_nodes)
    stats["initial_batches"] = len(batches)
    stats["retry_batches"] = len(retry_batches)
    stats["retried_nodes"] = len(missing_nodes)
    stats["batches"] = len(batches) + len(retry_batches)
    stats["complete"] = stats.get("missing", 0) == 0 and stats.get("applied", 0) == len(nodes)
    return translated, stats


def _plain_text_chunks(text, maximum_chars=6000):
    chunks, current = [], ""
    for paragraph in re.split(r"\n\s*\n", str(text or "").strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        pieces = [paragraph[i:i + maximum_chars] for i in range(0, len(paragraph), maximum_chars)]
        for piece in pieces:
            candidate = piece if not current else current + "\n\n" + piece
            if current and len(candidate) > maximum_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def translate_plain_text(text, cfg, *, source, item_id, purpose="body_translation"):
    """Faithfully translate a rare plain-text article fallback without abstraction."""
    key, base, model = cfg
    chunks = _plain_text_chunks(text)
    if not (key and base and model and chunks):
        return ""
    output = []
    for index, chunk in enumerate(chunks, start=1):
        translated = llm_chat_text(
            base, key, model,
            _plain_translation_prompt(chunk, index, len(chunks)),
            max_tokens=8000, purpose=purpose, source=source, item_id=item_id,
        ).strip()
        if not translated:
            return ""
        output.append(translated)
    return "\n\n".join(output)


def content_parse_record(report, *, status, source="", reason="", media_report=None):
    """Build the small, persistent diagnostic contract used by Actions and latest.json."""
    report = report if isinstance(report, dict) else {}
    record = {
        "run_id": LLM_USAGE.run_id,
        "processor_version": CONTENT_BLOCKS_PROCESSOR_VERSION,
        "attempted_at": datetime.now(TZ).isoformat(),
        "status": str(status or "unknown")[:40],
        "source": str(source or "")[:120],
        "strategy": str(report.get("strategy") or "unknown")[:60],
    }
    for key in (
        "blocks", "text_chars", "figures", "tables", "figures_discovered",
        "figures_selected", "figures_rejected", "candidate_count",
        "figures_rejected_author", "figures_rejected_decorative",
        "figures_rejected_duplicate", "figures_rejected_small", "figures_rejected_limit",
        "trimmed_tail_blocks", "trimmed_head_blocks", "trimmed_promotional_blocks",
        "trimmed_embedded_ui_blocks", "embedded_ui_components",
        "selected_depth", "selected_raw_blocks", "selected_raw_text_chars",
        "broad_raw_blocks", "broad_raw_text_chars", "parent_extra_blocks",
        "candidate_count_raw", "candidate_duplicates", "candidate_quality_rejected",
        "duplicate_blocks",
    ):
        record[key] = max(0, int(report.get(key, 0) or 0))
    if report.get("selected_score") is not None:
        record["selected_score"] = round(float(report.get("selected_score") or 0), 2)
    record["quality_status"] = str(report.get("quality_status") or "unknown")[:40]
    quality_flags = report.get("quality_flags")
    if isinstance(quality_flags, list) and quality_flags:
        record["quality_flags"] = [str(flag)[:120] for flag in quality_flags[:8]]
    if report.get("boundary_marker"):
        record["boundary_marker"] = str(report["boundary_marker"])[:120]
    if report.get("boundary_start_marker"):
        record["boundary_start_marker"] = str(report["boundary_start_marker"])[:120]
    if report.get("selected_tag"):
        record["selected_tag"] = str(report["selected_tag"])[:40]
    if report.get("focus_ratio") is not None:
        record["focus_ratio"] = round(float(report.get("focus_ratio") or 0), 4)
    for key in ("link_ratio", "duplicate_ratio"):
        if report.get(key) is not None:
            record[key] = round(float(report.get(key) or 0), 4)
    selection_evidence = report.get("selection_evidence")
    if isinstance(selection_evidence, list) and selection_evidence:
        record["selection_evidence"] = [str(value)[:60] for value in selection_evidence[:8]]
    if report.get("noimageindex"):
        record["noimageindex"] = True
    if reason:
        record["reason"] = str(reason)[:120]
    if isinstance(media_report, dict):
        record["media"] = {
            key: max(0, int(media_report.get(key, 0) or 0))
            for key in ("figures", "cached", "link_only")
        }
        if media_report.get("policy_version"):
            record["media"]["policy_version"] = str(media_report["policy_version"])[:60]
        reasons = media_report.get("reasons")
        if isinstance(reasons, dict) and reasons:
            record["media"]["reasons"] = {
                str(key)[:60]: max(0, int(value or 0))
                for key, value in reasons.items()
            }
    return record


def source_media_policy(source_name, source_configs=None):
    """Return the source-bound CDN policy; shared CDN hosts are never global."""
    configs = source_configs if isinstance(source_configs, dict) else {}
    config = configs.get(source_name, {}) if isinstance(configs.get(source_name, {}), dict) else {}
    hosts = [
        str(host).strip().casefold().rstrip(".")
        for host in config.get("media_hosts", [])
        if isinstance(host, str) and host.strip()
    ]
    return {
        "allowed_hosts": hosts,
        "send_referer": config.get("media_referer") == "article" and bool(hosts),
    }


def generate_event_body(
    event, primary, cfg, body_state=None, *, purpose="body_translation", media_policy=None,
):
    """Materialize a readable original/translation; use AI prose only as last fallback."""
    body_state = body_state if isinstance(body_state, dict) else {}
    article_url = primary.get("link", "")
    source = primary.get("source", "")
    article_blocks = sanitize_blocks(primary.get("article_blocks", []), article_url)
    article_text = str(primary.get("article_text") or "").strip()
    original_text = blocks_plain_text(article_blocks) if article_blocks else article_text
    content_hash = _content_hash(article_blocks, article_text)
    previous_record = (
        dict(event.get("content_parse"))
        if isinstance(event.get("content_parse"), dict) else {}
    )
    previous_blocks, previous_quality = trim_article_blocks(
        sanitize_blocks(event.get("content_blocks", []), article_url)
    )
    completed_same_source = bool(
        content_hash and event.get("source_content_hash") == content_hash
        and (event.get("content_blocks") or event.get("full_zh"))
        and previous_record.get("processor_version") == CONTENT_BLOCKS_PROCESSOR_VERSION
        and previous_record.get("quality_status") == "pass"
        and (
            event.get("content_mode") == "translated"
            and event.get("translation_status") == "complete"
            or event.get("content_mode") == "original"
            and event.get("source_language") == "zh"
            and event.get("translation_status") == "not_needed"
        )
    )
    if completed_same_source:
        return event.get("full_zh", "")

    if not original_text:
        event["full_zh"] = event.get("full_zh") or event.get("zh_summary", "")
        event["content_mode"] = "ai_fallback"
        event["content_level"] = "summary"
        event["source_language"] = "unknown"
        event["translation_status"] = "not_applicable"
        event["body_chars"] = len(event["full_zh"])
        body_state["fallback"] = body_state.get("fallback", 0) + 1
        return event["full_zh"]

    language = detect_source_language(original_text)
    display_blocks = article_blocks
    display_text = original_text
    mode = "original"
    translation_status = "not_needed" if language == "zh" else "unavailable"
    translation_error = ""
    translation_reused = ""
    translation_alignment = {}
    if language != "zh":
        aligned_translation, translation_alignment = _aligned_translation_blocks(
            article_blocks, previous_blocks,
        )
        previous_text = blocks_plain_text(aligned_translation)
        can_reuse_previous_translation = bool(
            article_blocks and aligned_translation
            and event.get("content_mode") == "translated"
            and event.get("translation_status") == "complete"
            and previous_record.get("processor_version") != CONTENT_BLOCKS_PROCESSOR_VERSION
        )
        if can_reuse_previous_translation:
            # Parser upgrades should not spend tokens retranslating a body that was
            # already translated faithfully. Apply the new deterministic boundary
            # to the stored blocks and retain that auditable translation.
            display_blocks = aligned_translation
            display_text = previous_text
            mode, translation_status = "translated", "complete"
            translation_reused = "aligned_stored_translation"
        try:
            if not translation_reused:
                if cfg[0] and cfg[1] and cfg[2]:
                    estimated_tokens = translation_budget_estimate(article_blocks, article_text)
                    if estimated_tokens and not LLM_USAGE.can_call(estimated_tokens):
                        status = LLM_USAGE.budget_status(estimated_tokens)
                        raise LLMBudgetExceeded(
                            "whole article translation needs "
                            f"{estimated_tokens} tokens; available {status['available_tokens']}"
                        )
                if article_blocks:
                    translated, stats = translate_article_blocks(
                        article_blocks, cfg, source=source, item_id=event["event_id"],
                        purpose=purpose,
                    )
                    if translated and stats.get("complete"):
                        display_blocks = translated
                        display_text = blocks_plain_text(translated)
                        mode, translation_status = "translated", "complete"
                    elif cfg[0] and cfg[1] and cfg[2]:
                        translation_status = "failed"
                        translation_error = "incomplete_translation"
                else:
                    translated_text = translate_plain_text(
                        article_text, cfg, source=source, item_id=event["event_id"], purpose=purpose,
                    )
                    if translated_text:
                        display_text = translated_text
                        mode, translation_status = "translated", "complete"
                    elif cfg[0] and cfg[1] and cfg[2]:
                        translation_status = "failed"
                        translation_error = "empty_translation"
        except Exception as exc:
            translation_status = "failed"
            translation_error = type(exc).__name__
            print(f"[body] 翻译失败，保留原文: {event.get('zh_title', '')[:40]} | {exc}")

    media_report = None
    if display_blocks:
        media_policy = media_policy if isinstance(media_policy, dict) else {}
        cached_blocks, media_report = cache_event_media(
            display_blocks, event["event_id"], article_url, SITE,
            allowed_hosts=media_policy.get("allowed_hosts"),
            send_referer=bool(media_policy.get("send_referer")),
        )
        event["content_blocks"] = cached_blocks
        event["content_format"] = "blocks-v1"
        display_text = blocks_plain_text(cached_blocks)
        if media_report["figures"]:
            print(
                f"[media] {event.get('zh_title', '')[:30]} | "
                f"缓存 {media_report['cached']} / 链接 {media_report['link_only']}"
            )
    else:
        event.pop("content_blocks", None)
        event["content_format"] = "plain-v1"

    record = content_parse_record(
        primary.get("_article_parse"), status="ready", source=source,
        reason=translation_error, media_report=media_report,
    )
    record.update({
        "content_mode": mode, "source_language": language,
        "translation_status": translation_status, "source_content_hash": content_hash,
    })
    if isinstance(previous_record.get("metadata_translation"), dict):
        record["metadata_translation"] = previous_record["metadata_translation"]
    if language != "zh":
        record["translation"] = {
            "run_id": LLM_USAGE.run_id,
            "policy_version": TRANSLATION_RETRY_POLICY_VERSION,
            "attempted_at": datetime.now(TZ).isoformat(),
            "purpose": purpose,
            "status": "complete" if translation_status == "complete" else (
                "budget_deferred" if translation_error == "LLMBudgetExceeded" else translation_status
            ),
        }
        if translation_reused:
            record["translation"]["reused"] = True
            record["translation"]["reuse_method"] = translation_reused
            record["translation"]["alignment"] = {
                key: translation_alignment[key]
                for key in (
                    "status", "anchors", "source_blocks", "stored_blocks",
                    "source_anchor_ratio", "aligned_blocks",
                    "dropped_prefix_blocks", "dropped_suffix_blocks",
                )
                if key in translation_alignment
            }
            record["translation"]["trimmed_head_blocks"] = int(
                previous_quality.get("trimmed_head_blocks", 0) or 0
            )
            record["translation"]["trimmed_tail_blocks"] = int(
                previous_quality.get("trimmed_tail_blocks", 0) or 0
            )
            record["translation"]["trimmed_promotional_blocks"] = int(
                previous_quality.get("trimmed_promotional_blocks", 0) or 0
            )
        if translation_error:
            record["translation"]["error"] = translation_error[:80]
    event["content_parse"] = record
    event["full_zh"] = display_text
    event["content_mode"] = mode
    event["content_level"] = mode
    event["source_language"] = language
    event["translation_status"] = translation_status
    event["source_content_hash"] = content_hash
    event["body_chars"] = len(display_text)
    body_state[mode] = body_state.get(mode, 0) + 1
    return display_text


def _bounded_env_int(name, default, *, minimum=0, maximum=100):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _event_time(event):
    value = parse_date(event.get("first_seen") or event.get("published"))
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _contains_han(value):
    return bool(re.search(r"[\u3400-\u9fff]", str(value or "")))


def _metadata_translation_record(event):
    record = event.get("content_parse") if isinstance(event.get("content_parse"), dict) else {}
    nested = record.get("metadata_translation")
    return nested if isinstance(nested, dict) else {}


def backfill_event_metadata(events, cfg, *, now=None, limit=None, lookback_days=30):
    """Repair recent non-Chinese list metadata without replacing or deleting events."""
    now = now or datetime.now(timezone.utc)
    now_utc = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    limit = (
        _bounded_env_int("CONTENT_METADATA_BACKFILL_LIMIT", 3, maximum=8)
        if limit is None else max(0, min(8, int(limit)))
    )
    summary = {
        "limit": limit, "eligible": 0, "attempted": 0, "complete": 0,
        "deferred_budget": 0, "skipped": 0, "failed": 0,
    }
    key, base, model = cfg
    if not (limit and key and base and model):
        summary["disabled_reason"] = "no_budget_or_config"
        return summary

    cooldown_cutoff = now_utc - timedelta(hours=6)
    eligible = []
    for event in events:
        if not event.get("items") or _event_time(event) < now_utc - timedelta(days=lookback_days):
            continue
        if _contains_han(event.get("zh_title")) and _contains_han(event.get("zh_summary")):
            continue
        previous = _metadata_translation_record(event)
        attempted_at = parse_date(previous.get("attempted_at"))
        if (
            previous.get("policy_version") == METADATA_TRANSLATION_POLICY_VERSION
            and previous.get("status") == "provider_error"
            and attempted_at is not None
        ):
            if attempted_at.tzinfo is None:
                attempted_at = attempted_at.replace(tzinfo=timezone.utc)
            if attempted_at.astimezone(timezone.utc) >= cooldown_cutoff:
                continue
        eligible.append(event)
    eligible.sort(key=_event_time, reverse=True)
    summary["eligible"] = len(eligible)

    for event in eligible[:limit]:
        primary = event["items"][0]
        original_title = primary.get("title") or event.get("zh_title") or ""
        original_summary = event.get("zh_summary") or ""
        original_body = str(event.get("full_zh") or "")[:2200]
        prompt = (
            ENRICH_RULES
            + "\n\n这是已收录事件的中文元数据补译。不得因 relevant=false 删除事件；"
              "只依据给出的原文忠实生成中文标题、摘要和推荐理由，不得抽象、扩写或编造。\n"
            + f"标题：{original_title}\n摘要：{original_summary[:800]}\n原文节选：{original_body}"
        )
        estimated_tokens = _estimated_llm_tokens(prompt, 1800)
        if not LLM_USAGE.can_call(estimated_tokens):
            summary["deferred_budget"] += 1
            break
        summary["attempted"] += 1
        try:
            out = llm_chat(
                base, key, model, prompt, max_tokens=1800,
                purpose="metadata_translation_backfill",
                source=primary.get("source", ""), item_id=event.get("event_id", ""),
                strict_object=True,
            )
            zh_title = str(out.get("zh_title") or "").strip()
            zh_summary = str(out.get("zh_summary") or "").strip()
            if not (_contains_han(zh_title) and _contains_han(zh_summary)):
                raise ValueError("metadata_translation_missing_chinese")
            event["zh_title"] = zh_title
            event["zh_summary"] = zh_summary
            event["reason"] = str(out.get("reason") or event.get("reason") or "").strip()
            category = out.get("category")
            if category in CATEGORIES_LABEL:
                event["category"] = category
                event["category_label"] = CATEGORIES_LABEL[category]
            event["vendors"] = list(dict.fromkeys(
                list(event.get("vendors") or [])
                + [value for value in (out.get("vendors") or []) if isinstance(value, str) and value.strip()]
            ))[:5]
            event["topics"] = [value for value in (out.get("topics") or []) if value in TOPIC_NAMES][:2]
            if isinstance(out.get("work_tags"), dict):
                event["work_tags"] = normalize_work_tags(out["work_tags"])
            if out.get("shelf") in {"news", "evergreen"}:
                event["shelf"] = out["shelf"]
            quality, breakdown = normalize_quality_result(
                out, event.get("quality_score", event.get("importance", 50)),
            )
            event["quality_score"] = quality
            event["importance"] = quality
            if breakdown:
                event["quality_breakdown"] = breakdown
            event["star"] = quality >= 75
            recalc_event_heat(event)
            nested = {
                "run_id": LLM_USAGE.run_id,
                "policy_version": METADATA_TRANSLATION_POLICY_VERSION,
                "attempted_at": datetime.now(TZ).isoformat(),
                "purpose": "metadata_translation_backfill",
                "status": "complete",
            }
            record = dict(event.get("content_parse") or {})
            record["metadata_translation"] = nested
            event["content_parse"] = record
            summary["complete"] += 1
            print(f"[metadata-backfill] {event.get('event_id')} | {zh_title[:40]}")
        except LLMBudgetExceeded:
            summary["attempted"] -= 1
            summary["deferred_budget"] += 1
            break
        except Exception as exc:
            record = dict(event.get("content_parse") or {})
            record["metadata_translation"] = {
                "run_id": LLM_USAGE.run_id,
                "policy_version": METADATA_TRANSLATION_POLICY_VERSION,
                "attempted_at": datetime.now(TZ).isoformat(),
                "purpose": "metadata_translation_backfill",
                "status": "provider_error",
                "error": type(exc).__name__[:80],
            }
            event["content_parse"] = record
            summary["failed"] += 1
            print(f"[metadata-backfill] 失败 {event.get('event_id')} | {exc}")
    return summary


def backfill_structured_content(
    events, cfg, *, now=None, limit=None, lookback_days=None, feed_content_by_url=None,
    source_configs=None,
):
    """Upgrade legacy bodies and retry preserved foreign originals in a stable order."""
    now = now or datetime.now(timezone.utc)
    now_utc = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    limit = (
        _bounded_env_int("CONTENT_TRANSLATION_BACKFILL_LIMIT", 6, maximum=8)
        if limit is None else max(0, min(8, int(limit)))
    )
    lookback_days = (
        _bounded_env_int("CONTENT_BLOCKS_BACKFILL_DAYS", 30, minimum=1, maximum=90)
        if lookback_days is None else max(1, min(90, int(lookback_days)))
    )
    attempt_limit = _bounded_env_int("CONTENT_BACKFILL_ATTEMPTS", 12, maximum=48)
    summary = {
        "foreign_limit": limit, "eligible": 0, "attempted": 0, "ready": 0,
        "original": 0, "translated": 0, "deferred_foreign": 0,
        "deferred_budget": 0, "stored_original_retries": 0,
        "parser_debt_eligible": 0, "skipped": 0, "failed": 0,
    }
    requested_event_ids = {
        value.strip() for value in re.split(",|\n", os.getenv("CONTENT_BACKFILL_EVENT_IDS", ""))
        if re.fullmatch(r"[A-Za-z0-9_-]{3,80}", value.strip())
    }
    if requested_event_ids:
        summary["requested_event_ids"] = sorted(requested_event_ids)
    if attempt_limit <= 0:
        summary["disabled_reason"] = "attempt_limit_zero"
        return summary
    feed_content_by_url = feed_content_by_url if isinstance(feed_content_by_url, dict) else {}

    retry_cutoff = now_utc - timedelta(days=7)
    eligible = []
    for event in events:
        if not event.get("items"):
            continue
        mode = event.get("content_mode")
        language = event.get("source_language")
        translation_status = event.get("translation_status")
        previous = event.get("content_parse") if isinstance(event.get("content_parse"), dict) else {}
        processor_current = bool(
            previous.get("processor_version") == CONTENT_BLOCKS_PROCESSOR_VERSION
            and previous.get("quality_status") == "pass"
        )
        parser_debt = not processor_current and bool(event.get("content_blocks"))
        within_window = _event_time(event) >= now_utc - timedelta(days=lookback_days)
        evergreen_debt = event.get("shelf") == "evergreen" and parser_debt
        if not within_window and not evergreen_debt:
            continue
        if evergreen_debt:
            summary["parser_debt_eligible"] += 1
        if mode == "translated" and translation_status == "complete" and processor_current:
            continue
        if (
            mode == "original" and language == "zh"
            and translation_status == "not_needed" and processor_current
        ):
            continue
        foreign_retry = bool(
            mode == "original" and language != "zh" and translation_status != "complete"
            and (event.get("content_blocks") or event.get("full_zh"))
        )
        if not foreign_retry:
            attempted_at = parse_date(previous.get("attempted_at"))
            if attempted_at is not None and previous.get("processor_version") == CONTENT_BLOCKS_PROCESSOR_VERSION:
                if attempted_at.tzinfo is None:
                    attempted_at = attempted_at.replace(tzinfo=timezone.utc)
                if attempted_at.astimezone(timezone.utc) >= retry_cutoff:
                    continue
        eligible.append(event)

    if requested_event_ids:
        eligible = [
            event for event in eligible
            if event.get("event_id") in requested_event_ids
        ]

    homepage = rank_timeline_events(
        events, page_size=DEFAULT_PAGE_SIZE, source_caps=FIRST_PAGE_SOURCE_CAPS,
    )[:DEFAULT_PAGE_SIZE]
    home_priority = {
        event.get("event_id"): DEFAULT_PAGE_SIZE - index
        for index, event in enumerate(homepage)
    }

    def quality_refresh_priority(event):
        stored = sanitize_blocks(event.get("content_blocks", []))
        if not stored:
            return 0
        _trimmed, quality = trim_article_blocks(stored)
        return int(
            quality.get("trimmed_tail_blocks", 0) > 0
            or quality.get("trimmed_head_blocks", 0) > 0
            or quality.get("quality_status") != "pass"
        )

    def parser_debt_priority(event):
        previous = event.get("content_parse") if isinstance(event.get("content_parse"), dict) else {}
        return int(
            bool(event.get("content_blocks"))
            and (
                previous.get("processor_version") != CONTENT_BLOCKS_PROCESSOR_VERSION
                or previous.get("quality_status") != "pass"
            )
        )

    eligible.sort(key=lambda event: (
        quality_refresh_priority(event),
        parser_debt_priority(event),
        int(
            _metadata_translation_record(event).get("run_id") == LLM_USAGE.run_id
            and _metadata_translation_record(event).get("status") == "complete"
        ),
        home_priority.get(event.get("event_id"), 0),
        bool(event.get("pinned")), event.get("shelf") == "evergreen",
        int(event.get("importance", 0) or 0), _event_time(event),
    ), reverse=True)
    summary["eligible"] = len(eligible)

    foreign_used = 0
    for event in eligible[:attempt_limit]:
        primary = event["items"][0]
        source = primary.get("source", "")
        summary["attempted"] += 1
        previous = event.get("content_parse") if isinstance(event.get("content_parse"), dict) else {}
        stored_blocks = sanitize_blocks(event.get("content_blocks", []), primary.get("link", ""))
        stored_text = blocks_plain_text(stored_blocks) if stored_blocks else str(event.get("full_zh") or "").strip()
        stored_foreign = bool(
            event.get("content_mode") == "original"
            and event.get("source_language") != "zh"
            and event.get("translation_status") != "complete"
            and stored_text
        )
        stored_foreign_reusable = bool(
            stored_foreign
            and (
                not stored_blocks
                or (
                    previous.get("processor_version") == CONTENT_BLOCKS_PROCESSOR_VERSION
                    and previous.get("quality_status") == "pass"
                )
            )
        )
        if stored_foreign_reusable:
            text, blocks, parse_report = stored_text, stored_blocks, dict(previous)
            summary["stored_original_retries"] += 1
        else:
            text, _title, published, blocks, parse_report = fetch_article_content(
                primary.get("link", ""), include_report=True,
            )
            text, blocks, parse_report = prefer_rss_article_content(
                text, blocks, parse_report,
                feed_content_by_url.get(norm_url(primary.get("link", ""))),
                primary.get("link", ""),
            )
            if published is not None:
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                published_iso = published.astimezone(TZ).isoformat()
                event["published"] = published_iso
                primary["published"] = published_iso
        if not text:
            event["content_parse"] = content_parse_record(
                parse_report, status="skipped", source=source,
                reason="no_usable_original",
            )
            summary["skipped"] += 1
            continue
        language = detect_source_language(blocks_plain_text(blocks) if blocks else text)
        trimmed_stored_blocks, _stored_quality = trim_article_blocks(stored_blocks)
        aligned_translation, _alignment = _aligned_translation_blocks(
            blocks, trimmed_stored_blocks,
        )
        reusable_translation = bool(
            language != "zh" and aligned_translation
            and event.get("content_mode") == "translated"
            and event.get("translation_status") == "complete"
            and previous.get("processor_version") != CONTENT_BLOCKS_PROCESSOR_VERSION
        )
        can_translate = bool(
            language != "zh" and not reusable_translation
            and cfg[0] and cfg[1] and cfg[2] and foreign_used < limit
        )
        if can_translate:
            estimated_tokens = translation_budget_estimate(blocks, text)
            if estimated_tokens and not LLM_USAGE.can_call(estimated_tokens):
                can_translate = False
                summary["deferred_budget"] += 1
        if language != "zh" and not can_translate and not reusable_translation:
            summary["deferred_foreign"] += 1
            if stored_foreign_reusable:
                continue
        if can_translate:
            foreign_used += 1
        body_cfg = cfg if language == "zh" or can_translate else ("", "", "")
        body_primary = dict(primary)
        body_primary.update({
            "article_text": text, "article_blocks": blocks, "_article_parse": parse_report,
        })
        try:
            generate_event_body(
                event, body_primary, body_cfg, {}, purpose="body_translation_backfill",
                media_policy=source_media_policy(source, source_configs),
            )
            summary["ready"] += 1
            summary[event.get("content_mode", "original")] = summary.get(
                event.get("content_mode", "original"), 0,
            ) + 1
            print(
                f"[backfill] {event.get('zh_title', '')[:36]} | "
                f"{event.get('content_mode')} | {parse_report.get('strategy')} | "
                f"图 {parse_report.get('figures', 0)} 表 {parse_report.get('tables', 0)}"
            )
        except Exception as exc:
            event["content_parse"] = content_parse_record(
                parse_report, status="failed", source=source, reason=str(exc),
            )
            summary["failed"] += 1
            print(f"[backfill] 失败 {event.get('zh_title', '')[:36]} | {exc}")
    summary["planned"] = summary["ready"]
    return summary


def refresh_media_cache(events, source_configs=None, *, limit=None):
    """Retry recoverable historical figures under the current source-bound policy."""
    limit = (
        _bounded_env_int("MEDIA_CACHE_BACKFILL_EVENTS", 48, maximum=64)
        if limit is None else max(0, min(64, int(limit)))
    )
    summary = {
        "policy_version": MEDIA_CACHE_POLICY_VERSION,
        "eligible": 0, "attempted": 0, "figures": 0,
        "cached": 0, "link_only": 0, "reasons": {},
    }
    if limit <= 0:
        return summary

    eligible = []
    for event in events:
        if not event.get("items"):
            continue
        blocks = sanitize_blocks(
            event.get("content_blocks", []), event["items"][0].get("link", ""),
        )
        if not blocks:
            continue
        previous = event.get("content_parse") if isinstance(event.get("content_parse"), dict) else {}
        previous_media = previous.get("media") if isinstance(previous.get("media"), dict) else {}
        if previous_media.get("policy_version") == MEDIA_CACHE_POLICY_VERSION:
            continue
        primary = event["items"][0]
        policy = source_media_policy(primary.get("source", ""), source_configs)
        retryable = 0
        for block in blocks:
            if block.get("type") != "figure" or block.get("media_status") != "link_only":
                continue
            reason = block.get("media_reason")
            if reason not in RETRYABLE_MEDIA_REASONS:
                continue
            if reason in {"cross_site_host", "redirected_cross_site"} and not same_site_media(
                block.get("src", ""), primary.get("link", ""),
                allowed_hosts=policy["allowed_hosts"],
            ):
                continue
            retryable += 1
        if retryable:
            eligible.append((retryable, _event_time(event), event, blocks, policy))

    eligible.sort(key=lambda item: (item[0], item[1]), reverse=True)
    summary["eligible"] = len(eligible)
    for _retryable, _timestamp, event, blocks, policy in eligible[:limit]:
        primary = event["items"][0]
        cached_blocks, report = cache_event_media(
            blocks, event["event_id"], primary.get("link", ""), SITE,
            allowed_hosts=policy["allowed_hosts"], send_referer=policy["send_referer"],
        )
        event["content_blocks"] = cached_blocks
        record = event.get("content_parse") if isinstance(event.get("content_parse"), dict) else {}
        record = dict(record)
        record.update({
            "run_id": LLM_USAGE.run_id,
            "attempted_at": datetime.now(TZ).isoformat(),
            "status": record.get("status") or "ready",
            "source": record.get("source") or primary.get("source", ""),
        })
        record["media"] = {
            key: max(0, int(report.get(key, 0) or 0))
            for key in ("figures", "cached", "link_only")
        }
        record["media"]["policy_version"] = MEDIA_CACHE_POLICY_VERSION
        if report.get("reasons"):
            record["media"]["reasons"] = dict(report["reasons"])
        event["content_parse"] = record
        summary["attempted"] += 1
        for key in ("figures", "cached", "link_only"):
            summary[key] += int(report.get(key, 0) or 0)
        for reason, count in report.get("reasons", {}).items():
            summary["reasons"][reason] = summary["reasons"].get(reason, 0) + int(count)
        print(
            f"[media-refresh] {event.get('zh_title', '')[:36]} | "
            f"缓存 {report.get('cached', 0)} / 隐藏 {report.get('link_only', 0)}"
        )
    return summary


def structured_content_metrics(events, *, run_id=""):
    """Summarize one run's parser/fallback/media outcomes for persistent observability."""
    metrics = {
        "run_id": run_id or LLM_USAGE.run_id,
        "attempted": 0, "ready": 0, "figures": 0, "tables": 0,
        "media_cached": 0, "media_link_only": 0,
        "candidate_duplicates": 0, "candidate_quality_rejected": 0,
        "strategies": {}, "quality_statuses": {}, "content_modes": {},
        "fallbacks": {}, "by_source": {},
    }
    for event in events:
        record = event.get("content_parse")
        if not isinstance(record, dict) or (run_id and record.get("run_id") != run_id):
            continue
        metrics["attempted"] += 1
        status = str(record.get("status") or "unknown")
        if status == "ready":
            metrics["ready"] += 1
        metrics["figures"] += int(record.get("figures", 0) or 0)
        metrics["tables"] += int(record.get("tables", 0) or 0)
        strategy = str(record.get("strategy") or "unknown")
        metrics["strategies"][strategy] = metrics["strategies"].get(strategy, 0) + 1
        quality_status = str(record.get("quality_status") or "unknown")
        metrics["quality_statuses"][quality_status] = (
            metrics["quality_statuses"].get(quality_status, 0) + 1
        )
        metrics["candidate_duplicates"] += int(record.get("candidate_duplicates", 0) or 0)
        metrics["candidate_quality_rejected"] += int(
            record.get("candidate_quality_rejected", 0) or 0
        )
        mode = str(record.get("content_mode") or "unknown")
        metrics["content_modes"][mode] = metrics["content_modes"].get(mode, 0) + 1
        if status != "ready":
            reason = str(record.get("reason") or status)[:120]
            metrics["fallbacks"][reason] = metrics["fallbacks"].get(reason, 0) + 1
        media = record.get("media") if isinstance(record.get("media"), dict) else {}
        metrics["media_cached"] += int(media.get("cached", 0) or 0)
        metrics["media_link_only"] += int(media.get("link_only", 0) or 0)
        source = str(record.get("source") or "unknown")
        source_metrics = metrics["by_source"].setdefault(
            source, {"attempted": 0, "ready": 0, "figures": 0, "tables": 0, "media_cached": 0},
        )
        source_metrics["attempted"] += 1
        source_metrics["ready"] += int(status == "ready")
        source_metrics["figures"] += int(record.get("figures", 0) or 0)
        source_metrics["tables"] += int(record.get("tables", 0) or 0)
        source_metrics["media_cached"] += int(media.get("cached", 0) or 0)
    return metrics


def catalog_content_metrics(events):
    """Measure the reader-visible content catalog, including historical parser debt."""
    metrics = {
        "events": len(events), "structured": 0, "renderable": 0,
        "current_pass": 0, "parser_debt": 0, "display_trimmed": 0,
        "display_suspect": 0, "embedded_ui_trimmed": 0,
        "embedded_ui_blocks": 0, "modes": {}, "processor_versions": {},
    }
    for event in events:
        mode = str(event.get("content_mode") or "missing")
        metrics["modes"][mode] = metrics["modes"].get(mode, 0) + 1
        record = event.get("content_parse") if isinstance(event.get("content_parse"), dict) else {}
        version = str(record.get("processor_version") or "missing")
        metrics["processor_versions"][version] = metrics["processor_versions"].get(version, 0) + 1
        blocks = sanitize_blocks(
            event.get("content_blocks", []),
            ((event.get("items") or [{}])[0].get("link", "") if event.get("items") else ""),
        )
        if not blocks:
            continue
        metrics["structured"] += 1
        trimmed, quality = trim_article_blocks(blocks)
        if len(blocks_plain_text(trimmed)) >= 120:
            metrics["renderable"] += 1
        if quality.get("quality_status") != "pass":
            metrics["display_suspect"] += 1
        if len(trimmed) != len(blocks):
            metrics["display_trimmed"] += 1
        embedded_removed = int(quality.get("trimmed_embedded_ui_blocks", 0) or 0)
        if embedded_removed:
            metrics["embedded_ui_trimmed"] += 1
            metrics["embedded_ui_blocks"] += embedded_removed
        if (
            record.get("processor_version") == CONTENT_BLOCKS_PROCESSOR_VERSION
            and record.get("quality_status") == "pass"
        ):
            metrics["current_pass"] += 1
        else:
            metrics["parser_debt"] += 1
    return metrics


def normalize_catalog_article_ui(events):
    """Apply the reader-visible article boundary policy to stored catalog bodies."""
    summary = {
        "policy_version": ARTICLE_UI_SANITIZER_VERSION,
        "scanned": 0, "cleaned_events": 0, "removed_blocks": 0,
    }
    for event in events if isinstance(events, list) else []:
        summary["scanned"] += 1
        primary = (event.get("items") or [{}])[0]
        article_url = primary.get("link", "") if isinstance(primary, dict) else ""
        stored_blocks = sanitize_blocks(event.get("content_blocks", []), article_url)
        removed = 0
        cleanup = {}
        if stored_blocks:
            cleaned_blocks, cleanup = trim_article_blocks(stored_blocks)
            removed = max(0, len(stored_blocks) - len(cleaned_blocks))
            if removed:
                event["content_blocks"] = cleaned_blocks
                event["content_format"] = "blocks-v1"
                event["full_zh"] = blocks_plain_text(cleaned_blocks)
        elif str(event.get("full_zh") or "").strip():
            cleaned_text, cleanup = strip_article_ui_text(event.get("full_zh", ""))
            removed = int(cleanup.get("trimmed_embedded_ui_blocks", 0) or 0)
            if removed:
                event["full_zh"] = cleaned_text
        if not removed:
            continue
        event["body_chars"] = len(str(event.get("full_zh") or ""))
        record = dict(event.get("content_parse") or {})
        record["article_ui_cleanup"] = {
            "policy_version": ARTICLE_UI_SANITIZER_VERSION,
            "run_id": LLM_USAGE.run_id,
            "cleaned_at": datetime.now(TZ).isoformat(),
            "removed_blocks": removed,
            "trimmed_head_blocks": int(cleanup.get("trimmed_head_blocks", 0) or 0),
            "trimmed_tail_blocks": int(cleanup.get("trimmed_tail_blocks", 0) or 0),
            "trimmed_promotional_blocks": int(
                cleanup.get("trimmed_promotional_blocks", 0) or 0
            ),
            "trimmed_embedded_ui_blocks": int(
                cleanup.get("trimmed_embedded_ui_blocks", 0) or 0
            ),
        }
        evidence = list(record.get("selection_evidence") or [])
        evidence.extend(cleanup.get("quality_evidence") or [])
        record["selection_evidence"] = list(dict.fromkeys(evidence))[:8]
        if stored_blocks:
            record["blocks"] = len(cleaned_blocks)
            record["text_chars"] = len(blocks_plain_text(cleaned_blocks))
            record["figures"] = sum(block.get("type") == "figure" for block in cleaned_blocks)
            record["tables"] = sum(block.get("type") == "table" for block in cleaned_blocks)
            record["quality_status"] = cleanup.get("quality_status", "pass")
            record["quality_flags"] = cleanup.get("quality_flags", [])
        event["content_parse"] = record
        summary["cleaned_events"] += 1
        summary["removed_blocks"] += removed
    return summary


def write_structured_content_summary(metrics):
    summary_path = str(os.getenv("GITHUB_STEP_SUMMARY", "")).strip()
    if not summary_path:
        return
    strategy_rows = "\n".join(
        f"| {name} | {count} |" for name, count in sorted(metrics.get("strategies", {}).items())
    ) or "| 无 | 0 |"
    text = (
        "\n## Structured article content\n\n"
        f"- Attempted: **{metrics.get('attempted', 0)}**；ready: **{metrics.get('ready', 0)}**\n"
        f"- Figures: **{metrics.get('figures', 0)}**；tables: **{metrics.get('tables', 0)}**\n"
        f"- Media cached: **{metrics.get('media_cached', 0)}**；link only: **{metrics.get('media_link_only', 0)}**\n\n"
        f"- Candidate duplicates removed: **{metrics.get('candidate_duplicates', 0)}**；"
        f"quality rejected: **{metrics.get('candidate_quality_rejected', 0)}**\n"
        f"- Catalog renderable: **{metrics.get('catalog', {}).get('renderable', 0)}** / "
        f"**{metrics.get('catalog', {}).get('structured', 0)}**；parser debt: "
        f"**{metrics.get('catalog', {}).get('parser_debt', 0)}**；player chrome cleaned: "
        f"**{metrics.get('article_ui_cleanup', {}).get('cleaned_events', 0)}**\n\n"
        "| Extraction strategy | Count |\n|---|---:|\n"
        f"{strategy_rows}\n"
    )
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(text)

def _event_candidate_comparable(item, event, max_hours=72):
    if item.get("category") and item.get("category") == event.get("category"):
        return True
    if set(item.get("vendors") or []) & set(event.get("vendors") or []):
        return True
    item_dt = item.get("_pub_dt") or parse_date(item.get("published"))
    event_dt = parse_date(event.get("first_seen") or event.get("published"))
    return bool(
        item_dt and event_dt
        and abs((item_dt - event_dt).total_seconds()) <= max_hours * 3600
    )


def cluster_events(new_items, events, cfg, *, late_merge=True):
    """把新条目分配进已有事件或新建事件。events: 既有事件列表（原地更新）"""
    def ev_desc(e):
        return f"标题:{e['zh_title']} 摘要:{e.get('zh_summary','')[:200]}"

    # 1) 新条目 vs 既有事件
    for it in new_items:
        it_titles = [it["zh_title"], it.get("title", "")]
        cand = []
        for e in events:
            if norm_url(e["items"][0]["link"]) == norm_url(it["link"]):
                cand.append((e, 1.0)); continue
            if not _event_candidate_comparable(it, e):
                continue
            sim = max_sim(it_titles, event_titles(e))
            if sim > 0.3:
                cand.append((e, sim))
        if not cand:
            events.append(make_event(it))
            continue
        pairs = [(f"标题:{it['zh_title']} 摘要:{it.get('zh_summary','')[:200]}", ev_desc(e)) for e, _ in cand]
        verdicts = llm_same_event(pairs, cfg)
        hit = next((cand[i][0] for i, v in enumerate(verdicts) if v), None)
        if hit:
            merge_into(hit, it)
            print(f"[cluster] 并入事件: {it['zh_title'][:30]} → {hit['zh_title'][:30]}")
        else:
            events.append(make_event(it))

    # 2) 既有事件之间的迟到合并（同事件分两批到达）
    changed = bool(late_merge)
    while changed:
        changed = False
        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                a, b = events[i], events[j]
                if max_sim(event_titles(a), event_titles(b)) > 0.3:
                    if llm_same_event([(ev_desc(a), ev_desc(b))], cfg)[0]:
                        for sub in b["items"]:
                            a["items"].append(sub)
                        a["published"] = max(a["published"], b["published"])
                        a_quality = int(a.get("quality_score", a.get("importance", 50)) or 50)
                        b_quality = int(b.get("quality_score", b.get("importance", 50)) or 50)
                        if b_quality > a_quality and b.get("quality_breakdown"):
                            a["quality_breakdown"] = b["quality_breakdown"]
                        a["quality_score"] = max(a_quality, b_quality)
                        a["importance"] = a["quality_score"]
                        a["signal"] = max(a.get("signal", 0), b.get("signal", 0))
                        recalc_event_heat(a)
                        a["vendors"] = list(dict.fromkeys(a.get("vendors", []) + b.get("vendors", [])))[:5]
                        merged_tags = merge_work_tags(a.get("work_tags"), b.get("work_tags"))
                        if merged_tags is not None:
                            a["work_tags"] = merged_tags
                        events.pop(j)
                        print(f"[cluster] 合并事件: {b['zh_title'][:30]} → {a['zh_title'][:30]}")
                        changed = True
                        break
            if changed:
                break
    return events

def make_event(it):
    eid = hashlib.md5(norm_url(it["link"]).encode()).hexdigest()[:12]
    event = {
        "event_id": eid,
        "zh_title": it["zh_title"], "zh_summary": it["zh_summary"], "reason": it.get("reason", ""),
        "full_zh": it.get("full_zh", ""),
        "content_blocks": it.get("content_blocks", []),
        "content_format": it.get("content_format", ""),
        "category": it["category"], "category_label": it["category_label"],
        "vendors": it.get("vendors", []), "heat": it["heat"], "star": it.get("star", False),
        "importance": it.get("importance", 50),
        "quality_score": it.get("quality_score", it.get("importance", 50)),
        "trend_score": it.get("trend_score", 0),
        "signal": it.get("signal", 0),
        "topics": it.get("topics", []), "shelf": it.get("shelf", "news"),
        "pinned": it.get("pinned", False),
        "published": it["published"],
        "first_seen": it.get("ingested_at") or it["published"],
        "items": [{"id": it["id"], "source": it["source"], "link": it["link"],
                   "published": it["published"], "ingested_at": it.get("ingested_at"), "title": it["title"]}],
    }
    if isinstance(it.get("work_tags"), dict):
        event["work_tags"] = normalize_work_tags(it["work_tags"])
    if isinstance(it.get("quality_breakdown"), dict):
        event["quality_breakdown"] = it["quality_breakdown"]
    for key in (
        "content_mode", "content_level", "source_language", "translation_status",
        "source_content_hash", "content_parse", "body_chars",
    ):
        if key in it:
            event[key] = it[key]
    return event

def recalc_event_heat(e, reference_time=None):
    """Recalculate independent quality/trend fields and compatibility heat."""
    published = e.get("published") or e.get("first_seen")
    pub = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
    quality = int(e.get("quality_score", e.get("importance", 50)) or 50)
    quality = max(1, min(100, quality))
    e["quality_score"] = quality
    e["importance"] = quality
    e["trend_score"] = calc_trend_score(
        pub, e.get("signal", 0), len(e["items"]) - 1,
        reference_time=reference_time,
    )
    e["heat"] = calc_heat(
        quality, pub, e.get("signal", 0), len(e["items"]) - 1,
        reference_time=reference_time,
    )
    e["star"] = quality >= 75

def merge_into(e, it):
    e["items"].append({"id": it["id"], "source": it["source"], "link": it["link"],
                       "published": it["published"], "ingested_at": it.get("ingested_at"), "title": it["title"]})
    if it["published"] and (not e["published"] or it["published"] < e["published"]):
        e["published"] = it["published"]
    fs_new = it.get("ingested_at") or it.get("published")
    if fs_new and (not e.get("first_seen") or fs_new < e["first_seen"]):
        e["first_seen"] = fs_new
    event_quality = int(e.get("quality_score", e.get("importance", 50)) or 50)
    item_quality = int(it.get("quality_score", it.get("importance", 50)) or 50)
    if item_quality > event_quality and it.get("quality_breakdown"):
        e["quality_breakdown"] = it["quality_breakdown"]
    e["quality_score"] = max(event_quality, item_quality)
    e["importance"] = e["quality_score"]
    e["signal"] = max(e.get("signal", 0), it.get("signal", 0))
    recalc_event_heat(e)
    if len(it.get("zh_summary", "")) > len(e.get("zh_summary", "")):
        e["zh_summary"], e["reason"] = it["zh_summary"], it.get("reason", e["reason"])
    if (
        it.get("content_mode") in {"original", "translated"}
        and e.get("content_mode") not in {"original", "translated"}
    ) or len(it.get("full_zh", "")) > len(e.get("full_zh", "")):
        e["full_zh"] = it["full_zh"]
        if it.get("content_blocks"):
            e["content_blocks"] = it["content_blocks"]
            e["content_format"] = it.get("content_format", "blocks-v1")
        for key in (
            "content_mode", "content_level", "source_language", "translation_status",
            "source_content_hash", "content_parse", "body_chars",
        ):
            if key in it:
                e[key] = it[key]
    e["vendors"] = list(dict.fromkeys(e.get("vendors", []) + it.get("vendors", [])))[:5]
    e["topics"] = [t for t in dict.fromkeys(e.get("topics", []) + it.get("topics", []))][:3]
    merged_tags = merge_work_tags(e.get("work_tags"), it.get("work_tags"))
    if merged_tags is not None:
        e["work_tags"] = merged_tags
    if it.get("shelf") == "evergreen":
        e["shelf"] = "evergreen"

# ── HN 信源 ───────────────────────────────────────────────
def fetch_hn_algolia(source):
    entries = []
    min_points = source.get("min_points", 30)
    for q in source.get("queries", []):
        url = ("https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=15&query="
               + urllib.parse.quote(q))
        hits = json.loads(fetch_url(url))["hits"]
        for h in hits:
            if (h.get("points") or 0) < min_points:
                continue
            entries.append({
                "title": h["title"],
                "link": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                "published": datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
                "summary": f"Hacker News 热帖 · {h.get('points',0)} 赞 · {h.get('num_comments',0)} 评论",
                "signal": h.get("points", 0),
            })
    seen_links, out = set(), []
    for e in entries:
        if e["link"] not in seen_links:
            seen_links.add(e["link"]); out.append(e)
    return out

# ── Bluesky 信源 ──────────────────────────────────────────
def bsky_session():
    """如配置了 BSKY_HANDLE / BSKY_APP_PASSWORD（环境变量或 config.json），创建认证会话"""
    handle = os.getenv("BSKY_HANDLE", "")
    passwd = os.getenv("BSKY_APP_PASSWORD", "")
    cfg_path = Path(__file__).resolve().parent / "config.json"
    if (not handle or not passwd) and cfg_path.exists():
        cfg = json.load(open(cfg_path))
        handle = handle or cfg.get("BSKY_HANDLE", "")
        passwd = passwd or cfg.get("BSKY_APP_PASSWORD", "")
    if not (handle and passwd):
        return None
    req = urllib.request.Request(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        data=json.dumps({"identifier": handle, "password": passwd}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["accessJwt"]

def fetch_bluesky(source):
    """Bluesky 搜索热门帖（数据社区一手信号）。搜索接口需要认证会话。"""
    token = bsky_session()
    if not token:
        raise RuntimeError("未配置 BSKY_HANDLE/BSKY_APP_PASSWORD（ Bluesky 免费 App Password 即可）")
    entries = []
    min_likes = source.get("min_likes", 10)
    since = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for q in source.get("queries", []):
        url = ("https://bsky.social/xrpc/app.bsky.feed.searchPosts?sort=top&limit=15"
               f"&since={since}&q=" + urllib.parse.quote(q))
        req = urllib.request.Request(url, headers={**UA, "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        for p in data.get("posts", []):
            likes = p.get("likeCount", 0)
            if likes < min_likes:
                continue
            rec = p.get("record", {})
            text = (rec.get("text") or "").strip()
            if not text:
                continue
            handle = p.get("author", {}).get("handle", "")
            rkey = p.get("uri", "").rstrip("/").split("/")[-1]
            post_link = f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else p.get("uri", "")
            # 原文解析：帖子引用的外部链接才是内容本体（解决"引用重合而原文未收录"）
            ext = (rec.get("embed") or {}).get("external", {}).get("uri")
            if not ext:
                for fac in rec.get("facets", []):
                    for feat in fac.get("features", []):
                        if feat.get("$type", "").endswith("#link") and str(feat.get("uri", "")).startswith("http"):
                            ext = feat["uri"]; break
                    if ext:
                        break
            link = ext or post_link
            entries.append({
                "title": text[:100],
                "link": link,
                "published": parse_date(rec.get("createdAt", "")),
                "summary": f"Bluesky 热帖 · @{handle} · {likes} 赞 · {text[:300]}" + (f" · 原帖 {post_link}" if ext else ""),
                "signal": likes,
            })
    seen_links, out = set(), []
    for e in entries:
        if e["link"] not in seen_links:
            seen_links.add(e["link"]); out.append(e)
    return out

def fetch_snowflake_rn(source):
    """Snowflake 文档站 Release Notes：索引页提取周更版本页链接，新版本页出现即为一个事件"""
    html_txt = fetch_url(source["url"], timeout=20).decode("utf-8", errors="ignore")
    links = set(re.findall(r'/en/release-notes/\d{4}/\d+_\d+', html_txt))
    # 只保留最近 6 个周版本（按 年/主版本/次版本 排序），避免首次运行洪水
    def vkey(path):
        import re as _re
        m = _re.search(r'(\d{4})/(\d+)_(\d+)', path)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0,0,0)
    links = sorted(links, key=vkey, reverse=True)[:6]
    entries = []
    for path in links:
        ver = path.rsplit("/", 1)[-1].replace("_", ".")
        entries.append({
            "title": f"Snowflake Release Notes v{ver}",
            "link": "https://docs.snowflake.com" + path,
            "published": None,  # 页面出现时间即抓取时间
            "summary": "Snowflake 每周版本发布说明",
            "_slug_title": True,  # 抓正文时用页面 <title> 细化
        })
    return entries

def fetch_html_list(source):
    """通用 HTML 列表页采集器：无 RSS/sitemap 的站点，从列表页提取文章链接与标题。
    发布日期由抓正文阶段的 meta 日期回填（extract_meta_date）。"""
    html_txt = fetch_url(source["url"], timeout=15).decode("utf-8", errors="ignore")
    link_re = source.get("link_re", r'href="(/[a-z0-9_/-]+\d{3,})"')
    title_re = source.get("title_re", r"<strong[^>]*>(.*?)</strong>")
    base = source.get("base", "")
    entries, seen = [], set()
    for m in re.finditer(r'<a\b[^>]*\bhref="' + link_re + r'"[^>]*>(.*?)</a>', html_txt, re.S | re.I):
        path, inner = m.group(1), m.group(2)
        if path in seen:
            continue
        tm = re.search(title_re, inner, re.S)
        title = strip_html(tm.group(1)) if tm else strip_html(inner)
        if not title:
            continue
        seen.add(path)
        entries.append({"title": title, "link": base + path, "published": None, "summary": "", "_slug_title": True})
    return entries[:PER_SOURCE_MAX]

def fetch_sitemap(source):
    """sitemap 信源：无 RSS 的官网，用 sitemap 的 URL+lastmod 作为更新流（标题由抓正文阶段从 <title> 补全）"""
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    entries = []
    include = source.get("url_include", "")
    for u in source.get("urls", []):
        root = fetch_feed(u)
        for url_el in root.iter(ns + "url"):
            loc_el = url_el.find(ns + "loc")
            if loc_el is None or not loc_el.text:
                continue
            if include and include not in loc_el.text:
                continue
            lm = url_el.find(ns + "lastmod")
            slug = loc_el.text.rstrip("/").split("/")[-1].replace("-", " ")
            entries.append({
                "title": slug, "link": loc_el.text,
                "published": parse_date(lm.text) if lm is not None and lm.text else None,
                "summary": "", "_slug_title": True,
            })
    return entries

# ── 主流程 ────────────────────────────────────────────────
def main():
    sources = [s for s in json.load(open(ROOT / "pipeline" / "sources.json")) if s.get("enabled")]
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=EVENT_RETENTION_DAYS)
    cfg = load_llm_config()

    DATA.mkdir(parents=True, exist_ok=True); ARCHIVE.mkdir(parents=True, exist_ok=True)
    latest_path = DATA / "latest.json"
    ss_path = DATA / "sources_status.json"
    ss = json.load(open(ss_path)) if ss_path.exists() else {}
    events = []
    if latest_path.exists():
        old = json.load(open(latest_path))
        if old.get("events"):
            events = old["events"]
        else:  # 旧版 items 结构迁移
            for i in old.get("items", []):
                events.append(make_event(i))
    article_ui_cleanup_summary = normalize_catalog_article_ui(events)
    if article_ui_cleanup_summary["cleaned_events"]:
        print(
            f"[content-ui] 清理 {article_ui_cleanup_summary['cleaned_events']} 篇 / "
            f"{article_ui_cleanup_summary['removed_blocks']} 个正文外页面组件块"
        )
    normalized_labels = normalize_category_labels(events)
    if normalized_labels:
        print(f"[taxonomy] 统一分类展示名 {normalized_labels} 条")
    # 周报优先使用上轮已完成的一周数据并抢先占用极小预算，避免内容审核
    # 与正文生成先耗尽单轮额度。周一 08:17 之前不会提前发布新一期。
    _brief, brief_status = generate_weekly_brief_for_events(events, cfg, now)
    print(f"[weekly-brief] {brief_status}")
    seen = {sub["id"] for e in events for sub in e["items"]}
    seen_urls = {norm_url(sub["link"]) for e in events for sub in e["items"]}
    url_to_event = {}
    for e in events:
        for sub in e["items"]:
            url_to_event[norm_url(sub["link"])] = e
    new_by_url = {}  # 本轮新增条目的 url 索引（同文多帖信号叠加）

    new_items, source_status = [], []
    feed_content_by_url = {}
    for s in sources:
        control = source_control_snapshot(s)
        due, schedule_reason = source_due(s, ss.get(s["name"], {}), now)
        if not due:
            source_status.append({
                "name": s["name"], "ok": True, "new": 0, "skipped": True,
                "skip_reason": schedule_reason, "control": control,
            })
            print(f"[schedule] {s['name']:28s} 跳过（{schedule_reason}）")
            continue
        try:
            if s.get("kind") == "hn_algolia":
                entries = fetch_hn_algolia(s)
            elif s.get("kind") == "bluesky":
                entries = fetch_bluesky(s)
            elif s.get("kind") == "sitemap":
                entries = fetch_sitemap(s)
            elif s.get("kind") == "html_list":
                entries = fetch_html_list(s)
            elif s.get("kind") == "snowflake_rn":
                entries = fetch_snowflake_rn(s)
            else:
                entries = parse_feed(fetch_feed(s["url"]), s)
            entries, filter_stats = prefilter_entries(entries, s, now)
            candidate_limit = source_candidate_limit(s, PER_SOURCE_MAX)
            kept = 0
            skipped_seen = 0
            limit_reached = False
            for e in entries:
                if e.get("feed_content_html"):
                    feed_content_by_url[norm_url(e["link"])] = e["feed_content_html"]
                iid = hashlib.md5(e["link"].encode()).hexdigest()[:12]
                if iid in seen:
                    skipped_seen += 1
                    continue
                nurl = norm_url(e["link"])
                if nurl in seen_urls:
                    # 同文合流：已收录的老事件 → 追加信源；本轮新条目 → 叠加社区信号
                    tgt = url_to_event.get(nurl)
                    if tgt is not None:
                        pub0 = e["published"].astimezone(TZ) if e["published"] else now.astimezone(TZ)
                        tgt["items"].append({"id": iid, "source": s["name"], "link": e["link"],
                                             "published": pub0.isoformat(), "title": e["title"]})
                        tgt["signal"] = max(tgt.get("signal", 0), e.get("signal", 0))
                        tgt["published"] = max(tgt["published"], pub0.isoformat())
                        recalc_event_heat(tgt)
                        print(f"[merge-src] {s['name']} 的同文报道并入: {tgt['zh_title'][:30]}")
                    elif nurl in new_by_url:
                        prev = new_by_url[nurl]
                        prev["signal"] = prev.get("signal", 0) + e.get("signal", 0)
                    skipped_seen += 1
                    continue
                if kept >= candidate_limit:
                    limit_reached = True
                    break
                seen.add(iid); seen_urls.add(nurl)
                pub_dt = e["published"] or now
                if pub_dt > now + timedelta(hours=2):  # 信源排期导致的未来时间 → 钳到抓取时间
                    print(f"[date] 未来发布时间钳制: {e['title'][:40]} ({pub_dt} → {now})")
                    pub_dt = now
                pub_iso = pub_dt.astimezone(TZ).isoformat() if e["published"] else None
                new_items.append({
                    "id": iid, "title": e["title"], "zh_title": e["title"],
                    "summary": e.get("summary", "")[:600], "zh_summary": e.get("summary", "")[:300],
                    "feed_content_html": e.get("feed_content_html", ""),
                    "reason": "", "link": e["link"],
                    "source": s["name"], "source_type": s["type"],
                    "source_tier": s.get("tier", "default"),
                    "category": "platform", "category_label": "AI 数据平台",
                    "vendors": VENDOR_TAGS.get(s["name"], []),
                    "vendor_default": s["type"] == "vendor",
                    "published": pub_iso, "ingested_at": now.astimezone(TZ).isoformat(), "_pub_dt": pub_dt,
                    "signal": e.get("signal", 0), "importance": 50,
                    "quality_score": 50,
                    "trend_score": calc_trend_score(pub_dt, e.get("signal", 0)),
                    "topics": [],
                    "_slug_title": e.get("_slug_title", False),
                    "heat": calc_heat(50, pub_dt, e.get("signal", 0)),
                    "star": False,  # 精选由 LLM 加工时按重要性判定
                    "article_text": "",
                })
                new_by_url[nurl] = new_items[-1]
                kept += 1
            source_status.append({
                "name": s["name"], "ok": True, "new": kept,
                "fetched": filter_stats["fetched"],
                "eligible": filter_stats["eligible"],
                "prefiltered": filter_stats["prefiltered"],
                "prefilter_dropped": filter_stats["dropped"],
                "skipped_seen": skipped_seen,
                "limit_reached": limit_reached,
                "schedule_reason": schedule_reason,
                "control": control,
            })
            print(
                f"[fetch] {s['name']:28s} 原始 {filter_stats['fetched']} | "
                f"预筛后 {filter_stats['eligible']} | 新增 {kept}"
            )
        except Exception as e:
            source_status.append({
                "name": s["name"], "ok": False, "error": str(e),
                "schedule_reason": schedule_reason, "control": control,
            })
            print(f"[fetch] {s['name']:28s} 失败: {e}")

    # 事件主来源的正文抓取；新流程不再抓取每个重复报道。
    def grab(it):
        text, page_title, meta_date, blocks, parse_report = fetch_article_content(
            it["link"], include_report=True,
        )
        text, blocks, parse_report = prefer_rss_article_content(
            text, blocks, parse_report, it.get("feed_content_html"), it["link"],
        )
        it["article_text"] = text
        it["article_blocks"] = blocks
        it["_article_parse"] = parse_report
        if it.get("_slug_title") and page_title:
            it["title"] = page_title
            it["zh_title"] = page_title
        # 发布时间覆盖：无日期的条目用页面 meta 日期回填（优先于抓取时间）
        if not it.get("published") and meta_date and meta_date <= datetime.now(timezone.utc) + timedelta(days=1):
            it["published"] = meta_date.astimezone(TZ).isoformat()
            it["_pub_dt"] = meta_date
            print(f"[date] meta 回填发布时间: {meta_date.date()} | {it['title'][:30]}")
        return it

    source_configs = {source["name"]: source for source in sources}
    pipeline_order = os.getenv("PIPELINE_ORDER", "event_first").strip().lower()
    if pipeline_order == "legacy":
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(grab, new_items))
        got = sum(1 for it in new_items if it["article_text"])
        print(f"[article] 旧流程正文抓取成功 {got}/{len(new_items)}")
        new_items = llm_enrich(new_items, cfg, generate_fulltext=False)
        events = cluster_events(new_items, events, cfg, late_merge=True)
        legacy_body_state = {"original": 0, "translated": 0, "fallback": 0}
        for primary in new_items:
            target = next(
                (
                    event for event in events
                    if any(item.get("id") == primary["id"] for item in event.get("items", []))
                ),
                None,
            )
            if target is not None:
                generate_event_body(
                    target, primary, cfg, legacy_body_state,
                    media_policy=source_media_policy(primary.get("source", ""), source_configs),
                )
    else:
        # 元数据 → 候选缓存 → 规则初筛 → 当轮聚簇 → 主来源 → 元数据加工 → 事件正文
        new_items = precheck_candidate_cache(new_items, cfg)
        new_items = rule_prefilter_candidates(new_items)
        groups = group_candidate_items(new_items, cfg)
        group_records = [
            (group, select_primary_source(group, source_configs)) for group in groups
        ]
        primaries = [primary for _group, primary in group_records]
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(grab, primaries))
        got = sum(1 for item in primaries if item.get("article_text"))
        print(
            f"[article] 事件主来源抓取成功 {got}/{len(primaries)} "
            f"（候选 {len(new_items)} 条 / 事件组 {len(groups)} 个）"
        )
        enriched_primaries = llm_enrich(primaries, cfg, generate_fulltext=False)
        enriched_by_id = {item["id"]: item for item in enriched_primaries}
        accepted_items = []
        accepted_records = []
        model = cfg[2]
        for group, primary in group_records:
            enriched = enriched_by_id.get(primary["id"])
            if enriched is None:
                if model:
                    for sibling in group:
                        if sibling is primary:
                            continue
                        CANDIDATE_CACHE.remember(
                            **_candidate_cache_context(sibling, model), status="rejected",
                        )
                continue
            enrichment = _cacheable_enrichment(enriched)
            if model and enriched.get("_enrich_error"):
                for sibling in group:
                    if sibling is primary:
                        continue
                    CANDIDATE_CACHE.remember(
                        **_candidate_cache_context(sibling, model), status="error",
                        error_type=enriched["_enrich_error"],
                    )
            elif model:
                for sibling in group:
                    if sibling is primary:
                        continue
                    CANDIDATE_CACHE.remember(
                        **_candidate_cache_context(sibling, model), status="accepted",
                        enrichment=enrichment,
                    )
            accepted_items.extend(group)
            accepted_records.append((group, enriched))

        events = cluster_events(enriched_primaries, events, cfg, late_merge=False)
        # 正文分级前先应用人工策展，确保置顶事件获得深度资格。
        cur_path = ROOT / "pipeline" / "classics.json"
        if cur_path.exists():
            cur = json.load(open(cur_path))
            for event in events:
                if event["event_id"] in cur.get("pin", []):
                    event["shelf"], event["pinned"] = "evergreen", True
                if event["event_id"] in cur.get("drop", []):
                    event["shelf"], event["pinned"] = "news", False
        body_state = {"original": 0, "translated": 0, "fallback": 0}
        for group, primary in accepted_records:
            event = next(
                (
                    event for event in events
                    if any(item.get("id") == primary["id"] for item in event.get("items", []))
                ),
                None,
            )
            if event is None:
                continue
            merge_group_sources(event, group, primary)
            generate_event_body(
                event, primary, cfg, body_state,
                media_policy=source_media_policy(primary.get("source", ""), source_configs),
            )
        new_items = accepted_items
        print(
            f"[pipeline] event_first 接受 {len(new_items)} 条，"
            f"原文 {body_state['original']} / 忠实译文 {body_state['translated']} / "
            f"降级 {body_state['fallback']} 个"
        )

    metadata_backfill_summary = backfill_event_metadata(events, cfg, now=now)
    backfill_summary = backfill_structured_content(
        events, cfg, now=now, feed_content_by_url=feed_content_by_url,
        source_configs=source_configs,
    )
    media_refresh_summary = refresh_media_cache(events, source_configs)
    run_structured = structured_content_metrics(events, run_id=LLM_USAGE.run_id)
    run_structured["catalog"] = catalog_content_metrics(events)
    run_structured["metadata_backfill"] = metadata_backfill_summary
    run_structured["backfill"] = backfill_summary
    run_structured["media_refresh"] = media_refresh_summary
    run_structured["article_ui_cleanup"] = article_ui_cleanup_summary
    write_structured_content_summary(run_structured)
    print(
        f"[structured] ready {run_structured['ready']}/{run_structured['attempted']} | "
        f"图 {run_structured['figures']} 表 {run_structured['tables']} | "
        f"缓存 {run_structured['media_cached']}"
    )

    # 信源状态持久化：连续失败计数 + 抓取/入选计数（入选率 = 信源质量记分牌）
    from collections import Counter as _Counter
    accepted = _Counter(it["source"] for it in new_items)
    accepted_categories = accepted_categories_by_source(
        events, (item["id"] for item in new_items),
    )
    now_iso = now.astimezone(TZ).isoformat()
    llm_by_source = LLM_USAGE.snapshot().get("by_source", {})
    for st in source_status:
        rec = ss.get(st["name"], {})
        rec["last_run"] = now_iso
        rec["ok"] = st["ok"]
        rec["control"] = st.get("control", {})
        rec["last_schedule_reason"] = st.get("skip_reason") or st.get("schedule_reason", "")
        rec["last_structured_content"] = run_structured.get("by_source", {}).get(
            st["name"],
            {"attempted": 0, "ready": 0, "figures": 0, "tables": 0, "media_cached": 0},
        )
        if st.get("skipped"):
            rec["last_skipped"] = now_iso
            rec["last_new"] = 0
            rec["last_model_calls"] = 0
            rec["last_model_tokens"] = 0
            rec["last_accepted_by_category"] = {}
            ss[st["name"]] = rec
            continue
        rec["last_attempt"] = now_iso
        if st["ok"]:
            rec["last_ok"] = now_iso
            rec["last_fetch"] = now_iso
            rec["fails"] = 0
            rec["total_fetched"] = rec.get("total_fetched", 0) + st.get("new", 0)
            rec["total_accepted"] = rec.get("total_accepted", 0) + accepted.get(st["name"], 0)
            rec["total_raw_entries"] = rec.get("total_raw_entries", 0) + st.get("fetched", 0)
            rec["total_prefiltered"] = rec.get("total_prefiltered", 0) + st.get("prefiltered", 0)
            rec["last_new"] = st.get("new", 0)
            rec["last_raw_entries"] = st.get("fetched", 0)
            rec["last_eligible"] = st.get("eligible", 0)
            rec["last_prefiltered"] = st.get("prefiltered", 0)
            rec["last_prefilter_dropped"] = st.get("prefilter_dropped", {})
            rec["last_skipped_seen"] = st.get("skipped_seen", 0)
            rec["last_limit_reached"] = bool(st.get("limit_reached"))
            usage = llm_by_source.get(st["name"], {})
            rec["last_model_calls"] = int(usage.get("calls", 0))
            rec["last_model_tokens"] = int(usage.get("total_tokens", 0))
            rec["total_model_calls"] = rec.get("total_model_calls", 0) + rec["last_model_calls"]
            rec["total_model_tokens"] = rec.get("total_model_tokens", 0) + rec["last_model_tokens"]
            accepted_now = accepted.get(st["name"], 0)
            rec["last_accepted"] = accepted_now
            category_now = accepted_categories.get(st["name"], {})
            rec["last_accepted_by_category"] = category_now
            category_totals = dict(rec.get("total_accepted_by_category") or {})
            for category, count in category_now.items():
                category_totals[category] = int(category_totals.get(category, 0)) + int(count)
            rec["total_accepted_by_category"] = category_totals
            if st.get("new", 0) > 0 and accepted_now == 0:
                rec["zero_accept_streak"] = rec.get("zero_accept_streak", 0) + 1
            elif accepted_now > 0:
                rec["zero_accept_streak"] = 0
            total_candidates = rec.get("total_fetched", 0)
            rec["acceptance_rate"] = (
                round(rec.get("total_accepted", 0) / total_candidates, 4)
                if total_candidates else 0
            )
            if rec.get("zero_accept_streak", 0) >= 3:
                rec["recommendation"] = (
                    f"连续 {rec['zero_accept_streak']} 轮零采用，建议增大抓取间隔或收紧预筛；不自动停用"
                )
            else:
                rec.pop("recommendation", None)
        else:
            rec["fails"] = rec.get("fails", 0) + 1
            rec["error"] = st.get("error", "")[:120]
        ss[st["name"]] = rec
    json.dump(ss, open(ss_path, "w"), ensure_ascii=False, indent=1)

    # 人工策展：classics.json 的 pin（强制长期保留）/ drop（撤下）
    cur_path = ROOT / "pipeline" / "classics.json"
    if cur_path.exists():
        cur = json.load(open(cur_path))
        for e in events:
            if e["event_id"] in cur.get("pin", []):
                e["shelf"], e["pinned"] = "evergreen", True
            if e["event_id"] in cur.get("drop", []):
                e["shelf"], e["pinned"] = "news", False

    # 清理过期：news 7 天淘汰；evergreen 作为长期内容永久保留
    events = [e for e in events if should_retain_event(e, cutoff=cutoff)]
    media_prune = prune_media_cache((event["event_id"] for event in events), SITE)
    if media_prune["removed_dirs"]:
        print(
            f"[media] 清理过期事件目录 {media_prune['removed_dirs']} 个 / "
            f"{media_prune['removed_bytes']} bytes"
        )

    # 热度分 3.0：全量重算（按真实发布时间与 48 小时半衰期自然降温）
    for e in events:
        recalc_event_heat(e, reference_time=now)

    top = [
        e["event_id"] for e in rank_hot_events(
            events, limit=3, source_cap=2, reference_time=now,
        )
    ]
    events.sort(key=lambda e: (e.get("first_seen") or e["published"] or ""), reverse=True)

    payload = {
        "generated_at": now.astimezone(TZ).isoformat(),
        "events": events, "top": top, "sources": source_status,
        "structured_content": run_structured,
    }
    json.dump(payload, open(latest_path, "w"), ensure_ascii=False, indent=1)
    json.dump(payload, open(ARCHIVE / (now.astimezone(TZ).strftime("%Y-%m-%d-%H%M") + ".json"), "w"),
              ensure_ascii=False, indent=1)
    n_sub = sum(len(e["items"]) for e in events)
    print(f"[done] 事件 {len(events)} 个（含条目 {n_sub} 条），本次新增 {len(new_items)} 条")

if __name__ == "__main__":
    try:
        main()
    finally:
        CLUSTER_CACHE.finalize()
        print(CLUSTER_CACHE.one_line_summary())
        CANDIDATE_CACHE.finalize()
        print(CANDIDATE_CACHE.one_line_summary())
        LLM_USAGE.finalize()
        print(LLM_USAGE.one_line_summary())
