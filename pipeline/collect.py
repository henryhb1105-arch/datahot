#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""考古收录：把任意经典文章 URL 收进典藏池；自动识别微信公众号文章并提取账号名
用法：python3 pipeline/collect.py <url1> [url2 ...]
"""
import sys, json, hashlib, re, html as H
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_update import (fetch_article_text, make_event, load_llm_config, llm_chat, compile_fulltext,
                        norm_url, fetch_url, strip_html, calc_heat, TOPIC_NAMES,
                        CATEGORIES_LABEL, TZ, LLM_USAGE)

ROOT = Path(__file__).resolve().parent.parent
LATEST = ROOT / "site" / "data" / "latest.json"

def fetch_wechat(url):
    """抓取微信公众号文章：返回 (标题, 公众号名, 正文)"""
    raw = fetch_url(url, timeout=20)
    h = raw.decode("utf-8", errors="ignore")
    def un(x):
        return H.unescape(x).strip() if x else ""
    t = re.search(r"var msg_title = ['\"]([^'\"]+)", h) or re.search(r'property="og:title" content="([^"]+)', h)
    n = re.search(r"var nickname = (?:htmlDecode\()?['\"]([^'\"]+)", h)
    body = re.search(r'(?s)<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*(?:<script|<div[^>]*id="js_pc_qr_code")', h)
    text = strip_html(body.group(1))[:3000] if body else ""
    return un(t.group(1) if t else ""), un(n.group(1) if n else ""), text

def fetch_pdf(url):
    """抓取 PDF 并提取文本（本地运行，依赖 pypdf）"""
    raw = fetch_url(url, timeout=30)
    tmp = Path("/tmp/_collect.pdf")
    tmp.write_bytes(raw)
    from pypdf import PdfReader
    r = PdfReader(str(tmp))
    text = "\n".join((p.extract_text() or "") for p in r.pages[:20])
    return text[:3000]

def main():
    urls = sys.argv[1:]
    if not urls:
        print("用法：python3 pipeline/collect.py <url1> [url2 ...]"); sys.exit(1)
    d = json.load(open(LATEST))
    events = d.get("events", [])
    seen_urls = {norm_url(sub["link"]) for e in events for sub in e["items"]}
    cfg = load_llm_config()
    now = datetime.now(TZ)

    new_items, wx_accounts = [], []
    for u in urls:
        if norm_url(u) in seen_urls:
            print(f"跳过（已收录）: {u}"); continue
        if "mp.weixin.qq.com" in u:
            title, account, text = fetch_wechat(u)
            source = f"公众号·{account}" if account else "微信公众号"
            if account:
                wx_accounts.append(account)
        elif u.lower().endswith(".pdf"):
            text = fetch_pdf(u)
            title = u.rsplit("/", 1)[-1].replace(".pdf", "").replace("-", " ")
            source = "主编收录"
        else:
            text, title, meta_dt = fetch_article_text(u)
            source = "主编收录"
        if not title:
            print(f"抓取失败: {u}"); continue
        pub_dt = locals().get("meta_dt")
        pub_iso = pub_dt.astimezone(TZ).isoformat() if pub_dt else None
        new_items.append({
            "id": hashlib.md5(u.encode()).hexdigest()[:12],
            "title": title, "zh_title": title,
            "summary": text[:600], "zh_summary": "", "reason": "",
            "link": u, "source": source, "source_type": "curated",
            "category": "platform", "category_label": "AI 数据平台",
            "vendors": [], "vendor_default": True, "topics": [],  # 主编收录：默认相关，不过滤
            "published": pub_iso or now.isoformat(), "_pub_dt": pub_dt or now,
            "signal": 0, "importance": 50, "heat": 20,
            "star": False, "article_text": text, "shelf": "news",
        })
        print(f"抓到: [{source}] {title[:50]}")

    def enrich_curated(it):
        """主编收录专用加工：不做相关性过滤（人选的必然相关）"""
        key, base, model = cfg
        content = f"标题：{it['title']}\n摘要：{it['summary'][:800]}"
        if it.get("article_text"):
            content += f"\n原文：{it['article_text'][:2200]}"
        topics_str = "/".join(TOPIC_NAMES)
        out = llm_chat(
            base, key, model,
            "你是数据领域垂直资讯站的编辑，为以下内容生成中文加工稿。输出 JSON："
            '{"zh_title": "中文标题(≤40字，不要带网站后缀)", "zh_summary": "中文摘要3-4句", '
            '"reason": "推荐理由1-2句", '
            '"category": "agent|platform|bi|product", '
            '"topics": ["从主题词表选0-2个：' + topics_str + '，没有就空数组"], '
            '"vendors": ["提到的厂商"], "importance": 1-100整数}\n\n' + content,
            purpose="curated_enrich", source=it.get("source", ""), item_id=it.get("id", ""),
        )
        it["zh_title"] = (out.get("zh_title") or it["title"]).strip()
        it["zh_summary"] = out.get("zh_summary") or it["summary"][:300]
        it["reason"] = out.get("reason", "")
        it["full_zh"] = compile_fulltext(
            it["zh_title"], it.get("article_text") or it.get("summary", ""), cfg,
            context={"source": it.get("source", ""), "item_id": it.get("id", "")},
        )
        cat = out.get("category")
        if cat in CATEGORIES_LABEL:
            it["category"], it["category_label"] = cat, CATEGORIES_LABEL[cat]
        it["topics"] = [t for t in (out.get("topics") or []) if t in TOPIC_NAMES][:2]
        it["vendors"] = [v for v in (out.get("vendors") or []) if isinstance(v, str)][:5]
        it["importance"] = int(out.get("importance", 70))
        it["heat"] = calc_heat(it["importance"], it["_pub_dt"], 0)
        return it

    if new_items:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            new_items = list(pool.map(enrich_curated, new_items))
        for it in new_items:
            it["shelf"] = "evergreen"   # 收录一律进典藏
            it["pinned"] = True
            events.append(make_event(it))
            print(f"已入典藏: {it['zh_title'][:50]}")
        d["events"] = events
        json.dump(d, open(LATEST, "w"), ensure_ascii=False, indent=1)
        print(f"完成，当前事件总数 {len(events)}。运行 build_site.py 重建站点。")

    if wx_accounts:
        print("\n═══ 检测到微信公众号 ═══")
        for a in dict.fromkeys(wx_accounts):
            print(f"  账号：{a}  → 可通过 wechat2rss 转为长期信源（待确认）")

if __name__ == "__main__":
    try:
        main()
    finally:
        LLM_USAGE.finalize()
        print(LLM_USAGE.one_line_summary())
