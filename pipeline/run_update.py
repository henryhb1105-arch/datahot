#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DataHot 更新管道：采集 RSS → 过滤 → 分类 → 打分 → （可选 LLM 加工）→ 生成静态站
用法：python3 run_update.py
LLM 加工（可选）：设置环境变量 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL（OpenAI 兼容接口）
"""
import json, os, re, sys, html, socket, hashlib, urllib.request, urllib.error, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DATA = SITE / "data"
ARCHIVE = DATA / "archive"
KEEP_DAYS = 7          # 时间轴保留天数
PER_SOURCE_MAX = 20    # 每个源最多取多少条
TZ = timezone(timedelta(hours=8))

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
      "Accept": "application/rss+xml,application/xml,text/xml,*/*"}

socket.setdefaulttimeout(20)

# ── 栏目分类规则 ──────────────────────────────────────────
CATEGORIES = [
    ("agent",    "Data Agent",  ["text-to-sql", "text2sql", "nl2sql", "chatbi", "natural language query",
                                 "analytics agent", "data agent", "copilot", "agent", "conversational analytics",
                                 "对话式", "取数", "chatbot"]),
    ("platform", "AI 数据平台", ["data warehouse", "lakehouse", "warehouse", "etl", "elt", "pipeline",
                                 "semantic layer", "ingestion", "governance", "data platform", "streaming",
                                 "iceberg", "delta", "catalog", "数据平台", "湖仓", "语义层", "治理"]),
    ("bi",       "BI 与可视化", ["dashboard", "visualization", "visualisation", "chart", "reporting", "bi ",
                                 "business intelligence", "报表", "仪表盘", "可视化"]),
    ("product",  "数据产品",    ["funding", "acquisition", "acquires", "raises", "ipo", "gartner", "forrester",
                                 "magic quadrant", "pricing", "融资", "收购", "并购", "报告"]),
]

VENDOR_TAGS = {
    "Databricks Blog": ["Databricks"], "dbt Blog": ["dbt Labs"],
    "ThoughtSpot Blog": ["ThoughtSpot"], "Metabase Blog": ["Metabase"],
    "ClickHouse Blog": ["ClickHouse"], "AWS Big Data Blog": ["AWS"],
    "Fivetran Blog": ["Fivetran"], "StarRocks Blog": ["StarRocks"],
}

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

def fetch_feed(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req) as r:
        raw = r.read()
    raw = re.sub(rb'&(?!amp;|lt;|gt;|quot;|apos;|#)', b'&amp;', raw)  # 修复裸 &
    return ET.fromstring(raw)

def text_of(el, *names):
    for n in names:
        c = el.find(n)
        if c is not None and c.text:
            return c.text
        # 带命名空间
        for child in el:
            if child.tag.split("}")[-1] == n and child.text:
                return child.text
    return ""

def parse_feed(root_el, source):
    items = []
    # RSS 2.0
    for it in root_el.iter("item"):
        items.append({
            "title": strip_html(text_of(it, "title")),
            "link": text_of(it, "link").strip(),
            "published": parse_date(text_of(it, "pubDate", "published", "updated", "date")),
            "summary": strip_html(text_of(it, "description", "summary", "encoded")),
        })
    # Atom
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

def categorize(title, summary):
    text = (title + " " + summary).lower()
    for key, label, kws in CATEGORIES:
        if any(k in text for k in kws):
            return key, label
    return "platform", "AI 数据平台"

def heat_score(source_weight, published):
    base = source_weight * 10
    if published:
        age_h = (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 3600
        decay = max(0.3, 1 - age_h / (KEEP_DAYS * 24) * 0.7)
    else:
        decay = 0.5
    return round(base * decay)

# ── LLM 加工（可选，OpenAI 兼容接口）──────────────────────
def load_llm_config():
    """优先级：环境变量 > pipeline/config.json"""
    key, base, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_BASE_URL"), os.getenv("LLM_MODEL")
    cfg_path = Path(__file__).resolve().parent / "config.json"
    if cfg_path.exists():
        cfg = json.load(open(cfg_path))
        key = key or cfg.get("LLM_API_KEY", "")
        base = base or cfg.get("LLM_BASE_URL", "")
        model = model or cfg.get("LLM_MODEL", "")
    return key, base, model

def llm_enrich(items):
    key, base, model = load_llm_config()
    if not (key and base and model):
        print("[llm] 未配置 LLM_API_KEY/LLM_BASE_URL/LLM_MODEL，跳过 AI 加工（标题/摘要保留原文）")
        return items
    from concurrent.futures import ThreadPoolExecutor

    def enrich_one(it):
        prompt = (
            "你是面向数据从业者的资讯编辑，服务于一个监控 Data Agent、AI数据平台、BI、数据产品 四个领域的资讯站。"
            "基于以下资讯判断相关性并输出 JSON（不要输出多余内容）：\n"
            '{"relevant": true或false（与上述四个领域无关则为false）, '
            '"zh_title": "中文标题（不超过40字）", "zh_summary": "中文摘要，3-4句，保留产品名与数字", '
            '"reason": "推荐理由：为什么数据从业者应关注，1-2句", '
            '"category": "agent|platform|bi|product 四选一", "importance": 1到100的整数}\n\n'
            f"标题：{it['title']}\n摘要：{it['summary'][:800]}"
        )
        req = urllib.request.Request(
            base.rstrip("/") + "/chat/completions",
            data=json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            content = json.loads(r.read())["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)  # 容错：从文本中提取 JSON
        out = json.loads(m.group(0)) if m else {}
        if out.get("relevant") is False:
            return None
        it["zh_title"] = out.get("zh_title") or it["title"]
        it["zh_summary"] = out.get("zh_summary") or it["summary"][:300]
        it["reason"] = out.get("reason", "")
        if out.get("category") in ("agent", "platform", "bi", "product"):
            it["category"] = out["category"]
            it["category_label"] = dict(agent="Data Agent", platform="AI 数据平台",
                                        bi="BI 与可视化", product="数据产品")[out["category"]]
        it["heat"] = round(it["heat"] * 0.5 + int(out.get("importance", 50)) * 0.5)
        return it

    kept = []
    with ThreadPoolExecutor(max_workers=6) as pool:
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

# ── 主流程 ────────────────────────────────────────────────
def fetch_hn_algolia(source):
    """通过 Algolia HN API 按关键词检索热帖（points 过滤）"""
    entries = []
    min_points = source.get("min_points", 30)
    for q in source.get("queries", []):
        url = ("https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=15&query="
               + urllib.parse.quote(q))
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req) as r:
            hits = json.loads(r.read())["hits"]
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

def main():
    sources = [s for s in json.load(open(ROOT / "pipeline" / "sources.json")) if s.get("enabled")]
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=KEEP_DAYS)

    # 历史条目（用于跨次累积 + 去重）
    DATA.mkdir(parents=True, exist_ok=True); ARCHIVE.mkdir(parents=True, exist_ok=True)
    old_items = []
    latest_path = DATA / "latest.json"
    if latest_path.exists():
        old_items = json.load(open(latest_path)).get("items", [])
    seen = {i["id"] for i in old_items}

    new_items, source_status = [], []
    for s in sources:
        try:
            if s.get("kind") == "hn_algolia":
                entries = fetch_hn_algolia(s)
            else:
                feed = fetch_feed(s["url"])
                entries = parse_feed(feed, s)
            kept = 0
            for e in entries:
                if e["published"] and e["published"] < cutoff:
                    continue
                iid = hashlib.md5(e["link"].encode()).hexdigest()[:12]
                if iid in seen:
                    continue
                seen.add(iid)
                cat, label = categorize(e["title"], e["summary"])
                pub = e["published"].astimezone(TZ) if e["published"] else now.astimezone(TZ)
                new_items.append({
                    "id": iid, "title": e["title"], "zh_title": e["title"],
                    "summary": e["summary"][:600], "zh_summary": e["summary"][:300],
                    "reason": "", "link": e["link"],
                    "source": s["name"], "source_type": s["type"],
                    "category": cat, "category_label": label,
                    "vendors": VENDOR_TAGS.get(s["name"], []),
                    "published": pub.isoformat(),
                    "heat": heat_score(s["weight"], e["published"]),
                    "star": s["type"] == "vendor" and s["weight"] >= 3,
                })
                kept += 1
            source_status.append({"name": s["name"], "ok": True, "new": kept})
            print(f"[fetch] {s['name']:30s} 新增 {kept} 条")
        except Exception as e:
            source_status.append({"name": s["name"], "ok": False, "error": str(e)})
            print(f"[fetch] {s['name']:30s} 失败: {e}")

    all_items = llm_enrich(new_items) + old_items
    # 清理过期 + 排序
    all_items = [i for i in all_items if not i.get("published") or datetime.fromisoformat(i["published"]) > cutoff]
    all_items.sort(key=lambda i: i["heat"], reverse=True)
    top3 = all_items[:3]
    all_items.sort(key=lambda i: i["published"], reverse=True)

    payload = {
        "generated_at": now.astimezone(TZ).isoformat(),
        "items": all_items, "top": [i["id"] for i in top3],
        "sources": source_status,
    }
    json.dump(payload, open(latest_path, "w"), ensure_ascii=False, indent=1)
    json.dump(payload, open(ARCHIVE / (now.astimezone(TZ).strftime("%Y-%m-%d-%H%M") + ".json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"[done] 总条目 {len(all_items)}，新增 {len(new_items)}")
    return payload

if __name__ == "__main__":
    main()
