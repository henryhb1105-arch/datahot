#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""考古收录：把任意经典文章 URL 直接收进典藏池
用法：python3 pipeline/collect.py <url1> [url2 ...]
"""
import sys, json, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_update import (fetch_article_text, llm_enrich, make_event, load_llm_config,
                        norm_url, heat_score, TZ)

ROOT = Path(__file__).resolve().parent.parent
LATEST = ROOT / "site" / "data" / "latest.json"

def main():
    urls = sys.argv[1:]
    if not urls:
        print("用法：python3 pipeline/collect.py <url1> [url2 ...]"); sys.exit(1)
    d = json.load(open(LATEST))
    events = d.get("events", [])
    seen_urls = {norm_url(sub["link"]) for e in events for sub in e["items"]}
    cfg = load_llm_config()
    now = datetime.now(TZ)

    new_items = []
    for u in urls:
        if norm_url(u) in seen_urls:
            print(f"跳过（已收录）: {u}"); continue
        text, title = fetch_article_text(u)
        if not title:
            print(f"抓取失败: {u}"); continue
        new_items.append({
            "id": hashlib.md5(u.encode()).hexdigest()[:12],
            "title": title, "zh_title": title,
            "summary": text[:600], "zh_summary": "", "reason": "",
            "link": u, "source": "主编收录", "source_type": "curated",
            "category": "platform", "category_label": "AI 数据平台",
            "vendors": [], "vendor_default": False, "topics": [],
            "published": now.isoformat(), "_pub_dt": now,
            "signal": 0, "importance": 50, "heat": 20,
            "star": False, "article_text": text, "shelf": "news",
        })
        print(f"抓到: {title[:50]}")

    if new_items:
        new_items = llm_enrich(new_items, cfg)
        for it in new_items:
            it["shelf"] = "evergreen"  # 考古收录一律进典藏
            it["pinned"] = True
            events.append(make_event(it))
            print(f"已入典藏: {it['zh_title'][:50]}")
        d["events"] = events
        json.dump(d, open(LATEST, "w"), ensure_ascii=False, indent=1)
        print(f"完成，当前事件总数 {len(events)}。运行 build_site.py 重建站点。")

if __name__ == "__main__":
    main()
