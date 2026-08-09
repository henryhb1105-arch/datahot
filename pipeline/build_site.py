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
TOPIC_DIR = SITE / "topics"
TZ = timezone(timedelta(hours=8))
CAT_BADGE = {"agent": "b-agent", "platform": "b-platform", "bi": "b-bi", "product": "b-product"}
CAT_LABEL = {"agent": "Data Agent", "platform": "AI 数据平台", "bi": "BI 与可视化", "product": "数据产品"}
WEEK_CN = "一二三四五六日"
TOPICS_META = json.load(open(ROOT / "pipeline" / "topics.json"))
TOPIC_SLUG = {t["name"]: t["slug"] for t in TOPICS_META}

SHARED_CSS = """
body{overflow-x:clip}
main,.layout>*,.hotlist>*{min-width:0}
.d-only{display:inline-block}
@media(max-width:960px){.d-only{display:none}}
.chip{display:inline-block;font-size:11px;background:#eef2ff;color:var(--blue);border-radius:99px;padding:1px 10px;text-decoration:none}
.chip:hover{background:#dbe4ff}
.tlsearch{margin-left:auto;border:1px solid var(--line);border-radius:99px;padding:5px 12px;font-size:12.5px;width:120px;outline:none;background:var(--card)}
.tlsearch:focus{width:160px;border-color:var(--accent);transition:width .2s}
.chiprow{display:flex;gap:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;padding:4px 0 12px;margin-bottom:4px}
.chiprow::-webkit-scrollbar{display:none}
.chiprow .fchip{flex-shrink:0;font-size:12.5px;border:1px solid var(--line);border-radius:99px;padding:4px 14px;color:var(--sub);cursor:pointer;background:var(--card)}
.chiprow .fchip.on{background:var(--ink);color:#fff;border-color:var(--ink);font-weight:600}
.tabbar{display:none}
@media(max-width:960px){
  body{padding-bottom:64px}
  .tabbar{display:flex;position:fixed;bottom:0;left:0;right:0;background:var(--tabbar-bg);backdrop-filter:blur(10px);border-top:1px solid var(--line);z-index:70;padding-bottom:env(safe-area-inset-bottom)}
  .tabbar a{flex:1;display:flex;flex-direction:column;align-items:center;padding:8px 0 6px;font-size:11px;color:var(--sub);text-decoration:none;gap:2px}
  .tabbar a .ico{font-size:19px}
  .tabbar a.on{color:var(--accent);font-weight:600}
}
.tgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
@media(max-width:960px){.tgrid{grid-template-columns:1fr}}
.tcard{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;text-decoration:none;display:block;transition:.15s}
.tcard:hover{border-color:#d1d5db;box-shadow:0 4px 16px rgba(0,0,0,.05)}
.tcard h3{font-size:17px;font-weight:800;margin-bottom:6px}
.tcard .td{font-size:12.5px;color:var(--sub);line-height:1.6;margin-bottom:10px}
.tcard .tn{font-size:12px;color:var(--accent);font-weight:700}
.tcard .tt{font-size:12.5px;color:var(--txt2);margin-top:8px;line-height:1.7}
"""

def tabbar(active, prefix=""):
    items = [("热榜", "🔥", "index.html", "home"), ("主题", "🗺️", "topics.html", "topics")]
    return ('<nav class="tabbar">' + "".join(
        f'<a href="{prefix}{u}" class="{"on" if k == active else ""}"><span class="ico">{i}</span>{n}</a>'
        for n, i, u, k in items) + "</nav>")

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

