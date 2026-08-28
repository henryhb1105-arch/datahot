# DataHot 信源发现与内容质量闭环

## 边界

信源侦察与公开发布是两个系统。侦察器只负责扩大候选召回，输出写入
`pipeline/discovery_state/`；候选不会自动加入 `pipeline/sources.json`，也不会进入
首页、热榜、周报或 Agent Feed。

## 每轮如何发现

`python3 pipeline/run_discovery.py` 与现有定时更新共用同一串行工作流，默认每 20
小时实际执行一次：

1. OpenAI Responses API Web Search：按 `pipeline/discovery_queries.json` 轮换查询，
   排除已接入域名，并保存 `web_search_call.action.sources` 返回的可追溯 URL。
2. Hacker News 官方 API：读取 top/best/new，社区分数只作为趋势信号，仍需本地相关性
   过滤和后续质量审核。
3. 已收录优质文章的引用图：同一未知域名被至少两篇质量不低于 70 的文章引用时，
   进入候选池。

没有 `OPENAI_API_KEY` 时第一条会明确记录为 skipped，HN 与引用图继续运行，不能因此
中断资讯更新或 Pages 发布。正式启用 Web Search 时，在 GitHub Actions Secrets 添加
`OPENAI_API_KEY`；模型默认 `gpt-5.6`，可通过 `DISCOVERY_OPENAI_MODEL` 调整。当前接口
参数以 [OpenAI Web Search 官方文档](https://developers.openai.com/api/docs/guides/tools-web-search)
为准。

## 生命周期

- `DISCOVERED`：首次出现，证据不足。
- `PROBATION`：至少两个独立发现通道，或累计三篇不同候选文章；仍不公开。
- `ACTIVE`：编辑确认抓取稳定、正文可用且内容质量合格后，人工加入正式信源配置。
- `DEGRADED`：现有信源连续失败至少三次；只提醒，不自动删除或停用。
- `PAUSED`：配置中明确关闭，或由编辑决定暂停。

`scout.json` 同时保存文章候选、未知域名候选和现有信源健康快照。`latest_report.md`
只呈现最值得检查的候选和异常，不把内部运行指标放到读者页面。

## 三类评分

- `quality_score`：原创性、证据密度、信息增量、可操作深度四项各 0–25 分。
- `trend_score`：新鲜度、社区关注和多信源印证；不包含内容质量。
- `fit_score`：只在浏览器端根据显式关注和文章反馈计算，不写成全局事实。

兼容字段 `importance` 暂时等于 `quality_score`；`heat` 保持原排序数值语义，等于内容
质量 45% 加趋势 55%。这样现有页面和 Agent 客户端无需同步升级。

## 反馈

详情页的“有用/没用”与可选原因写入 `dh_content_feedback_v1`，不保存正文和自由文本。
它会立即调整当前设备上的 For Me 适合度；“太浅、营销、正文差”等质量反馈不会被误当
成主题偏好。

匿名统计默认关闭。只有配置 HTTPS 第一方接收端且用户未启用 GPC/DNT/关闭统计时，
才发送事件 ID、`useful/not_useful` 和固定原因枚举，供导出的 NDJSON 计算“值得读比例”。

## 验收指标

- 推荐候选中已收录 URL 的比例与漏检率。
- 原文发布时间到首次发现的时延。
- 新域名从 DISCOVERED 到 PROBATION 的数量和最终采用率。
- 前 10 篇的“有用”比例，以及营销/太浅/正文质量差的原因分布。
- 每个正式信源的抓取成功率、采用率、连续零采用和全文成功率。
