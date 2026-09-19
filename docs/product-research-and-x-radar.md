# 产品研究与 X 候选入口

产品身份维护在 `pipeline/products.json`。只根据明确的产品名称、精确官方域名或人工确认的事件 ID 归属；不能把厂商所有新闻自动算到某个产品上。五条实施路径位于 `pipeline/learning_paths.json`，新增引用必须通过本地文章和案例存在性检查。

`products.html` 聚合 10 个产品；单产品页连接动态、精选和案例。`paths.html` 提供五方向 15 个步骤，实施建议与原文事实分开。客户端关注仍保存在原有本地存储中，旧主题/厂商关注不丢失。

## X 的成本边界

**当前未启用付费采集，无新增定时器。** `python3 pipeline/x_radar.py` 只输出离线计划；默认预算为 0，即使加 `--execute` 也不会发出请求。当前 allowlist 从三个已核对官方账号开始：Databricks、Hex、Metabase；后续扩展需核对账号归属。

- [X 官方计价](https://docs.x.com/x-api/getting-started/pricing)：2026-09-19 核对，读取帖子为每条 $0.005；具体账户价格以控制台为准。
- [近期搜索](https://docs.x.com/x-api/posts/search-recent-posts) 只覆盖近 7 天。每批最多 50 条，单次每周最多 200 条，按此价格上界 $1；滚动 31 天预算最多 $5。实际账单可能低于保守预留额。
- 只有同时设置 enabled、非零预算、30 天内核对的价格与控制台限额、专用读取 token，才允许执行。控制台限额须由操作者实际核对后填写日期，不能用代码内预算替代账户限额。
- 请求前将整批最大费用写入持久账本；网络异常不退款、不自动重试；7 天内重复执行使用缓存。独占文件锁避免并发透支。损坏账本失败关闭，不能删除账本来恢复额度。
- 只调用近期搜索，不展开用户/媒体、不获取全年历史、不发布 X 帖子；token 只从环境读取。每次最多 4 次读取请求，不调用模型。滚动预算仅约束本采集器，账户内其他应用另计。
- 结果仅进入 `.local/x-radar/state.json`，不进入公开站点。按帖子 ID 与规范化来源链接去重；预算截断时明确 `coverage_complete=false`，不能宣称“抓全”。搜索起点留 2 分钟余量，不能视为完整档案。
- 编辑核验后通过既有 manual batch 流程发布：优先引用官方文章，保留 X 发现入口，标明版本和发布日期。不要把原始推文直接自动发布到站点。

账号核对依据：[Databricks 合作伙伴手册](https://www.databricks.com/sites/default/files/2024-08/guide-databricks-partner-program-for-isvs.pdf)、[Hex 官方提示指南](https://marketing.hex.tech/blog/notebook-agent-prompting-guide-agentic-analytics/)、[Metabase 官方社区](https://discourse.metabase.com/t/metabase-community-highlights/6219)。

本轮只用模拟响应测试预算、去重与失败行为。启用前需确认专用读取凭据、账户限额和当前价格，并先进行一次受预算约束的端到端验证。