def render_card(e, prefix=""):
    star = '<span class="star">精选</span>' if e.get("star") else ""
    n = len(e["items"])
    also = ""
    if n > 1:
        names = " · ".join(esc(s["source"]) for s in e["items"][1:])
        also = f'<div class="also">另有 <b>{n-1} 家信源</b>报道：{names}</div>'
    reason = f'<div class="why"><span class="w">推荐理由</span><span>{esc(e["reason"])}</span></div>' if e.get("reason") else ""
    tchips = "".join(
        f'<a class="chip" href="{prefix}topics/{TOPIC_SLUG[t]}.html">{esc(t)}</a>'
        for t in e.get("topics", []) if t in TOPIC_SLUG)
    vtags = "".join(f'<span class="vtag">{esc(v)}</span>' for v in e.get("vendors", []))
    vbox = f'<div class="vendors">{tchips}{vtags}</div>' if (tchips or vtags) else ""
    url = prefix + detail_url(e)
    return f'''<div class="item" data-cat="{e["category"]}" data-topics="{esc("|".join(e.get("topics", [])))}" data-link="{url}">
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
    tchips = "".join(
        f'<a class="chip" href="../topics/{TOPIC_SLUG[t]}.html">{esc(t)}</a>'
        for t in e.get("topics", []) if t in TOPIC_SLUG)
    vtags = tchips + "".join(f'<span class="vtag">{esc(v)}</span>' for v in e.get("vendors", []))
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
    page = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{esc(e["zh_title"])} · DataHot</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{page_url}">
<meta property="og:title" content="{esc(e["zh_title"])}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:url" content="{page_url}">
<meta property="og:site_name" content="DataHot · 数据领域 AI 热榜">
<link rel="icon" href="../favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="../icons/favicon-32.png">
<link rel="apple-touch-icon" href="../icons/apple-touch-icon.png">
<meta name="theme-color" content="#1a1d23">
<script type="application/ld+json">{jsonld}</script>
<style>{css}
{SHARED_CSS}
.article{{max-width:760px;margin:0 auto;padding:32px 20px 60px}}
.article .back{{font-size:13px;color:var(--sub);display:inline-block;margin-bottom:18px}}
.article .back:hover{{color:var(--accent)}}
.article h1{{font-size:24px;font-weight:800;line-height:1.5;margin:12px 0 16px}}
.article .meta{{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--sub);flex-wrap:wrap}}
.article .body{{font-size:15.5px;line-height:1.9;color:var(--txt3);margin:20px 0}}
.article .card{{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px 22px;margin:18px 0}}
.article h4{{font-size:14px;font-weight:800;margin-bottom:10px}}
.article .vendor-row{{text-decoration:none}}
.cta{{display:inline-block;background:var(--accent);color:#fff;font-size:14px;font-weight:700;border-radius:10px;padding:11px 26px;margin:6px 0 4px}}
.cta:hover{{opacity:.9}}
.fulltext p{{font-size:15px;line-height:1.95;color:var(--txt3);margin:0 0 14px}}
.disclaimer{{font-size:12px;color:var(--sub);border-top:1px dashed var(--line);padding-top:10px;margin-top:4px}}
.disclaimer a{{color:var(--accent)}}
</style></head><body>
<header><div class="wrap nav">
  <div class="logo"><a href="../index.html">Data<em>Hot</em></a><span class="tag">每 6 小时更新</span></div>
</div></header>
<div class="article">
  <div class="topbar">
    <a class="back" href="../index.html" style="margin-bottom:0">← 返回热榜</a>
    <span class="sharebtns">
      <button class="sbtn ghost" onclick="openPoster()">🖼 海报</button>
      <button class="sbtn" onclick="openSheet()">↗ 分享</button>
    </span>
  </div>
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
{tabbar("home", "../")}
</body></html>'''
    return page.replace("</body></html>", share_ui(e, page_url) + "</body></html>")

