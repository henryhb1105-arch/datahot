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

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DATA = SITE / "data"
ARCHIVE = DATA / "archive"
KEEP_DAYS = 7
PER_SOURCE_MAX = 20
TZ = timezone(timedelta(hours=8))

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
      "Accept": "application/rss+xml,application/xml,text/xml,*/*"}

socket.setdefaulttimeout(20)

CATEGORIES_LABEL = dict(agent="Data Agent", platform="AI 数据平台", bi="BI 与可视化", product="数据产品")

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
    "Microsoft Power BI（Power Platform Blog）": ["Microsoft", "Power BI"],
    "Tableau Engineering（Medium）": ["Tableau"],
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
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        pass
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
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

def parse_feed(root_el, source):
    items = []
    for it in root_el.iter("item"):
        items.append({
            "title": strip_html(text_of(it, "title")),
            "link": text_of(it, "link").strip(),
            "published": parse_date(text_of(it, "pubDate", "published", "updated", "date")),
            "summary": strip_html(text_of(it, "description", "summary", "encoded")),
        })
    ns = "{http://www.w3.org/2005/Atom}"
    for it in root_el.iter(ns + "entry"):
        link = ""
        for l in it.iter(ns + "link"):
            if l.get("href") and (l.get("rel") in (None, "alternate")):
                link = l.get("href"); break
        items.append({
            "title": strip_html(text_of(it, ns + "title")),
            "link": link,
            "published": parse_date(text_of(it, ns + "published", ns + "updated")),
            "summary": strip_html(text_of(it, ns + "summary", ns + "content")),
        })
    return [i for i in items if i["title"] and i["link"]][:PER_SOURCE_MAX]

import math

def freshness(published):
    """时间新鲜度 0.3~1.0：7 天内线性衰减"""
    if not published:
        return 0.5
    age_h = (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 3600
    return max(0.3, 1 - age_h / (KEEP_DAYS * 24) * 0.7)

def community_score(signal):
    """社区信号（HN 赞数 / Bluesky 赞数）对数归一到 0-100，1000 赞 ≈ 满分"""
    if not signal or signal <= 0:
        return 0
    return min(100, round(math.log1p(signal) / math.log1p(1000) * 100))

def calc_heat(importance=50, published=None, signal=0, extra_sources=0):
    """热度分 2.1：LLM重要性×0.5 + 新鲜度×0.2 + 社区信号×0.15(封顶12分) + 多信源×0.15，归一 0-100。
    设计原则：社区信号只做加分项不做主驾驶；多信源交叉验证比点赞数更可信。"""
    multi = min(100, 25 * extra_sources)
    comm = min(12, 0.15 * community_score(signal))
    return round(min(100,
        0.5 * importance + 0.2 * freshness(published) * 100
        + comm + 0.15 * multi))

# ── F5：HN 条目抓原文 ──────────────────────────────────────
def fetch_article_text(url, max_chars=24000):
    """粗提取网页正文：去脚本/样式/标签，取前 max_chars 字符；同时返回 <title>"""
    try:
        raw = fetch_url(url, timeout=10)
        try:
            html_txt = raw.decode("utf-8", errors="ignore")
        except Exception:
            return "", ""
        title = ""
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_txt)
        if m:
            title = strip_html(m.group(1))
            title = re.split(r"[|｜_-]{1,2}\s*(?:Aloudata|官网|博客).*$", title)[0].strip() or title
        text = re.sub(r"(?is)<(script|style|noscript|nav|footer|header)[^>]*>.*?</\1>", " ", html_txt)
        text = strip_html(text)
        return (text[:max_chars] if len(text) > 400 else ""), title
    except Exception:
        return "", ""

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

