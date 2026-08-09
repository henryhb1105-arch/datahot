#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V1.1：读取 latest.json（事件结构），生成首页 + 每个事件的站内详情页（带 OG meta）"""
import json, html, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DETAIL_DIR = SITE / "e"
TZ = timezone(timedelta(hours=8))
CAT_BADGE = {"agent": "b-agent", "platform": "b-platform", "bi": "b-bi", "product": "b-product"}
CAT_LABEL = {"agent": "Data Agent", "platform": "AI 数据平台", "bi": "BI 与可视化", "product": "数据产品"}
WEEK_CN = "一二三四五六日"

def esc(s):
    return html.escape(s or "", quote=True)

def fmt_time(iso):
    return datetime.fromisoformat(iso).astimezone(TZ).strftime("%H:%M")

def fmt_date(iso):
    d = datetime.fromisoformat(iso).astimezone(TZ)
    return d.strftime("%Y-%m-%d %H:%M")

def day_key(iso):
    return datetime.fromisoformat(iso).astimezone(TZ).date()

def detail_url(e):
    return f'e/{e["event_id"]}.html'

def load_css():
    css = open(ROOT / "ui-mockup" / "index.html").read()
    return css.split("<style>", 1)[1].split("</style>", 1)[0]

def sources_html(e, link=False):
    """信源列表：首页纯展示，详情页带链接"""
    parts = []
    for sub in e["items"]:
        if link:
            parts.append(f'<a class="src" href="{esc(sub["link"])}" target="_blank" rel="noopener">{esc(sub["source"])} ↗</a>')
        else:
            parts.append(f'<span class="src">{esc(sub["source"])}</span>')
    return "".join(parts)

def render_card(e):
    star = '<span class="star">精选</span>' if e.get("star") else ""
    n = len(e["items"])
    also = ""
    if n > 1:
        names = " · ".join(esc(s["source"]) for s in e["items"][1:])
        also = f'<div class="also">另有 <b>{n-1} 家信源</b>报道：{names}</div>'
    reason = f'<div class="why"><span class="w">推荐理由</span><span>{esc(e["reason"])}</span></div>' if e.get("reason") else ""
    vtags = "".join(f'<span class="vtag">{esc(v)}</span>' for v in e.get("vendors", []))
    vbox = f'<div class="vendors">{vtags}</div>' if vtags else ""
    url = detail_url(e)
    return f'''<div class="item" data-cat="{e["category"]}" data-link="{url}">
      <div class="top"><span>{fmt_time(e["published"])}</span><span>{esc(e["items"][0]["source"])}</span>
      <span class="badge {CAT_BADGE[e["category"]]}">{CAT_LABEL[e["category"]]}</span>{star}
      <span class="heatnum">🔥 {e["heat"]}</span></div>
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

def render_detail(e, all_events, css):
    ebg = title_bigrams(e["zh_title"])
    related = sorted(
        (x for x in all_events if x["event_id"] != e["event_id"]),
        key=lambda x: (x["category"] == e["category"], sim(ebg, title_bigrams(x["zh_title"]))),
        reverse=True)[:3]
    rel_html = "".join(
        f'<a class="vendor-row" href="../{detail_url(x)}">'
        f'<span class="n">›</span>{esc(x["zh_title"])}<span class="count">🔥 {x["heat"]}</span></a>'
        for x in related) or '<div style="font-size:12.5px;color:var(--sub)">暂无相关事件</div>'
    sorted_items = sorted(e["items"], key=lambda s: s["published"])
    srcs = ""
    for i, s in enumerate(sorted_items):
        first_badge = '<span class="src more">首发</span>' if i == 0 else ""
        en_note = "（英文）" if s["source"] != "InfoQ（AI/数据工程）" else ""
        srcs += (f'<div class="vendor-row"><span class="n">↗</span>'
                 f'<a href="{esc(s["link"])}" target="_blank" rel="noopener">{esc(s["source"])}{en_note}</a>'
                 f'{first_badge}'
                 f'<span class="count">{fmt_date(s["published"])}</span></div>')
    vtags = "".join(f'<span class="vtag">{esc(v)}</span>' for v in e.get("vendors", []))
    desc = esc(e["zh_summary"][:150])
    main_link = esc(sorted_items[0]["link"])
    main_src = esc(sorted_items[0]["source"])
    # 全文编译段落
    full_paras = "".join(
        f"<p>{esc(p)}</p>" for p in re.split(r"\n\s*\n|\n", e.get("full_zh", "")) if p.strip())
    full_block = ""
    if full_paras:
        full_block = f'''<div class="card"><h4>📄 全文编译 <span style="font-size:11px;color:var(--sub);font-weight:400">AI 基于原文编译</span></h4>
  <div class="fulltext">{full_paras}</div>
  <div class="disclaimer">本内容由 AI 基于原文编译生成，仅供参考，版权归原作者与原发布方所有 · <a href="{main_link}" target="_blank" rel="noopener">查看原文 ↗</a></div>