def share_ui(e, page_url):
    """详情页分享组件：Action Sheet（复制链接/海报/系统分享）+ Canvas 海报生成。普通字符串，非 f-string"""
    ev_json = json.dumps({
        "title": e["zh_title"], "summary": e.get("zh_summary", ""),
        "reason": e.get("reason", ""), "topic": (e.get("topics") or [""])[0],
        "heat": e["heat"], "source": e["items"][0]["source"],
        "date": e["published"][:10], "url": page_url,
    }, ensure_ascii=False)
    return """
<div class="sh-mask" id="shMask" onclick="shClose()"></div>
<div class="sh-sheet" id="shSheet"><div class="sh-panel">
  <div class="sh-group">
    <div class="sh-title">分享这条资讯</div>
    <button class="sh-opt" onclick="shCopy()">🔗 复制链接</button>
    <button class="sh-opt" onclick="shClose();openPoster()">🖼 分享海报</button>
    <button class="sh-opt" onclick="shNative()">📲 系统分享…</button>
  </div>
  <button class="sh-cancel" onclick="shClose()">取消</button>
</div></div>
<div class="sh-poster-modal" id="shPoster">
  <div class="sh-poster-wrap"><img id="shPosterImg" alt="分享海报"></div>
  <div class="sh-poster-actions">
    <a class="sh-save" id="shSave" href="#" onclick="shSaveClick(event)">保存图片</a>
    <button class="sh-close" onclick="shClose()">关闭</button>
  </div>
  <div class="sh-poster-tip">iOS 也可以长按图片保存</div>
</div>
<div class="sh-toast" id="shToast"></div>
<style>
.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.sharebtns{display:flex;gap:8px}
.sbtn{border:none;background:var(--ink);color:var(--bg);border-radius:99px;padding:7px 14px;font-size:12.5px;font-weight:600;cursor:pointer}
.sbtn.ghost{background:var(--card);color:var(--ink);border:1px solid var(--line)}
.sbtn:active{transform:scale(.95)}
@media (prefers-color-scheme: dark){
.sh-group,.sh-cancel{background:rgba(30,33,38,.97)}
.sh-opt{color:var(--ink);border-bottom-color:var(--line)}
.sh-title{border-bottom-color:var(--line)}
}
.sh-mask{position:fixed;inset:0;background:rgba(0,0,0,.45);opacity:0;pointer-events:none;transition:.25s;z-index:80}
.sh-mask.show{opacity:1;pointer-events:auto}
.sh-sheet{position:fixed;left:0;right:0;bottom:0;z-index:90;transform:translateY(110%);transition:transform .3s cubic-bezier(.32,.72,.35,1);padding:0 10px calc(10px + env(safe-area-inset-bottom))}
.sh-sheet.show{transform:translateY(0)}
.sh-panel{max-width:430px;margin:0 auto}
.sh-group{background:rgba(255,255,255,.97);border-radius:16px;overflow:hidden;margin-bottom:8px}
.sh-title{font-size:12px;color:var(--sub);text-align:center;padding:12px;border-bottom:.5px solid var(--line)}
.sh-opt{display:flex;align-items:center;justify-content:center;gap:8px;padding:15px;font-size:16px;font-weight:500;border:none;border-bottom:.5px solid var(--line);cursor:pointer;background:none;width:100%;color:var(--ink)}
.sh-opt:last-child{border-bottom:none}
.sh-opt:active{background:#f0f1f3}
.sh-cancel{background:rgba(255,255,255,.97);border-radius:16px;padding:15px;text-align:center;font-size:16px;font-weight:600;color:var(--blue);cursor:pointer;width:100%;border:none}
.sh-poster-modal{position:fixed;inset:0;z-index:95;background:rgba(15,17,20,.92);display:none;flex-direction:column;align-items:center;justify-content:center;padding:20px}
.sh-poster-modal.show{display:flex}
.sh-poster-wrap{width:min(340px,86vw);border-radius:18px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.sh-poster-wrap img{width:100%;display:block}
.sh-poster-actions{margin-top:18px;display:flex;gap:10px}
.sh-save,.sh-close{border:none;border-radius:99px;padding:11px 22px;font-size:14px;font-weight:600;cursor:pointer;text-decoration:none}
.sh-save{background:var(--accent);color:#fff}
.sh-close{background:rgba(255,255,255,.15);color:#fff}
.sh-poster-tip{margin-top:10px;font-size:11px;color:#8b919b}
.sh-toast{position:fixed;top:18%;left:50%;transform:translateX(-50%);background:rgba(26,29,35,.92);color:#fff;font-size:13px;padding:10px 20px;border-radius:99px;opacity:0;transition:.25s;z-index:99;pointer-events:none}
.sh-toast.show{opacity:1}
</style>
<script>
if(window.CanvasRenderingContext2D&&!CanvasRenderingContext2D.prototype.roundRect){
  CanvasRenderingContext2D.prototype.roundRect=function(x,y,w,h,r){this.rect(x,y,w,h);return this;};
}
var SH_EV = __EV_JSON__;
function shClose(){
  document.getElementById('shMask').classList.remove('show');
  document.getElementById('shSheet').classList.remove('show');
  document.getElementById('shPoster').classList.remove('show');
}
function openSheet(){
  document.getElementById('shMask').classList.add('show');
  document.getElementById('shSheet').classList.add('show');
}
function shToast(t){
  var el=document.getElementById('shToast'); el.textContent=t; el.classList.add('show');
  setTimeout(function(){el.classList.remove('show')},1600);
}
function shCopy(){
  shClose();
  function done(){shToast('链接已复制，去粘贴吧');}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(SH_EV.url).then(done,done);}
  else{var i=document.createElement('input');i.value=SH_EV.url;document.body.appendChild(i);i.select();try{document.execCommand('copy');}catch(e){} i.remove();done();}
}
function shSaveClick(ev){
  ev.preventDefault();
  if(!posterURL){return;}
  var bu=URL.createObjectURL(dataToBlob(posterURL));
  var w=window.open(bu,'_blank');
  if(!w){shToast('请长按图片保存到相册');}
  else{shToast('已在新页面打开，长按图片保存');}
}
function shNative(){
  shClose();
  if(navigator.share){
    navigator.share({title:SH_EV.title,text:(SH_EV.reason||SH_EV.summary).slice(0,60)+' | DataHot',url:SH_EV.url}).catch(function(){});
  }else{shCopy();}
}
function wrapText(ctx,text,x,y,maxW,lineH,maxLines){
  var line='',lines=0;
  for(var i=0;i<text.length;i++){
    var t=line+text[i];
    if(ctx.measureText(t).width>maxW&&line){
      ctx.fillText(line,x,y);y+=lineH;lines++;line=text[i];
      if(lines>=maxLines-1){
        line=line+text.slice(i+1);
        while(ctx.measureText(line+'…').width>maxW&&line.length>1){line=line.slice(0,-1);}
        ctx.fillText(line+'…',x,y);return y+lineH;
      }
    }else{line=t;}
  }
  if(line){ctx.fillText(line,x,y);y+=lineH;}
  return y;
}
function posterPalette(dark){
  return dark ? {
    bg:['#1a1d23','#231d17','#33200f'], title:'#ffffff', sum:'#c9cdd4',
    reasonBg:'rgba(217,79,43,.14)', reasonHd:'#f5b48a', reasonTxt:'#f0d9cf',
    meta:'#8b919b', dash:'rgba(255,255,255,.18)', name:'#ffffff', foot:'#c9cdd4',
    qrBox:'#ffffff', qrBorder:null, topic:'#f5b48a', topicBd:'rgba(245,180,138,.7)'
  } : {
    bg:['#ffffff','#fdf8f4','#fdf0e9'], title:'#1a1d23', sum:'#4b5563',
    reasonBg:'rgba(217,79,43,.07)', reasonHd:'#d94f2b', reasonTxt:'#7c3a24',
    meta:'#6b7280', dash:'rgba(0,0,0,.15)', name:'#1a1d23', foot:'#6b7280',
    qrBox:'#ffffff', qrBorder:'rgba(0,0,0,.12)', topic:'#d94f2b', topicBd:'rgba(217,79,43,.5)'
  };
}
function drawPoster(qrImg,dark){
  var P=posterPalette(dark);
  var W=1080,H=1440,c=document.createElement('canvas');c.width=W;c.height=H;
  var x=c.getContext('2d');
  var g=x.createLinearGradient(0,0,W,H);
  g.addColorStop(0,P.bg[0]);g.addColorStop(.55,P.bg[1]);g.addColorStop(1,P.bg[2]);
  x.fillStyle=g;x.fillRect(0,0,W,H);
  x.fillStyle='#d94f2b';x.beginPath();x.roundRect(64,60,72,72,18);x.fill();
  x.fillStyle='#fff';x.font='800 44px -apple-system,sans-serif';x.textBaseline='middle';
  x.fillText('D',88,98);
  x.fillStyle=P.name;x.font='800 38px -apple-system,sans-serif';x.fillText('DataHot',152,100);
  if(SH_EV.topic){
    x.font='500 26px -apple-system,PingFang SC,sans-serif';
    var tw=x.measureText(SH_EV.topic).width;
    x.strokeStyle=P.topicBd;x.lineWidth=2;
    x.beginPath();x.roundRect(W-64-tw-48,66,tw+48,56,28);x.stroke();
    x.fillStyle=P.topic;x.fillText(SH_EV.topic,W-64-tw-24,96);
  }
  var y=210;x.fillStyle=P.title;x.font='800 58px -apple-system,PingFang SC,sans-serif';x.textBaseline='top';
  y=wrapText(x,SH_EV.title,64,y,W-128,84,3)+16;
  x.fillStyle=P.sum;x.font='400 32px -apple-system,PingFang SC,sans-serif';
  y=wrapText(x,SH_EV.summary,64,y,W-128,52,5)+20;
  if(SH_EV.reason){
    var ry=y+8;
    x.fillStyle=P.reasonBg;x.fillRect(64,ry,W-128,150);
    x.fillStyle='#d94f2b';x.fillRect(64,ry,8,150);
    x.fillStyle=P.reasonHd;x.font='700 28px -apple-system,PingFang SC,sans-serif';
    x.fillText('为什么值得看',92,ry+26);
    x.fillStyle=P.reasonTxt;x.font='400 28px -apple-system,PingFang SC,sans-serif';
    wrapText(x,SH_EV.reason,92,ry+66,W-176,44,2);
    y=ry+180;
  }
  x.fillStyle=P.meta;x.font='400 26px -apple-system,sans-serif';
  x.fillText('🔥 '+SH_EV.heat+' 热度 · '+SH_EV.source+' · '+SH_EV.date,64,Math.max(y,H-320));
  x.strokeStyle=P.dash;x.setLineDash([8,8]);x.lineWidth=2;
  x.beginPath();x.moveTo(64,H-240);x.lineTo(W-64,H-240);x.stroke();x.setLineDash([]);
  x.fillStyle=P.qrBox;x.beginPath();x.roundRect(64,H-200,150,150,14);x.fill();
  if(P.qrBorder){x.strokeStyle=P.qrBorder;x.lineWidth=2;x.beginPath();x.roundRect(64,H-200,150,150,14);x.stroke();}
  if(qrImg){x.drawImage(qrImg,74,H-190,130,130);}
  else{x.fillStyle='#666';x.font='400 22px sans-serif';x.fillText('扫码访问',88,H-118);}
  x.fillStyle=P.name;x.font='700 30px -apple-system,PingFang SC,sans-serif';
  x.fillText('扫码阅读全文编译',240,H-176);
  x.fillStyle=P.foot;x.font='400 24px -apple-system,PingFang SC,sans-serif';
  x.fillText('DataHot · 数据领域 AI 热榜',240,H-126);
  x.fillText('henryhb1105-arch.github.io/datahot',240,H-86);
  return c.toDataURL('image/png');
}
var posterURL=null,posterDark=null;
function openPoster(){
  document.getElementById('shPoster').classList.add('show');
  var dark=window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches;
  if(posterURL&&posterDark===dark){return;}
  posterDark=dark;
  var qr=new Image();qr.crossOrigin='anonymous';
  qr.onload=function(){posterURL=drawPoster(qr,dark);showPoster();};
  qr.onerror=function(){posterURL=drawPoster(null,dark);showPoster();};
  qr.src='https://api.qrserver.com/v1/create-qr-code/?size=240x240&margin=0&data='+encodeURIComponent(SH_EV.url);
}
function dataToBlob(d){
  var p=d.split(','),m=p[0].match(/:(.*?);/)[1],b=atob(p[1]),a=new Uint8Array(b.length);
  for(var i=0;i<b.length;i++){a[i]=b.charCodeAt(i);}
  return new Blob([a],{type:m});
}
function showPoster(){
  document.getElementById('shPosterImg').src=posterURL;
  var a=document.getElementById('shSave');
  a.href=URL.createObjectURL(dataToBlob(posterURL)); a.target='_blank';
}
</script>""".replace("__EV_JSON__", ev_json)

