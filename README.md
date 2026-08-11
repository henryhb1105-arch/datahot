# DataHot · 数据领域 AI 资讯热榜

监控 **Data Agent / AI 数据平台 / BI / 数据产品** 四个领域的资讯聚合站。
多信源采集 → LLM 过滤加工（中文摘要 + 推荐理由 + 分类 + 热度分）→ 静态站点，每 6 小时自动更新。

## 架构

```
RSS/API 采集 ──► LLM 加工（DeepSeek）──► latest.json ──► 静态 HTML ──► GitHub Pages
（12 个信源）    （过滤·摘要·推荐理由）      （跨次累积）     （无后端）
```

- `pipeline/sources.json` — 信源配置（`enabled: false` 的为待解封源）
- `pipeline/run_update.py` — 采集 / 过滤 / LLM 加工 / 打分 / 数据输出
- `pipeline/build_site.py` — 静态页面渲染
- `pipeline/check_links.py` — 全站本地 `href/src` 完整性检查（失效链接会阻断构建）
- `pipeline/config.json` — 本地 LLM 密钥（**已 gitignore，不要提交**）
- `.github/workflows/update.yml` — 每 6 小时定时运行 + 自动发布 Pages

## 本地运行

```bash
# 1. 配置 LLM（编辑 pipeline/config.json 填入 DeepSeek Key）
cp pipeline/.env.example pipeline/config.json

# 2. 更新数据并生成站点
python3 pipeline/run_update.py && python3 pipeline/build_site.py

# 可独立复查已生成站点；有效率必须为 100%
python3 pipeline/check_links.py site

# 3. 本地预览
cd site && npm run dev   # 或 python3 -m http.server
```

## 部署

GitHub Actions 每 6 小时自动运行（UTC 0/6/12/18 第 17 分），数据回写仓库、站点发布到 `gh-pages` 分支。
仓库 Secrets 需配置：`LLM_API_KEY`（DeepSeek）。

### DeepSeek 用量与预算

每次更新会将调用次数、输入/输出 Token、失败调用、用途和信源统计写入 `site/data/llm_usage.json`，并在 GitHub Actions Summary 中显示本次汇总。记录中不保存 prompt 或模型回答正文；若供应商未返回 usage，会明确标记并按请求前估算值扣减预算。

可在仓库 Actions Variables 中调整：

- `MAX_LLM_TOKENS_PER_RUN`：单次更新的 Token 上限，默认 `160000`
- `MAX_LLM_TOKENS_PER_DAY`：自然日 Token 上限，默认 `500000`
- `MAX_COMPILE_EVENTS_PER_RUN`：每次最多生成全文编译稿的事件数，默认 `8`
- `CANDIDATE_CACHE_ENABLED`：是否开启候选判定缓存，默认 `true`
- `CANDIDATE_CACHE_TTL_DAYS`：accepted/rejected 判定保留天数，默认 `21`
- `CANDIDATE_CACHE_ERROR_TTL_HOURS`：失败候选的重试退避时长，默认 `6`

达到上限时会在 API 请求前停止新调用，不影响已采集原文的保留和静态站点构建。候选缓存会原子写入 `site/data/candidate_cache.json`；同 URL、同内容、同模型与规则版本在 TTL 内不会重复调用相关性模型。

### 信源调度与预筛

`pipeline/sources.json` 支持为每个信源独立配置 `fetch_interval_hours`、`max_candidates_per_run`、`lookback_days`、`require_published`、`path_include/path_exclude` 和 `include_keywords/exclude_keywords`。删除这些可选字段即回退到每 6 小时、单轮 20 条、7 天窗口、无关键词限制的默认行为。手动补数时可临时设置 `FORCE_SOURCE_FETCH=true` 绕过分频，不会改写信源配置。

每轮的调度原因、预筛数、候选数、采用率、模型调用数和 Token 会写入 `site/data/sources_status.json`。连续三轮有候选但零采用时只记录降频建议，不会自动停用或删除信源。

### 事件优先加工流程

默认 `PIPELINE_ORDER=event_first`：元数据采集 → 候选缓存 → 规则初筛 → 当轮聚簇 → 选主来源 → 只抓主来源正文 → LLM 元数据加工 → 事件正文。普通新闻生成 600–1200 字符的关键事实、行业影响和实践要点；置顶、常青或重要度达标的事件才进入深度编译。

- `MAX_DEEP_EVENTS_PER_RUN`：单轮深度正文上限，默认 `2`
- `DEEP_IMPORTANCE_THRESHOLD`：深度正文重要度门槛，默认 `80`
- `CLUSTER_CACHE_TTL_DAYS`：标题/事件聚簇判定缓存，默认 `14` 天

正文预算耗尽时直接降级为已有中文摘要，构建不中断。如需紧急回滚加工顺序，将 Actions Variable `PIPELINE_ORDER` 设为 `legacy`；候选、Token 和信源控制数据不会被删除。

### 结构化正文安全模型

正文优先保存为 `blocks-v1`，支持 `heading`、`paragraph`、`list`、`blockquote`、`code`、`table` 和 `figure`；文本节点支持 `strong`、`em`、`code`、`link` 和 DataHot 语义颜色 token。block 与文本节点都有稳定 ID。DeepSeek 只接收 `{id, text}` 列表并返回相同 ID，本地合并译文，因此不会让模型改写链接、marks 或块结构。

抓取的第三方 HTML 不会直接入库或渲染：脚本、iframe、Canvas、事件属性和非 HTTP(S) 协议会被移除，颜色只映射到站点设计 token。渲染前会再次清洗；blocks 缺失或异常时继续使用已有 `full_zh` 安全纯文本兼容层。

图片与静态图表只在同站点来源、未声明 `noimageindex` 且通过公网 URL、MIME、文件大小和像素上限检查后缓存到 `site/media/<event_id>/`。位图通过 Pillow 重新编码以清除 EXIF 和任意元数据；SVG 只保留静态图形白名单，删除脚本、外部引用和危险属性。默认每事件最多 3 张、单文件 5 MB、总缓存 250 MB，过期事件目录随数据一起清理。缓存失败时不热链，只显示图注、来源和原图入口。设置 `MEDIA_BLOCKS_ENABLED=false` 可立即关闭图片渲染并保留这些可追溯信息。

### 隐私友好行为分析

分析客户端默认关闭，只有配置公开 HTTPS 接收端后才在正式域名发送字段白名单事件；localhost、测试、GPC/DNT 和手动关闭均不发送。它不采集正文、完整搜索词、Cookie、身份、指纹或位置。事件 schema、去重规则、接收端契约和指标公式见 [`ANALYTICS.md`](ANALYTICS.md)，NDJSON 导出可用 `python3 pipeline/analytics_metrics.py export.ndjson` 先做质量校验再计算指标。

## 内容声明

本站仅聚合各信源的摘要与原文链接，不转载全文，版权归原作者所有。