</div>'''
    page_url = f"{SITE_BASE}/e/{e['event_id']}.html"
    jsonld = json.dumps({
        "@context": "https://schema.org", "@type": "NewsArticle",
        "headline": e["zh_title"], "description": e["zh_summary"][:150],
        "datePublished": e["published"], "inLanguage": "zh-CN",
        "isBasedOn": sorted_items[0]["link"],
        "publisher": {"@type": "Organization", "name": "DataHot"},
    }, ensure_ascii=False)
    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(e["zh_title"])} · DataHot</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{page_url}">
<meta property="og:title" content="{esc(e["zh_title"])}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:url" content="{page_url}">
<meta property="og:site_name" content="DataHot · 数据领域 AI 热榜">
<script type="application/ld+json">{jsonld}</script>
<style>{css}
.article{{max-width:760px;margin:0 auto;padding:32px 20px 60px}}
.article .back{{font-size:13px;color:var(--sub);display:inline-block;margin-bottom:18px}}
.article .back:hover{{color:var(--accent)}}
.article h1{{font-size:24px;font-weight:800;line-height:1.5;margin:12px 0 16px}}
.article .meta{{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--sub);flex-wrap:wrap}}
.article .body{{font-size:15.5px;line-height:1.9;color:#374151;margin:20px 0}}
.article .card{{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px 22px;margin:18px 0}}
.article h4{{font-size:14px;font-weight:800;margin-bottom:10px}}
.article .vendor-row{{text-decoration:none}}
.cta{{display:inline-block;background:var(--accent);color:#fff;font-size:14px;font-weight:700;border-radius:10px;padding:11px 26px;margin:6px 0 4px}}
.cta:hover{{opacity:.9}}
.fulltext p{{font-size:15px;line-height:1.95;color:#374151;margin:0 0 14px}}
.disclaimer{{font-size:12px;color:var(--sub);border-top:1px dashed var(--line);padding-top:10px;margin-top:4px}}
.disclaimer a{{color:var(--accent)}}
</style></head><body>
<header><div class="wrap nav">
  <div class="logo"><a href="../index.html">Data<em>Hot</em></a><span class="tag">每 6 小时更新</span></div>
</div></header>
<div class="article">
  <a class="back" href="../index.html">← 返回热榜</a>
  <div class="meta">
    <span class="badge {CAT_BADGE[e["category"]]}">{CAT_LABEL[e["category"]]}</span>
    {'<span class="star">精选</span>' if e.get("star") else ''}
    <span title="{fmt_date(e["published"])}">{human_time(e["published"])}</span>
    <span style="margin-left:auto" class="heatnum">🔥 {e["heat"]} 热度</span>
  </div>
  <h1>{esc(e["zh_title"])}</h1>
  <div class="body">{esc(e["zh_summary"])}</div>
  <a class="cta" href="{main_link}" target="_blank" rel="noopener">阅读原文 · {main_src} ↗</a>
  {f'<div class="why" style="border-top:1px dashed var(--line);padding-top:14px;margin-top:18px;font-size:14px"><span class="w">推荐理由</span><span>{esc(e["reason"])}</span></div>' if e.get("reason") else ""}
  {f'<div class="vendors" style="margin-top:14px">{vtags}</div>' if vtags else ""}
  {full_block}
  <div class="card"><h4>🔗 信源（{len(e["items"])} 家报道 · 按时间排序）</h4>{srcs}</div>
  <div class="card"><h4>📌 相关事件</h4>{rel_html}</div>
</div>
<footer>DataHot · 数据领域 AI 资讯热榜 · 仅聚合摘要与编译内容，版权归原作者</footer>
</body></html>'''

def main():
    payload = json.load(open(SITE / "data" / "latest.json"))
    events = payload["events"]
    gen = datetime.fromisoformat(payload["generated_at"])
    css = load_css()

    # ── 详情页 ──
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    valid_ids = set()
    for e in events:
        valid_ids.add(e["event_id"] + ".html")
        (DETAIL_DIR / (e["event_id"] + ".html")).write_text(render_detail(e, events, css), encoding="utf-8")
    # 清理过期详情页
    for f in DETAIL_DIR.glob("*.html"):
        if f.name not in valid_ids:
            f.unlink()

    # ── 热点榜 ──
    hot_cards = ""
    for n, eid in enumerate(payload.get("top", [])[:3], 1):
        e = next((x for x in events if x["event_id"] == eid), None)
        if not e:
            continue
        hot_cards += f'''<div class="hot" data-link="{detail_url(e)}"><span class="rank">TOP {n}</span><span class="heat">{e["heat"]} 热度</span>
        <h3><a href="{detail_url(e)}">{esc(e["zh_title"])}</a></h3>
        <div class="sources">{sources_html(e)}</div></div>'''

    # ── 时间轴 ──
    days = defaultdict(list)
    for e in events:
        days[day_key(e["published"])].append(e)
    timeline = ""
    for d in sorted(days, reverse=True):
        head = f'{d.month}月{d.day}日'
        info = f'星期{WEEK_CN[d.weekday()]} · {len(days[d])} 个事件'
        timeline += f'<div class="day"><div class="day-head"><span class="date">{head}</span><span class="info">{info}</span></div>'
        timeline += "\n".join(render_card(e) for e in days[d])
        timeline += "</div>"

    # ── 厂商热榜 ──
    vendor_count = defaultdict(int)
    for e in events:
        for v in e.get("vendors", []):
            vendor_count[v] += 1
    vrows = "".join(
        f'<div class="vendor-row"><span class="n">{n}</span>{esc(v)}<span class="count">{c} 条</span></div>'
        for n, (v, c) in enumerate(sorted(vendor_count.items(), key=lambda x: -x[1])[:8], 1))
    if not vrows:
        vrows = '<div style="font-size:12.5px;color:var(--sub)">暂无数据</div>'

    ok = sum(1 for s in payload["sources"] if s["ok"])
    bad = [s["name"] for s in payload["sources"] if not s["ok"]]
    bad_txt = "、".join(bad) if bad else "0 ✅"

    page = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DataHot · 数据领域 AI 热榜</title>