def render_topics_map(events, css):
    """主题地图页：8 个主题的卡片墙"""
    cards = ""
    for t in TOPICS_META:
        evs = [e for e in events if t["name"] in e.get("topics", [])]
        if not evs:
            continue
        latest = "".join(f'<div class="tt">· {esc(e["zh_title"][:36])}</div>' for e in evs[:3])
        cards += f'''<a class="tcard" href="topics/{t["slug"]}.html">
  <h3>{esc(t["name"])}</h3>
  <div class="td">{esc(t["desc"])}</div>
  <div class="tn">{len(evs)} 个事件 →</div>{latest}
</a>'''
    return page_shell("主题地图 · DataHot", "按主题看数据领域：8 条持续演进的叙事线", css, f'''
<div class="wrap" style="padding:28px 20px 60px;max-width:900px">
  <div class="section-title"><h2>🗺️ 主题地图</h2><span>按议题看数据领域 · 持续更新</span></div>
  <div class="tgrid">{cards}</div>
</div>''', tabbar("topics"))

def render_topic_page(t, events, css):
    """单个主题页：导语 + 该主题事件时间轴"""
    evs = [e for e in events if t["name"] in e.get("topics", [])]
    vendors = sorted({v for e in evs for v in e.get("vendors", [])})
    vtags = "".join(f'<span class="vtag">{esc(v)}</span>' for v in vendors)
    days = defaultdict(list)
    for e in evs:
        days[day_key(e["published"])].append(e)
    timeline = ""
    for d in sorted(days, reverse=True):
        timeline += f'<div class="day"><div class="day-head"><span class="date">{d.month}月{d.day}日</span><span class="info">{len(days[d])} 个事件</span></div>'
        timeline += "\n".join(render_card(e, prefix="../") for e in days[d])
        timeline += "</div>"
    body = f'''
<div class="wrap" style="padding:28px 20px 60px;max-width:900px">
  <a class="back" href="../topics.html" style="font-size:13px;color:var(--sub)">← 主题地图</a>
  <h1 style="font-size:26px;font-weight:800;margin:14px 0 6px">{esc(t["name"])}</h1>
  <p style="font-size:14px;color:var(--sub);margin-bottom:8px">{esc(t["desc"])}</p>
  <p style="font-size:12.5px;color:var(--sub);margin-bottom:18px">近 7 天收录 {len(evs)} 个事件 · 每 6 小时更新</p>
  {f'<div class="vendors" style="margin-bottom:18px">{vtags}</div>' if vtags else ""}
  {timeline}
</div>'''
    return page_shell(f"{t['name']} · DataHot 主题", t["desc"], css, body, tabbar("topics", "../"), prefix="../")

