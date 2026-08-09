#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性回填：为现有事件打 topics 标签（只读标题+摘要，成本低）"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_update import load_llm_config, llm_chat, TOPIC_NAMES
from concurrent.futures import ThreadPoolExecutor

DATA = Path(__file__).resolve().parent.parent / "site" / "data" / "latest.json"

def tag_event(e):
    if e.get("topics"):
        return e, False
    out = llm_chat(BASE, KEY, MODEL,
        "以下是数据领域资讯的标题和摘要。从主题词表中选 0-2 个最贴切的主题"
        f"（{ '/'.join(TOPIC_NAMES) }），没有合适的就空数组，宁缺毋滥。"
        '只输出 JSON {"topics": [...]}。\n\n'
        f"标题：{e['zh_title']}\n摘要：{e.get('zh_summary','')[:300]}")
    e["topics"] = [t for t in (out.get("topics") or []) if t in TOPIC_NAMES][:2]
    return e, True

KEY, BASE, MODEL = load_llm_config()
d = json.load(open(DATA))
with ThreadPoolExecutor(max_workers=10) as pool:
    results = list(pool.map(tag_event, d["events"]))
d["events"] = [r[0] for r in results]
json.dump(d, open(DATA, "w"), ensure_ascii=False, indent=1)
tagged = sum(1 for e in d["events"] if e.get("topics"))
print(f"回填完成：{tagged}/{len(d['events'])} 个事件有主题标签")
from collections import Counter
c = Counter(t for e in d["events"] for t in e.get("topics", []))
print("主题分布:", dict(c.most_common()))
