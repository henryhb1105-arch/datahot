"""Curated product identities and source-backed implementation paths.

Matching uses titles, short editorial metadata and exact official domains. A
vendor name or a passing mention in the full article is never enough by itself.
"""
from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).parent
SLUG = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


@lru_cache(maxsize=1)
def load_products():
    products = json.loads((ROOT / "products.json").read_text())["products"]
    ids = [p["id"] for p in products]
    if len(set(ids)) != len(ids) or any(not SLUG.fullmatch(i) for i in ids):
        raise ValueError("invalid or duplicate product identity")
    for p in products:
        if urlparse(p["url"]).scheme != "https" or not p["name"] or not p["focus"]:
            raise ValueError("product must have a name, focus and HTTPS source")
    return products


def text_matches(text, aliases):
    return any(re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text, re.I)
               for alias in aliases)


def match_products(event, products=None):
    products = load_products() if products is None else products
    items = event.get("items") or []
    text = " ".join(str(s or "") for s in [event.get("zh_title"), event.get("zh_summary"),
                     *[i.get("title") for i in items]])
    hosts = {(urlparse(str(i.get("link") or "")).hostname or "").removeprefix("www.") for i in items}
    return [p["id"] for p in products if
            event.get("event_id") in p["event_ids"] or
            text_matches(text, p["aliases"]) or bool(hosts & set(p["domains"]))]


def product_metadata():
    return [{"id":p["id"], "name":p["name"], "category":p["category"]} for p in load_products()]


def load_paths(events, case_paths):
    payload = json.loads((ROOT / "learning_paths.json").read_text())
    available = {e["event_id"] for e in events}
    seen = set()
    for path in payload["paths"]:
        if path["id"] in seen or not SLUG.fullmatch(path["id"]):
            raise ValueError("invalid or duplicate reference path")
        seen.add(path["id"])
        for step in path["steps"]:
            if not step["events"] or not set(step["events"]) <= available:
                raise ValueError("implementation path contains missing evidence")
            if not set(step.get("cases", [])) <= set(case_paths):
                raise ValueError("implementation path contains missing case")
    return payload


def esc(value):
    return html.escape(str(value or ""), quote=True)


def render_product_index(events):
    counts = {p["id"]:0 for p in load_products()}
    for event in events:
        for product_id in match_products(event):
            counts[product_id] += 1
    cards = []
    for p in load_products():
        cards.append(f'''<article class="research-card">
          <span class="research-kicker">{esc(p['category'])}</span>
          <h2><a href="products/{p['id']}.html">{esc(p['name'])}</a></h2>
          <p>{esc(p['focus'])}</p><div class="research-actions">
          <a href="products/{p['id']}.html">{counts[p['id']]} 条已收录资料 →</a>
          <a href="for-me.html?follow=product:{p['id']}" aria-label="关注 {esc(p['name'])}">关注产品</a></div></article>''')
    return f'''<main class="wrap research-page"><header class="research-head">
      <p class="research-kicker">按产品持续跟踪</p><h1>产品雷达</h1>
      <p>把产品动态、精选参考与设计案例放在一起。关注一个产品，就能在「关注」页看到相关内容。</p>
      <nav class="research-actions" aria-label="研究入口"><a href="for-me.html">我的关注 →</a><a href="paths.html">从实施路径开始 →</a></nav>
      </header><div class="research-grid">{''.join(cards)}</div>
      <p class="research-note">覆盖范围为已收录材料，不代表产品的完整更新日志。功能状态以各篇原文对应版本为准。</p></main>'''


def render_product_body(product, events, cases, render_card):
    related = [e for e in events if product["id"] in match_products(e)]
    related.sort(key=lambda e: str(e.get("published") or e.get("first_seen") or ""), reverse=True)
    picks = [e for e in related if e.get("editorial_pick")]
    news = [e for e in related if not e.get("editorial_pick")]
    # Cases explicitly name the product; do not attach every case from a vendor.
    related_cases = [c for c in cases if text_matches(c["product"], product["aliases"] + [product["name"]])]
    def section(title, rows, limit):
        cards = ''.join(render_card(e, prefix="../") for e in rows[:limit])
        if not cards:
            return ''
        return f'<section class="research-section"><h2>{title} <small>{len(rows)} 条</small></h2>{cards}</section>'
    case_html = ''.join(f'<a class="research-reference" href="../{esc(c["href"])}"><b>{esc(c["product"])}</b><span>{esc(c["problem"])}</span></a>' for c in related_cases)
    return f'''<main class="wrap research-page research-detail"><header class="research-head">
      <a class="research-back" href="../products.html">← 产品雷达</a><p class="research-kicker">{esc(product['category'])}</p>
      <h1>{esc(product['name'])}</h1><p>{esc(product['focus'])}</p>
      <nav class="research-actions" aria-label="产品操作"><a class="research-primary" href="../for-me.html?follow=product:{product['id']}">关注这个产品</a>
      <a href="{esc(product['url'])}" target="_blank" rel="noopener noreferrer">官方网站 ↗</a></nav></header>
      <p class="research-note">{len(related)} 条已收录资料 · {len(related_cases)} 个设计案例。下列日期对应各篇材料，不代表产品当前能力清单。</p>
      {section('精选参考', picks, 8)}{section('产品动态', news, 15)}
      {f'<section class="research-section"><h2>设计案例</h2>{case_html}</section>' if case_html else ''}
      <div class="research-next"><a href="../paths.html">将这些资料用于具体任务：查看实施路径 →</a></div></main>'''


def render_paths_body(payload, events, cases):
    event_map = {e["event_id"]:e for e in events}
    sections = []
    for path in payload["paths"]:
        steps = []
        for step in path["steps"]:
            evidence = ''.join(f'<a href="e/{event_id}.html">{esc(event_map[event_id].get("zh_title"))} →</a>' for event_id in step["events"])
            examples = ''.join(f'<a href="{esc(cases[case_id]["href"])}">设计案例 · {esc(cases[case_id]["product"])} →</a>' for case_id in step.get("cases", []))
            steps.append(f'''<li><h3>{esc(step['title'])}</h3><p>{esc(step['task'])}</p>
              <p class="research-done"><b>完成标志：</b>{esc(step['done_when'])}</p>
              <div class="research-evidence" aria-label="参考材料">{evidence}{examples}</div></li>''')
        sections.append(f'''<section class="research-path" id="{path['id']}"><p class="research-kicker">{esc(path['category'])}</p>
          <h2>{esc(path['title'])}</h2><p>{esc(path['goal'])}</p><p class="research-deliverable"><b>最终产物：</b>{esc(path['deliverable'])}</p>
          <ol>{''.join(steps)}</ol></section>''')
    links = ''.join(f'<a href="#{p["id"]}">{esc(p["category"])}</a>' for p in payload["paths"])
    return f'''<main class="wrap research-page research-detail"><header class="research-head">
      <p class="research-kicker">从阅读到动手</p><h1>实施参考路径</h1><p>选一个你正在解决的问题，按步骤交付可检查的结果。</p>
      <p class="research-note">DataHot 编辑建议 · {esc(payload['reviewed_at'])} 核对。原文提供案例证据，以下步骤是实施建议，不是厂商功能承诺。</p>
      <nav class="research-path-nav" aria-label="选择实施方向">{links}</nav></header>{''.join(sections)}
      <div class="research-next"><a href="products.html">按产品继续研究 →</a><a href="favorites.html">整理我的项目资料 →</a></div></main>'''