def page_shell(title, desc, css, body, tabbar_html, prefix=""):
    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="icon" href="{prefix}favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="{prefix}icons/apple-touch-icon.png">
<meta name="theme-color" content="#1a1d23">
<style>{css}
{SHARED_CSS}
</style></head><body>
<header><div class="wrap nav">
  <div class="logo"><a href="{prefix}index.html" style="text-decoration:none">Data<em>Hot</em></a><span class="tag">每 6 小时更新</span></div>
</div></header>
{body}
<footer>DataHot · 数据领域 AI 资讯热榜 · 仅聚合摘要与链接，版权归原作者</footer>
{tabbar_html}
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

    # ── 主题地图 + 主题页 ──
    TOPIC_DIR.mkdir(parents=True, exist_ok=True)
    (SITE / "topics.html").write_text(render_topics_map(events, css), encoding="utf-8")
    valid_topic_slugs = set()
    for t in TOPICS_META:
        if any(t["name"] in e.get("topics", []) for e in events):
            valid_topic_slugs.add(t["slug"] + ".html")
            (TOPIC_DIR / (t["slug"] + ".html")).write_text(render_topic_page(t, events, css), encoding="utf-8")
    for f in TOPIC_DIR.glob("*.html"):
        if f.name not in valid_topic_slugs:
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

    # 主题筛选条：只显示当前有事件的主题
    active_topics = {t for e in events for t in e.get("topics", [])}
    topic_fchips = "".join(
        f'<span class="fchip" data-topic="{esc(t["name"])}">{esc(t["name"])}</span>'
        for t in TOPICS_META if t["name"] in active_topics)

    page = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>DataHot · 数据领域 AI 热榜</title>