def llm_chat(base, key, model, prompt, timeout=120, max_tokens=None):
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        content = json.loads(r.read())["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.S)
    return json.loads(m.group(0), strict=False) if m else {}  # strict=False 容忍编译稿中的原始换行

# ── 全文编译引擎（忠实编译，非摘要）─────────────────────────
COMPILE_RULES = """你是数据领域垂直资讯站的专业编译。把下面的原文编译为面向数据从业者的中文全文编译稿。要求：
1. 完整保留原文的信息、论证过程、关键事实、案例、数据、步骤与结论；不随意省略关键段落、数字、人物、公司、产品与技术细节。
2. 保留原文的结构与逻辑顺序，用「## 」开头的小标题和自然段呈现（小标题据原文标题直译或概括）。
3. 这是全文编译，不是摘要：目标长度约为原文的 40%-70%，宁可长也不可漏。
4. 严格忠于原文，不得编造、补写或评论。若某处原文无法读取或不完整，用【此处原文未能完整读取】标注，不得自行补写。
5. 原文中的导航、订阅框、相关阅读推荐等网页杂质，直接忽略。
只输出编译稿正文（纯文本，段落间两个换行，小标题以「## 」开头）。"""

def compile_fulltext(title, source_text, cfg):
    """忠实编译：短文单遍，长文按段落分块编译后拼接"""
    key, base, model = cfg
    if not (key and base and model and source_text):
        return ""
    src = source_text[:22000]
    if len(src) <= 6000:
        return llm_chat_text(base, key, model,
            COMPILE_RULES + "\n\n【原文标题】" + title + "\n\n" + src, max_tokens=6000)
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
            part = llm_chat_text(base, key, model,
            COMPILE_RULES + f"\n\n注意：这是文章的第 {i}/{len(chunks)} 部分，只编译本部分的可见内容；若开头或结尾句子被切断，编译可见部分即可，不得补写上下文。\n\n【原文标题】" + title + "\n\n" + ch,
            max_tokens=8000)
            if part.strip():
                return part.strip()
        return ""
    from concurrent.futures import ThreadPoolExecutor as _TPE
    with _TPE(max_workers=4) as pool:
        parts = list(pool.map(compile_chunk, enumerate(chunks, 1)))
    if len(cur) > len(chunks[-1] if chunks else "") and len(chunks) >= 6:
        parts.append("【此处原文未能完整读取：文章过长，仅编译前 6 部分】")
    return "\n\n".join(p for p in parts if p)

def llm_chat_text(base, key, model, prompt, max_tokens=4096):
    """纯文本版 LLM 调用（编译稿不走 JSON 解析）"""
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                         "max_tokens": max_tokens}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()

# ── F4：加固的相关性过滤 + AI 加工 ─────────────────────────
ENRICH_RULES = """你是一个数据领域垂直资讯站的编辑。本站只覆盖四个领域：Data Agent（ChatBI/Text-to-SQL/分析Agent）、AI数据平台（数仓/湖仓/语义层/数据集成治理）、BI与可视化（BI工具/报表）、数据产品（方法论/融资并购/行业报告）。

【相关性硬规则】
- 注意：dbt 指数据工具 dbt Labs；心理疗法 DBT（辩证行为疗法）等无关内容一律 false
- 仅当内容直接涉及上述领域时 relevant=true
- 泛AI新闻一律 false：AI消费应用、AI硬件、AI政策八卦、模型发布（与数据场景无关）、AI音乐/绘画/社交等
- 数据分析/数据库/数据基础设施的融资并购、产品发布、技术实践 → true

【示例】
标题 "Databricks launches new semantic layer" → {"relevant": true, ...}
标题 "OpenAI 发布新款AI智能音箱" → {"relevant": false}
标题 "Airbnb 测试 AI 搜索功能" → {"relevant": false}

输出 JSON（不要输出多余内容）：
{"relevant": true或false, "zh_title": "中文标题(≤40字)", "zh_summary": "中文摘要3-4句，保留产品名与数字，不得编造原文没有的信息", "reason": "推荐理由：为什么数据从业者应关注，1-2句", "category": "agent|platform|bi|product", "shelf": "news 或 evergreen（方法论/框架/深度实践/报告解读等半年后仍值得读的标 evergreen，发布/融资/版本更新等时效内容标 news）", "topics": ["从主题词表选0-2个：ChatBI/Data Agent/语义层/平台AI化/BI变局/湖仓/实时分析/数据人，没有合适的就空数组，宁缺毋滥"], "vendors": ["提到的数据厂商，如Snowflake/Databricks/PowerBI/帆软等，没有则空数组"], "importance": 1-100整数}"""

