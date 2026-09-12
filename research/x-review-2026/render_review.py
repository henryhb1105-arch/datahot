"""Render a static, source-linked editorial review; never alters published content."""
import hashlib
import json
import re
from collections import Counter
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent
RAW = Path('/tmp/datahot-x-review-2026')
DEST = Path('/Users/henry-mini/.codex/visualizations/2026/09/12/01a09336-f00b-7aa0-ae72-ec83a82a2c60/datahot-x-review-2026')

def main():
    rows=json.loads((ROOT/'candidates.json').read_text())
    ledger=json.loads((ROOT/'budget.json').read_text())
    posts=json.loads((RAW/'posts.json').read_text())
    queries=json.loads((ROOT/'queries.json').read_text())
    existing=json.loads((ROOT/'existing-index.json').read_text())
    returned=sum(v['returned_posts'] for v in ledger['requests'].values())
    assert ledger['closed'] and len(ledger['requests'])==30
    assert returned==193 and len(posts)==178 and len(rows)==20
    accounts=sorted(set(re.findall(r'from:([A-Za-z0-9_]+)', ' '.join(q['query'] for q in queries))),key=str.lower)
    matched=sum(bool(r['x_posts']) for r in rows)
    coverage={'period_start':'2026-01-01T00:00:00Z','period_end':'2026-09-12T04:50:00Z',
              'method':'30 bounded relevance-ranked search slices; max 10 posts per slice; no pagination',
              'accounts_queried':accounts,'completed_search_requests':30,
              'slices_with_more_results':sum(v['more_results'] for v in ledger['requests'].values()),
              'returned_post_resources':returned,'unique_post_ids':len(posts),
              'conservative_estimated_x_usd':round(returned*0.005,3),
              'estimate_if_24h_deduplication_applies_usd':round(len(posts)*0.005,3),
              'price_source':'https://docs.x.com/x-api/getting-started/pricing',
              'price_checked_date':'2026-09-12','actual_invoice_verified':False,
              'one_off_user_budget_usd':5,'implemented_maximum_post_capacity':300,
              'implemented_maximum_estimated_x_usd':1.5,'budget_closed':True,
              'workflow_trigger_removed_commit':'b26c4d6d',
              'runs':[34674397604,34674484504],
              'artifacts':[10291618817,10291504554],
              'existing_event_index_count':len(existing),
              'existing_index_sha256':hashlib.sha256((ROOT/'existing-index.json').read_bytes()).hexdigest(),
              'candidates':20,'candidates_with_x_evidence':matched,'website_supplement_candidates':20-matched,
              'full_archive_coverage':False,'site_published':False,
              'separate_paid_model_api_calls':0,'paid_scraping_service_calls':0,
              'cost_exclusions':['Current Codex session usage','Account-specific GitHub billing or taxes, if any'],
              'verification':'All 20 primary sources inspected through web tools or public HTML; URL duplicate check against indexed existing events; no production feature execution.'}
    (ROOT/'coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2)+'\n')
    intro=f'''# DataHot · 2026 数据与 AI 精选候选

审阅稿 · 2026 年 9 月 12 日 · [Issue #204](https://github.com/henryhb1105-arch/datahot/issues/204)

已整理 **20 条新增候选**：数据 Agent 7 条、AI 数据平台 4 条、语义层 4 条、AI 数据分析 3 条、AI 看板 / 数据产品 2 条。**其中 {matched} 条有本次 X 采集证据，{20-matched} 条由官方网页补充**。以下是选题卡片与推荐意见，不是原文翻译，也尚未导入站点。

本次查询覆盖 **2026-01-01 至 2026-09-12 12:50（北京时间）**。分月、分主题抽样，每片最多 10 条，共 30 次历史搜索，返回 **193 条资源 / 178 个不同帖子**。有 {coverage['slices_with_more_results']} 个查询仍有下一页，为控制成本没有继续翻页。因此它是年度范围内的精选回看，不能声称穷尽 2026 年所有相关 X 内容；9 月以后尚未发生的内容也不在范围内。

**费用：X 保守估算 $0.965，约 $0.97。** 按 [X 官方定价](https://docs.x.com/x-api/getting-started/pricing) $0.005/返回帖子计算；若平台当日去重正常生效，178 个不同帖子对应 $0.89。账单实扣未核验，报告按较高值预算。本次没有另行调用付费模型 API 或付费抓取服务；当前 Codex 会话用量不计入这个 X 费用数字，账户特定的 GitHub 费用和税费也未计入。没有购买订阅或充值。

原授权上限 $5；实际程序只预留最多 300 条 / $1.50。遇到预算账本冲突时在下一次 X 请求之前停止，恢复时跳过已完成查询，未重读付费结果。现在账本已关闭，临时采集触发器已删除，没有后续自动消费任务。

本次查询的 12 个账号条件：{', '.join('@'+a for a in accounts)}。这是查询范围，不表示每个账号都有返回结果，也不能以某个查询无结果推断公司没有发布相关内容。后续须按信源分别评估命中率；泛 AI 账号的 `agent` 一词噪声偏高，应限定数据分析场景，Google 的 Genie 也存在与世界模型重名的误命中。

筛选依据：能否解决一个明确的产品或工程问题；是否有代码、架构、实验或具名实践支撑；是否可复用；是否带来新的认知；功能状态能否核对。互动量不作主要排序依据。A 级为本轮优先阅读的编辑判断，不是实验评分；厂商性能或成本数字均未独立复现。

下面先按方向浏览，再看完整推荐理由。每条的“原文要点”仅陈述来源内容，“推荐理由”是本次编辑判断。

| 编号 | 方向 | 内容 | 来源路径 |
|---|---|---|---|
'''
    lines=[intro]
    for r in rows:
        lines.append(f"| {r['id']} | {r['category']} | [{r['title']}](#{r['id'].lower()}) | {'X + 官网' if r['x_posts'] else '官网补充'} |")
    for r in rows:
        links=' · '.join(f"[X 线索 {i+1}]({p['url']})（{p['date']}）" for i,p in enumerate(r['x_posts']))
        extras=' · '.join(f'[补充来源 {i+1}]({u})' for i,u in enumerate(r['extra_sources']))
        lines.append(f"\n<a id=\"{r['id'].lower()}\"></a>\n\n## {r['id']} · {r['title']}\n\n{r['category']} · {r['vendor']} · {r['source_date']} · {r['evidence']}\n\n**原文要点：** {r['facts']}\n\n**推荐理由：** {r['recommendation']}\n\n**状态与边界：** {r['boundary']}\n\n[阅读原文]({r['source_url']})"+((' · '+extras) if extras else '')+(('\n\n'+links) if links else '\n\n发现方式：官网补充；不冒充 X 发现。'))
    lines.append('''

## 去重与淘汰记录

以本次基线的 414 条站内事件及其中 19 条常驻精选为去重参照，移除跟踪参数、统一域名与路径后，20 条候选均未命中已有原文链接；这不意味着同一产品从未报道过。当前站点持续更新，正式入库前还应针对最新主线再查一次。

| 淘汰内容 | 原因 |
|---|---|
| ThoughtSpot AgentQL | 已收录，事件 5422d3495b2d |
| ThoughtSpot ChartSpec | 已收录，事件 ecaefd096734 |
| Google Data Agent Kit 跨源分析教程 | 已收录，事件 b37fd3d1c6d4 |
| OpenAI 内部数据 Agent、a16z 数据 Agent 上下文、Databricks 质量与成本评测 | 已有同源内容，不重复计为新候选 |
| Snowflake 同一天发布的三条相同平台消息 | 合并到 R08，作为一条选题 |
| 峰会报名、获奖、融资、模型接入、节日营销 | 缺少本次关注的可复用产品或工程内容 |
| 泛 coding agent、浏览器生成、Google 世界模型 Genie | 与数据 Agent 场景不符 |

## 在 DataHot 上怎么展示

建议沿用现有内容卡片，增加或映射这五类主题标签，不另建 X 时间流。卡片展示中文标题、公司、原文日期和一句具体推荐理由；X 只是发现来源，放在来源区，正文仍以原文章节、代码和图表为中心。跨平台的同一产品发布只保留一个事件。

详情页保留原文入口；需要中文时沿原文结构忠实翻译。编辑判断放在“推荐理由”，不要混入原文。若拿不到全文，显示简短摘介和原文链接，不用 AI 扩写冒充原文。本文卡片的要点只供选题审阅。

历史精选进入长期主题库，以真实发布时间显示，不伪装成今天的新闻。官网与 X 链接都作为来源保留；不要在首屏加载 X 嵌入脚本或实时调用 X API，避免增加页面加载负担和阅读依赖。

## 下一轮成本建议（尚未启用）

每周先查官方 changelog、博客和可用 RSS，再用 X 补漏；通常取 50–100 条新帖子，不做固定数量的发布任务。建议 X 月度总读取上限 500 条，对应公开单价下最多 $2.50。查询按账号和明确主题拆分，逐次预留预算，保存 since_id / 时间边界，失败不盲目重试；同一 URL 和产品事件跨来源合并。

193 条返回资源最后支撑了 8 条入选内容，说明 X 有补充价值；同时，按相关性取前 10 条会偏向热门发布，不能据此评价全部账号质量。本轮不需要扩到 800 条，也不建议为找齐更多帖子继续花钱。

此次只完成采集验证与候选审阅稿，没有启动每周自动任务，没有发布这 20 条内容。正式入库要按最新主线重新去重，并完成原文、图片、功能状态及站点发布验证。
''')
    md='\n'.join(lines).rstrip()+'\n'
    (ROOT/'review.md').write_text(md)
    cards=[]
    for r in rows:
        xlinks=' '.join(f'<a href="{escape(p["url"],quote=True)}" target="_blank" rel="noopener">X 线索</a>' for p in r['x_posts'])
        cards.append(f'<article id="{r["id"].lower()}"><div class="meta">{r["id"]} · {escape(r["category"])} · {escape(r["vendor"])} · {escape(r["source_date"])}</div><h2>{escape(r["title"])}</h2><p>{escape(r["facts"])}</p><p class="reason"><strong>推荐理由：</strong>{escape(r["recommendation"])}</p><details><summary>证据与功能状态</summary><p>{escape(r["boundary"])}</p><p>{escape(r["evidence"])} · {escape(r["discovery"])}</p></details><div class="links"><a href="{escape(r["source_url"],quote=True)}" target="_blank" rel="noopener">阅读原文 ↗</a>{xlinks}</div></article>')
    nav=''.join(f'<a href="#{r["id"].lower()}">{escape(r["category"])}</a>' for i,r in enumerate(rows) if i==0 or r['category']!=rows[i-1]['category'])
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DataHot · 2026 精选审阅稿</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#17202d;font:16px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1000px;margin:auto;padding:40px 24px}header{margin-bottom:24px}h1{font-size:32px;line-height:1.35;margin:12px 0}h2{font-size:21px;line-height:1.5;margin:10px 0}.eyebrow,.meta{color:#637184;font-size:13px}.summary{background:#e7f1ed;border-radius:8px;padding:16px 20px}nav{display:flex;flex-wrap:wrap;gap:10px;margin:24px 0}nav a{background:white;border:1px solid #dce2e8;padding:6px 12px;border-radius:6px}a{color:#185c70;text-underline-offset:3px}article{padding:24px;background:white;border:1px solid #e0e5ea;border-radius:10px;margin:16px 0;scroll-margin:16px}p{margin:10px 0}.reason{border-left:3px solid #66a08a;padding-left:12px}summary{cursor:pointer;color:#536171}.links{display:flex;gap:16px;margin-top:16px}footer{padding:20px 0;color:#637184;font-size:14px}@media(max-width:600px){main{padding:22px 16px}h1{font-size:26px}article{padding:18px}h2{font-size:19px}}
    </style><main><header><div class="eyebrow">DATAHOT / 2026 RESEARCH / 审阅稿</div><h1>值得长期保留的 20 条数据与 AI 内容</h1><p>数据 Agent 优先，围绕平台、语义、分析和数据产品建设。</p><div class="summary"><strong>193 条 X 返回资源 → 178 条去重帖子 → 8 条 X 线索入选 + 12 条官网补充</strong><br>X 费用保守估算 $0.97，账单实扣未核验。采集已关闭；内容尚未上站。</div><p class="meta">范围：2026-01-01 至 2026-09-12；分月抽样，不是全量归档。每条均附原文与推荐理由。</p></header>'''+f'<nav>{nav}</nav>'+''.join(cards)+'''<footer>此页是编辑审阅预览，正文要点不代替原文或忠实翻译。完整成本、去重和展示方案见同目录 review.md。页面为纯静态文件，无远程字体、图片、脚本或 API 请求。</footer></main></html>'''
    (ROOT/'preview.html').write_text(html)
    DEST.mkdir(parents=True,exist_ok=True)
    for name in ['review.md','preview.html','candidates.json','coverage.json']:
        (DEST/name).write_bytes((ROOT/name).read_bytes())
    print(json.dumps({'preview':str(DEST/'preview.html'),'review':str(DEST/'review.md'),
                      'html_bytes':len(html.encode()),'category_counts':dict(Counter(r['category'] for r in rows)),
                      'verification':'20 candidates, 8 X-matched, 193 returned, 178 unique, budget closed'},ensure_ascii=False))

if __name__=='__main__':main()