<meta name="description" content="监控 Data Agent、AI 数据平台、BI、数据产品四个领域的资讯热榜，多信源聚簇 + AI 中文摘要与推荐理由，每 6 小时更新。">
<meta property="og:title" content="DataHot · 数据领域 AI 热榜">
<meta property="og:description" content="Data Agent / AI 数据平台 / BI / 数据产品的每日热点，每 6 小时自动更新。">
<meta property="og:type" content="website">
<link rel="icon" href="favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="icons/favicon-32.png">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<link rel="manifest" href="icons/manifest.json">
<meta name="theme-color" content="#1a1d23">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="DataHot">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<style>{css}
{SHARED_CSS}
.item a:hover{{color:var(--accent)}}
.hot a:hover{{color:var(--accent)}}
#ptr{{position:fixed;top:0;left:0;right:0;height:0;overflow:hidden;display:flex;align-items:flex-end;justify-content:center;background:var(--bg);z-index:60;transition:height .12s ease-out}}
#ptr span{{font-size:12.5px;color:var(--sub);padding-bottom:8px}}
</style></head><body>
<div id="ptr"><span>下拉刷新</span></div>
<header><div class="wrap nav">
  <div class="logo">Data<em>Hot</em><span class="tag">每 6 小时更新</span></div>
  <a class="tab d-only" href="topics.html" style="text-decoration:none">🗺️ 主题</a>
