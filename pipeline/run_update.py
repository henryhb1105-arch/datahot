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

VENDOR_TAGS = {
    "Databricks Blog": ["Databricks"], "dbt Blog": ["dbt Labs"],
    "ThoughtSpot Blog": ["ThoughtSpot"], "Metabase Blog": ["Metabase"],
    "ClickHouse Blog": ["ClickHouse"], "AWS Big Data Blog": ["AWS"],
    "Fivetran Blog": ["Fivetran"], "StarRocks Blog": ["StarRocks"],
}

# ── 基础工具 ──────────────────────────────────────────────
def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return html.unescape(re.sub(r"\s+", " ", s)).strip()

def parse_date(s):
    if not s:
        return None
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
    raw = re.sub(rb'&(?!amp;|lt;|gt;|quot;|apos;|#)', b'&amp;', raw)
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

def heat_score(source_weight, published):
    base = source_weight * 10
    if published:
        age_h = (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 3600
        decay = max(0.3, 1 - age_h / (KEEP_DAYS * 24) * 0.7)
    else:
        decay = 0.5
    return round(base * decay)

# ── F5：HN 条目抓原文 ──────────────────────────────────────
def fetch_article_text(url, max_chars=2000):
    """粗提取网页正文：去脚本/样式/标签，取前 max_chars 字符"""
    try:
        raw = fetch_url(url, timeout=10)
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            return ""
        text = re.sub(r"(?is)<(script|style|noscript|nav|footer|header)[^>]*>.*?</\1>", " ", text)
        text = strip_html(text)
        return text[:max_chars] if len(text) > 400 else ""
    except Exception:
        return ""

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

def llm_chat(base, key, model, prompt, timeout=120):
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        content = json.loads(r.read())["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.S)
    return json.loads(m.group(0)) if m else {}

# ── F4：加固的相关性过滤 + AI 加工 ─────────────────────────
ENRICH_RULES = """你是一个数据领域垂直资讯站的编辑。本站只覆盖四个领域：Data Agent（ChatBI/Text-to-SQL/分析Agent）、AI数据平台（数仓/湖仓/语义层/数据集成治理）、BI与可视化（BI工具/报表）、数据产品（方法论/融资并购/行业报告）。

【相关性硬规则】
- 仅当内容直接涉及上述领域时 relevant=true
- 泛AI新闻一律 false：AI消费应用、AI硬件、AI政策八卦、模型发布（与数据场景无关）、AI音乐/绘画/社交等
- 数据分析/数据库/数据基础设施的融资并购、产品发布、技术实践 → true

【示例】
标题 "Databricks launches new semantic layer" → {"relevant": true, ...}
标题 "OpenAI 发布新款AI智能音箱" → {"relevant": false}
标题 "Airbnb 测试 AI 搜索功能" → {"relevant": false}

输出 JSON（不要输出多余内容）：
{"relevant": true或false, "zh_title": "中文标题(≤40字)", "zh_summary": "中文摘要3-4句，保留产品名与数字，不得编造原文没有的信息", "reason": "推荐理由：为什么数据从业者应关注，1-2句", "full_zh": "基于原文的完整中文编译稿，4-8个自然段、500-800字，保留所有关键信息（产品名、公司名、数字、时间、人名），段落之间用两个换行符分隔；严格忠于原文，不得编造原文没有的内容；若提供的原文信息不足，则在摘要基础上适度展开但总量不少于300字", "category": "agent|platform|bi|product", "vendors": ["提到的数据厂商，如Snowflake/Databricks/PowerBI/帆软等，没有则空数组"], "importance": 1-100整数}"""

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
        it["full_zh"] = out.get("full_zh", "")
        cat = out.get("category")
        if cat in CATEGORIES_LABEL:
            it["category"], it["category_label"] = cat, CATEGORIES_LABEL[cat]
        llm_vendors = [v for v in (out.get("vendors") or []) if isinstance(v, str) and v.strip()]
        it["vendors"] = list(dict.fromkeys(it.get("vendors", []) + llm_vendors))[:5]
        it["heat"] = round(it["heat"] * 0.5 + int(out.get("importance", 50)) * 0.5)
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
                        a["heat"] = max(a["heat"], b["heat"]) + 8 * (len(a["items"]) - 1)
                        a["published"] = max(a["published"], b["published"])
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
        "published": it["published"],
        "items": [{"id": it["id"], "source": it["source"], "link": it["link"],
                   "published": it["published"], "title": it["title"]}],
    }

def merge_into(e, it):
    e["items"].append({"id": it["id"], "source": it["source"], "link": it["link"],
                       "published": it["published"], "title": it["title"]})
    e["heat"] = max(e["heat"], it["heat"]) + 8
    e["published"] = max(e["published"], it["published"])
    if len(it.get("zh_summary", "")) > len(e.get("zh_summary", "")):
        e["zh_summary"], e["reason"] = it["zh_summary"], it.get("reason", e["reason"])
    if len(it.get("full_zh", "")) > len(e.get("full_zh", "")):
        e["full_zh"] = it["full_zh"]
    e["vendors"] = list(dict.fromkeys(e.get("vendors", []) + it.get("vendors", [])))[:5]

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
            })
    seen_links, out = set(), []
    for e in entries:
        if e["link"] not in seen_links:
            seen_links.add(e["link"]); out.append(e)
    return out

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

    new_items, source_status = [], []
    for s in sources:
        try:
            if s.get("kind") == "hn_algolia":
                entries = fetch_hn_algolia(s)
            else:
                entries = parse_feed(fetch_feed(s["url"]), s)
            kept = 0
            for e in entries:
                if e["published"] and e["published"] < cutoff:
                    continue
                iid = hashlib.md5(e["link"].encode()).hexdigest()[:12]
                if iid in seen or norm_url(e["link"]) in seen_urls:
                    continue
                seen.add(iid); seen_urls.add(norm_url(e["link"]))
                pub = e["published"].astimezone(TZ) if e["published"] else now.astimezone(TZ)
                new_items.append({
                    "id": iid, "title": e["title"], "zh_title": e["title"],
                    "summary": e["summary"][:600], "zh_summary": e["summary"][:300],
                    "reason": "", "link": e["link"],
                    "source": s["name"], "source_type": s["type"],
                    "category": "platform", "category_label": "AI 数据平台",
                    "vendors": VENDOR_TAGS.get(s["name"], []),
                    "vendor_default": s["type"] == "vendor",
                    "published": pub.isoformat(),
                    "heat": heat_score(s["weight"], e["published"]),
                    "star": s["type"] == "vendor" and s["weight"] >= 3,
                    "article_text": "",
                })
                kept += 1
            source_status.append({"name": s["name"], "ok": True, "new": kept})
            print(f"[fetch] {s['name']:28s} 新增 {kept} 条")
        except Exception as e:
            source_status.append({"name": s["name"], "ok": False, "error": str(e)})
            print(f"[fetch] {s['name']:28s} 失败: {e}")

    # F5+：全部新条目抓原文正文（用于摘要质量 + AI 全文编译），并发执行
    def grab(it):
        it["article_text"] = fetch_article_text(it["link"])
        return it
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(grab, new_items))
    got = sum(1 for it in new_items if it["article_text"])
    print(f"[article] 正文抓取成功 {got}/{len(new_items)}")

    # F4：LLM 加工
    new_items = llm_enrich(new_items, cfg)

    # F1：聚簇
    events = cluster_events(new_items, events, cfg)

    # 清理过期
    events = [e for e in events if datetime.fromisoformat(e["published"]) > cutoff]

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