def llm_enrich(items, cfg):
    key, base, model = cfg
    if not (key and base and model):
        print("[llm] 未配置 LLM，跳过 AI 加工")
        return items

    def enrich_one(it):
        content = f"标题：{it['title']}\n摘要：{it['summary'][:800]}"
        if it.get("article_text"):
            content += f"\n原文：{it['article_text'][:2200]}"
        note = "\n（注：该条目来自数据领域厂商官方博客，默认相关，除非明显是招聘/活动/公关软文）" if it.get("vendor_default") else ""
        out = llm_chat(base, key, model, ENRICH_RULES + "\n\n" + content + note)
        if out.get("relevant") is False:
            return None
        it["zh_title"] = out.get("zh_title") or it["title"]
        it["zh_summary"] = out.get("zh_summary") or it["summary"][:300]
        it["reason"] = out.get("reason", "")
        it["full_zh"] = compile_fulltext(it["zh_title"], it.get("article_text") or it.get("summary", ""), cfg)
        cat = out.get("category")
        if cat in CATEGORIES_LABEL:
            it["category"], it["category_label"] = cat, CATEGORIES_LABEL[cat]
        llm_vendors = [v for v in (out.get("vendors") or []) if isinstance(v, str) and v.strip()]
        it["vendors"] = list(dict.fromkeys(it.get("vendors", []) + llm_vendors))[:5]
        it["topics"] = [t for t in (out.get("topics") or []) if t in TOPIC_NAMES][:2]
        it["shelf"] = out.get("shelf") if out.get("shelf") in ("news", "evergreen") else "news"
        it["importance"] = int(out.get("importance", 50))
        it["heat"] = calc_heat(it["importance"], it.get("_pub_dt"), it.get("signal", 0))
        return it

    kept = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(enrich_one, it): it for it in items}
        for fut, it in futures.items():
            try:
                res = fut.result()
                if res is None:
                    print(f"[llm] 不相关，剔除: {it['title'][:50]}")
                else:
                    kept.append(res)
            except Exception as e:
                print(f"[llm] 加工失败（保留原文）: {e} | {it['title'][:40]}")
                kept.append(it)
    return kept

# ── F1：事件聚簇 ──────────────────────────────────────────
def title_bigrams(t):
    t = re.sub(r"[^\w一-鿿]+", "", (t or "").lower())
    return {t[i:i+2] for i in range(len(t) - 1)} if len(t) > 1 else {t} if t else set()

def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def llm_same_event(pairs, cfg):
    """pairs: [(a_desc, b_desc), ...] → [bool]"""
    key, base, model = cfg
    if not (key and base and model):
        return [False] * len(pairs)
    def judge(p):
        try:
            out = llm_chat(base, key, model,
                "判断以下两条资讯是否报道同一事件/同一产品发布（同一事件的不同媒体报道算同一事件）。"
                "注意：月度汇总/盘点类文章与其中提到的单项功能发布不算同一事件，除非该功能就是这篇文章的主题。"
                '只输出JSON {"same": true或false}。\n\n'
                f"【A】{p[0][:400]}\n【B】{p[1][:400]}")
            return out.get("same") is True
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

def cluster_events(new_items, events, cfg):
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
    changed = True
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
                        a["importance"] = max(a.get("importance", 50), b.get("importance", 50))
                        a["signal"] = max(a.get("signal", 0), b.get("signal", 0))
                        recalc_event_heat(a)
                        a["vendors"] = list(dict.fromkeys(a.get("vendors", []) + b.get("vendors", [])))[:5]
                        events.pop(j)
                        print(f"[cluster] 合并事件: {b['zh_title'][:30]} → {a['zh_title'][:30]}")
                        changed = True
                        break
            if changed:
                break
    return events