</div></header>

<div class="wrap"><div class="layout"><main>
  <div class="section-title"><h2>🔥 本期热点</h2><span>多信源聚簇 · 按热度排序</span></div>
  <div class="hotlist">{hot_cards}</div>
  <div class="section-title" style="align-items:center"><h2>📅 时间轴</h2><span>近 7 天</span>
    <input id="q" class="tlsearch" placeholder="🔍 搜索">
  </div>
  <div class="chiprow" id="chiprow">
    <span class="fchip on" data-topic="all">全部</span>
    {topic_fchips}
  </div>
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
{tabbar("home")}

<script>
// 主题筛选条
document.querySelectorAll('#chiprow .fchip').forEach(c=>c.addEventListener('click',()=>{{
  document.querySelectorAll('#chiprow .fchip').forEach(x=>x.classList.remove('on'));
  c.classList.add('on');
  const t=c.dataset.topic;
  document.querySelectorAll('.item').forEach(el=>{{
    el.style.display=(t==='all'||(el.dataset.topics||'').split('|').includes(t))?'':'none';
  }});
  document.querySelectorAll('.day').forEach(d=>{{
    const any=Array.from(d.querySelectorAll('.item')).some(el=>el.style.display!=='none');
    d.style.display=any?'':'none';
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
// 移动端下拉刷新
(function(){{
  const ind=document.getElementById('ptr');
  let startY=null,dy=0;
  const THRESH=72;
  window.addEventListener('touchstart',e=>{{
    startY=(window.scrollY<=0)?e.touches[0].clientY:null;
    dy=0;
  }},{{passive:true}});
  window.addEventListener('touchmove',e=>{{
    if(startY===null) return;
    dy=e.touches[0].clientY-startY;
    if(dy<=0||window.scrollY>0){{ind.style.height='0px';return;}}
    if(dy>8&&e.cancelable) e.preventDefault();
    const h=Math.min(dy*0.5,THRESH+20);
    ind.style.height=h+'px';
    ind.firstElementChild.textContent=dy>THRESH?'松开刷新':'下拉刷新';
  }},{{passive:false}});
  window.addEventListener('touchend',()=>{{
    if(dy>THRESH){{
      ind.firstElementChild.textContent='刷新中…';
      location.reload();
    }}else{{
      ind.style.height='0px';
    }}
    startY=null;dy=0;
  }},{{passive:true}});
}})();
</script>
</body></html>'''

    out = SITE / "index.html"
    out.write_text(page, encoding="utf-8")
    print(f"[render] 首页 ({len(page)//1024} KB) + 详情页 {len(valid_ids)} 个")

if __name__ == "__main__":
    main()
