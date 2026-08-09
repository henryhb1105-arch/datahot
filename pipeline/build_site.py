#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取 site/data/latest.json，生成 site/index.html 静态页"""
import json, html
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
TZ = timezone(timedelta(hours=8))
CAT_BADGE = {"agent": "b-agent", "platform": "b-platform", "bi": "b-bi", "product": "b-product"}
CAT_LABEL = {"agent": "Data Agent", "platform": "AI 数据平台", "bi": "BI 与可视化", "product": "数据产品"}
WEEK_CN = "一二三四五六日"

def esc(s):
    return html.escape(s or "", quote=True)

def fmt_time(iso):
    return datetime.fromisoformat(iso).astimezone(TZ).strftime("%H:%M")

def day_key(iso):
    return datetime.fromisoformat(iso).astimezone(TZ).date()

def render_item(it):
    star = '<span class="star">精选</span>' if it.get("star") else ""
    title = esc(it.get("zh_title") or it["title"])
    summary = esc(it.get("zh_summary") or it.get("summary", ""))
    reason = f'<div class="why"><span class="w">推荐理由</span><span>{esc(it["reason"])}</span></div>' if it.get("reason") else ""
    vtags = "".join(f'<span class="vtag">{esc(v)}</span>' for v in it.get("vendors", []))
    vbox = f'<div class="vendors">{vtags}</div>' if vtags else ""
    return f'''<div class="item" data-cat="{it["category"]}" data-link="{esc(it["link"])}">
      <div class="top"><span>{fmt_time(it["published"])}</span><span>{esc(it["source"])}</span>
      <span class="badge {CAT_BADGE[it["category"]]}">{CAT_LABEL[it["category"]]}</span>{star}
      <span class="heatnum">🔥 {it["heat"]}</span></div>
      <h3><a href="{esc(it["link"])}" target="_blank" rel="noopener">{title}</a></h3>
      <p class="sum">{summary}</p>{reason}{vbox}
    </div>'''

def main():
    payload = json.load(open(SITE / "data" / "latest.json"))
    items = payload["items"]
    top_ids = set(payload.get("top", []))
    gen = datetime.fromisoformat(payload["generated_at"])

    # 热点榜
    hot_cards = ""
    for n, iid in enumerate(payload.get("top", [])[:3], 1):
        it = next((i for i in items if i["id"] == iid), None)
        if not it:
            continue
        hot_cards += f'''<div class="hot" data-link="{esc(it["link"])}"><span class="rank">TOP {n}</span><span class="heat">{it["heat"]} 热度</span>
        <h3><a href="{esc(it["link"])}" target="_blank" rel="noopener">{esc(it.get("zh_title") or it["title"])}</a></h3>
        <div class="sources"><span class="src">{esc(it["source"])}</span></div></div>'''

    # 时间轴按日分组
    days = defaultdict(list)
    for it in items:
        days[day_key(it["published"])].append(it)
    timeline = ""
    for d in sorted(days, reverse=True):
        head = f'{d.month}月{d.day}日'
        info = f'星期{WEEK_CN[d.weekday()]} · {len(days[d])} 条'
        timeline += f'<div class="day"><div class="day-head"><span class="date">{head}</span><span class="info">{info}</span></div>'
        timeline += "\n".join(render_item(it) for it in days[d])
        timeline += "</div>"

    # 厂商热榜（近7天条目计数）
    vendor_count = defaultdict(int)
    for it in items:
        for v in it.get("vendors", []):
            vendor_count[v] += 1
    vrows = "".join(
        f'<div class="vendor-row"><span class="n">{n}</span>{esc(v)}<span class="count">{c} 条</span></div>'
        for n, (v, c) in enumerate(sorted(vendor_count.items(), key=lambda x: -x[1])[:8], 1))
    if not vrows:
        vrows = '<div style="font-size:12.5px;color:var(--sub)">暂无数据</div>'

    ok = sum(1 for s in payload["sources"] if s["ok"])
    bad = [s["name"] for s in payload["sources"] if not s["ok"]]
    bad_txt = "、".join(bad) if bad else "0 ✅"

    css = open(ROOT / "ui-mockup" / "index.html").read()
    css = css.split("<style>", 1)[1].split("</style>", 1)[0]

    page = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DataHot · 数据领域 AI 热榜</title>
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
  <div class="section-title"><h2>🔥 本期热点</h2><span>按热度排序 · 聚簇功能 V1.1 上线</span></div>
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
    信源正常：<b>{ok}/{len(payload["sources"])}</b> · 当前条目 <b>{len(items)} 条</b><br>
    信源异常：{esc(bad_txt)}
  </div></div>
</aside>
</div></div>

<footer>DataHot · 数据领域 AI 资讯热榜 · 仅聚合摘要与链接，版权归原作者 · 由 update 管道自动生成</footer>

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
// 整卡可点：点击卡片任意位置打开原文（点击标题/标签等真实链接时除外）
document.querySelectorAll('.item,.hot').forEach(el=>{{
  el.addEventListener('click',e=>{{
    if(e.target.closest('a')) return;
    const url=el.dataset.link;
    if(url) window.open(url,'_blank','noopener');
  }});
}});
</script>
</body></html>'''

    out = SITE / "index.html"
    out.write_text(page, encoding="utf-8")
    print(f"[render] {out}  ({len(page)//1024} KB, {len(items)} 条)")

if __name__ == "__main__":
    main()