<meta name="description" content="监控 Data Agent、AI 数据平台、BI、数据产品四个领域的资讯热榜，多信源聚簇 + AI 中文摘要与推荐理由，每 6 小时更新。">
<meta property="og:title" content="DataHot · 数据领域 AI 热榜">
<meta property="og:description" content="Data Agent / AI 数据平台 / BI / 数据产品的每日热点，每 6 小时自动更新。">
<meta property="og:type" content="website">
<style>{css}
.item a:hover{{color:var(--accent)}}
.hot a:hover{{color:var(--accent)}}
</style></head><body>
<header><div class="wrap nav">
  <div class="logo">Data<em>Hot</em><span class="tag">每 6 小时更新</span></div>
  <nav class="tabs" id="tabs">
    <span class="tab on" data-cat="all">🔥 全部</span>
    <span class="tab" data-cat="agent">🤖 Data Agent</span>
    <span class="tab" data-cat="platform">🏗️ AI 数据平台</span>
    <span class="tab" data-cat="bi">📊 BI 与可视化</span>
    <span class="tab" data-cat="product">🧩 数据产品</span>
  </nav>
  <div class="search" onclick="document.getElementById('q').focus()">🔍 <input id="q" placeholder="搜索标题…" style="border:none;outline:none;background:transparent;font-size:13px;width:110px"></div>
</div></header>

<div class="wrap"><div class="layout"><main>
  <div class="section-title"><h2>🔥 本期热点</h2><span>多信源聚簇 · 按热度排序</span></div>
  <div class="hotlist">{hot_cards}</div>
  <div class="section-title"><h2>📅 时间轴</h2><span>近 7 天 · 按日分组</span></div>
  {timeline}
</main>

<aside>
  <div class="card"><h4>🏢 厂商热榜 <span style="font-size:11px;color:var(--sub);font-weight:400">近7天</span></h4>{vrows}</div>
  <div class="card"><h4>🏷️ 栏目说明</h4><div class="legend">
    <div class="row"><span class="badge b-agent">Data Agent</span>ChatBI · NL2SQL · 分析 Agent</div>
    <div class="row"><span class="badge b-platform">AI 数据平台</span>湖仓 · 语义层 · 数据治理</div>
    <div class="row"><span class="badge b-bi">BI 与可视化</span>BI 厂商 · 报表 · 可视化</div>
    <div class="row"><span class="badge b-product">数据产品</span>方法论 · 融资并购 · 报告</div>
  </div></div>
  <div class="card"><h4>🕐 更新状态</h4><div class="status">
    最后更新：<b>{gen.strftime("%Y-%m-%d %H:%M")}</b><br>
    信源正常：<b>{ok}/{len(payload["sources"])}</b> · 在站事件 <b>{len(events)} 个</b><br>
    信源异常：{esc(bad_txt)}
  </div></div>
</aside>
</div></div>

<footer>DataHot · 数据领域 AI 资讯热榜 · 仅聚合摘要与链接，版权归原作者 · 每 6 小时自动更新</footer>

<script>
const tabs=document.querySelectorAll('#tabs .tab');
tabs.forEach(t=>t.addEventListener('click',()=>{{
  tabs.forEach(x=>x.classList.remove('on'));t.classList.add('on');
  const c=t.dataset.cat;
  document.querySelectorAll('.item').forEach(el=>{{
    el.style.display=(c==='all'||el.dataset.cat===c)?'':'none';
  }});
}}));
document.getElementById('q').addEventListener('input',e=>{{
  const q=e.target.value.toLowerCase();
  document.querySelectorAll('.item').forEach(el=>{{
    el.style.display=el.textContent.toLowerCase().includes(q)?'':'none';
  }});
}});
// 整卡可点：进入站内详情页
document.querySelectorAll('.item,.hot').forEach(el=>{{
  el.addEventListener('click',e=>{{
    if(e.target.closest('a')) return;
    const url=el.dataset.link;
    if(url) location.href=url;
  }});
}});
</script>
</body></html>'''

    out = SITE / "index.html"
    out.write_text(page, encoding="utf-8")
    print(f"[render] 首页 ({len(page)//1024} KB) + 详情页 {len(valid_ids)} 个")

if __name__ == "__main__":
    main()