def make_event(it):
    eid = hashlib.md5(norm_url(it["link"]).encode()).hexdigest()[:12]
    return {
        "event_id": eid,
        "zh_title": it["zh_title"], "zh_summary": it["zh_summary"], "reason": it.get("reason", ""),
        "full_zh": it.get("full_zh", ""),
        "category": it["category"], "category_label": it["category_label"],
        "vendors": it.get("vendors", []), "heat": it["heat"], "star": it.get("star", False),
        "importance": it.get("importance", 50), "signal": it.get("signal", 0),
        "topics": it.get("topics", []), "shelf": it.get("shelf", "news"),
        "pinned": it.get("pinned", False),
        "published": it["published"],
        "items": [{"id": it["id"], "source": it["source"], "link": it["link"],
                   "published": it["published"], "title": it["title"]}],
    }

def recalc_event_heat(e):
    """事件热度 = calc_heat(最高重要性, 最新发布时间, 最强社区信号, 信源数-1)"""
    pub = datetime.fromisoformat(e["published"])
    e["heat"] = calc_heat(e.get("importance", 50), pub, e.get("signal", 0), len(e["items"]) - 1)

def merge_into(e, it):
    e["items"].append({"id": it["id"], "source": it["source"], "link": it["link"],
                       "published": it["published"], "title": it["title"]})
    e["published"] = max(e["published"], it["published"])
    e["importance"] = max(e.get("importance", 50), it.get("importance", 50))
    e["signal"] = max(e.get("signal", 0), it.get("signal", 0))
    recalc_event_heat(e)
    if len(it.get("zh_summary", "")) > len(e.get("zh_summary", "")):
        e["zh_summary"], e["reason"] = it["zh_summary"], it.get("reason", e["reason"])
    if len(it.get("full_zh", "")) > len(e.get("full_zh", "")):
        e["full_zh"] = it["full_zh"]
    e["vendors"] = list(dict.fromkeys(e.get("vendors", []) + it.get("vendors", [])))[:5]
    e["topics"] = [t for t in dict.fromkeys(e.get("topics", []) + it.get("topics", []))][:3]
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
    cutoff = now - timedelta(days=KEEP_DAYS)
    cfg = load_llm_config()

    DATA.mkdir(parents=True, exist_ok=True); ARCHIVE.mkdir(parents=True, exist_ok=True)
    latest_path = DATA / "latest.json"
    events = []
    if latest_path.exists():
        old = json.load(open(latest_path))
        if old.get("events"):
            events = old["events"]
        else:  # 旧版 items 结构迁移
            for i in old.get("items", []):
                events.append(make_event(i))
    seen = {sub["id"] for e in events for sub in e["items"]}
    seen_urls = {norm_url(sub["link"]) for e in events for sub in e["items"]}
    url_to_event = {}
    for e in events:
        for sub in e["items"]:
            url_to_event[norm_url(sub["link"])] = e
    new_by_url = {}  # 本轮新增条目的 url 索引（同文多帖信号叠加）

    new_items, source_status = [], []
    for s in sources:
        try:
            if s.get("kind") == "hn_algolia":
                entries = fetch_hn_algolia(s)
            elif s.get("kind") == "bluesky":
                entries = fetch_bluesky(s)
            elif s.get("kind") == "sitemap":
                entries = fetch_sitemap(s)
            elif s.get("kind") == "snowflake_rn":
                entries = fetch_snowflake_rn(s)
            else:
                entries = parse_feed(fetch_feed(s["url"]), s)
            kept = 0
            for e in entries:
                if e["published"] and e["published"] < cutoff:
                    continue
                iid = hashlib.md5(e["link"].encode()).hexdigest()[:12]
                if iid in seen:
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
                    continue
                seen.add(iid); seen_urls.add(nurl)
                pub = e["published"].astimezone(TZ) if e["published"] else now.astimezone(TZ)
                pub_dt = e["published"] or now
                new_items.append({
                    "id": iid, "title": e["title"], "zh_title": e["title"],
                    "summary": e["summary"][:600], "zh_summary": e["summary"][:300],
                    "reason": "", "link": e["link"],
                    "source": s["name"], "source_type": s["type"],
                    "category": "platform", "category_label": "AI 数据平台",
                    "vendors": VENDOR_TAGS.get(s["name"], []),
                    "vendor_default": s["type"] == "vendor",
                    "published": pub.isoformat(), "_pub_dt": pub_dt,
                    "signal": e.get("signal", 0), "importance": 50, "topics": [],
                    "_slug_title": e.get("_slug_title", False),
                    "heat": calc_heat(50, pub_dt, e.get("signal", 0)),
                    "star": s["type"] == "vendor" and s["weight"] >= 3,
                    "article_text": "",
                })
                new_by_url[nurl] = new_items[-1]
                kept += 1
            source_status.append({"name": s["name"], "ok": True, "new": kept})
            print(f"[fetch] {s['name']:28s} 新增 {kept} 条")
        except Exception as e:
            source_status.append({"name": s["name"], "ok": False, "error": str(e)})
            print(f"[fetch] {s['name']:28s} 失败: {e}")

    # F5+：全部新条目抓原文正文（用于摘要质量 + AI 全文编译），并发执行
    def grab(it):
        text, page_title = fetch_article_text(it["link"])
        it["article_text"] = text
        if it.get("_slug_title") and page_title:
            it["title"] = page_title
            it["zh_title"] = page_title
        return it
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(grab, new_items))
    got = sum(1 for it in new_items if it["article_text"])
    print(f"[article] 正文抓取成功 {got}/{len(new_items)}")

    # F4：LLM 加工
    new_items = llm_enrich(new_items, cfg)

    # F1：聚簇
    events = cluster_events(new_items, events, cfg)

    # 信源状态持久化：连续失败计数 + 抓取/入选计数（入选率 = 信源质量记分牌）
    from collections import Counter as _Counter
    accepted = _Counter(it["source"] for it in new_items)
    ss_path = DATA / "sources_status.json"
    ss = json.load(open(ss_path)) if ss_path.exists() else {}
    now_iso = now.astimezone(TZ).isoformat()
    for st in source_status:
        rec = ss.get(st["name"], {})
        rec["last_run"] = now_iso
        rec["ok"] = st["ok"]
        if st["ok"]:
            rec["last_ok"] = now_iso
            rec["fails"] = 0
            rec["total_fetched"] = rec.get("total_fetched", 0) + st.get("new", 0)
            rec["total_accepted"] = rec.get("total_accepted", 0) + accepted.get(st["name"], 0)
            rec["last_new"] = st.get("new", 0)
        else:
            rec["fails"] = rec.get("fails", 0) + 1
            rec["error"] = st.get("error", "")[:120]
        ss[st["name"]] = rec
    json.dump(ss, open(ss_path, "w"), ensure_ascii=False, indent=1)

    # 人工策展：classics.json 的 pin（强制典藏）/ drop（撤下）
    cur_path = ROOT / "pipeline" / "classics.json"
    if cur_path.exists():
        cur = json.load(open(cur_path))
        for e in events:
            if e["event_id"] in cur.get("pin", []):
                e["shelf"], e["pinned"] = "evergreen", True
            if e["event_id"] in cur.get("drop", []):
                e["shelf"], e["pinned"] = "news", False

    # 清理过期：news 7 天淘汰；evergreen 永久沉淀（典藏池）
    events = [e for e in events
              if datetime.fromisoformat(e["published"]) > cutoff or e.get("shelf") == "evergreen"]

    # 热度分 2.0：全量重算（新鲜度随时间衰减，分数每天自然"降温"）
    for e in events:
        recalc_event_heat(e)

    top = [e["event_id"] for e in sorted(events, key=lambda e: -e["heat"])[:3]]
    events.sort(key=lambda e: e["published"], reverse=True)

    payload = {
        "generated_at": now.astimezone(TZ).isoformat(),
        "events": events, "top": top, "sources": source_status,
    }
    json.dump(payload, open(latest_path, "w"), ensure_ascii=False, indent=1)
    json.dump(payload, open(ARCHIVE / (now.astimezone(TZ).strftime("%Y-%m-%d-%H%M") + ".json"), "w"),
              ensure_ascii=False, indent=1)
    n_sub = sum(len(e["items"]) for e in events)
    print(f"[done] 事件 {len(events)} 个（含条目 {n_sub} 条），本次新增 {len(new_items)} 条")

if __name__ == "__main__":
    main()
