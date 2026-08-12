# DataHot · 数据领域 AI 资讯热榜

监控 **Data Agent / AI 数据平台 / BI / 数据产品 / AI分析** 五个领域的资讯聚合站。
多信源采集 → LLM 过滤加工（中文摘要 + 推荐理由 + 分类 + 热度分）→ 静态站点，每 6 小时自动更新。

## 架构

```
RSS/API 采集 ──► LLM 加工（DeepSeek）──► latest.json ──► 静态 HTML ──► GitHub Pages
（12 个信源）    （过滤·摘要·推荐理由）      （跨次累积）     （无后端）
```

- `pipeline/sources.json` — 信源配置（`enabled: false` 的为待解封源）
- `pipeline/run_update.py` — 采集 / 过滤 / LLM 加工 / 打分 / 数据输出
- `pipeline/build_site.py` — 静态页面渲染
- `pipeline/lite_data.py` — 首页/搜索/收藏的轻量数据与首屏结构规则
- `pipeline/check_links.py` — 全站本地 `href/src` 完整性检查（失效链接会阻断构建）
- `pipeline/config.json` — 本地 LLM 密钥（**已 gitignore，不要提交**）
- `.github/workflows/update.yml` — 每 6 小时定时运行 + 自动发布 Pages
- `.github/workflows/deploy.yml` — 源码合并后只构建/测试/发布，不调用 DeepSeek

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

正文优先保存为 `blocks-v1`，支持 `heading`、`paragraph`、`list`、`blockquote`、`code`、`table` 和 `figure`；表格保留安全范围内的 `rowspan` / `colspan`，文本节点支持 `strong`、`em`、`code`、`link` 和 DataHot 语义颜色 token。block 与文本节点都有稳定 ID。DeepSeek 只接收正文、图注和替代文字的 `{id, text}` 列表并返回相同 ID，本地合并译文，因此不会让模型改写图片地址、链接、marks 或块结构。

正文根节点按 `article` → `main` → 语义内容容器 → JSON-LD `articleBody` → 最大正文容器 → 全页兜底的顺序选择；每个结果会记录命中策略、正文块数、图片/表格数和回退原因。图片按原文流内位置保留，过滤 logo、头像、小尺寸装饰图和重复图，再按图注、替代文字、尺寸及 chart/diagram 等解释性信号选出最多 3 张。图片和表格不会因普通正文的 1200 字符预算被截掉。

抓取的第三方 HTML 不会直接入库或渲染：脚本、iframe、Canvas、事件属性和非 HTTP(S) 协议会被移除，颜色只映射到站点设计 token。渲染前会再次清洗；blocks 缺失或异常时继续使用已有 `full_zh` 安全纯文本兼容层。

图片与静态图表只在同站点来源、未声明 `noimageindex` 且通过公网 URL、MIME、文件大小和像素上限检查后缓存到 `site/media/<event_id>/`。位图通过 Pillow 重新编码以清除 EXIF 和任意元数据；SVG 只保留静态图形白名单，删除脚本、外部引用和危险属性。默认每事件最多 3 张、单文件 5 MB、总缓存 250 MB，过期事件目录随数据一起清理。缓存失败时不热链，只显示图注、来源和原图入口。设置 `MEDIA_BLOCKS_ENABLED=false` 可立即关闭图片渲染并保留这些可追溯信息。

每轮还会限量检查近期高价值的旧事件，只对确实解析出图片或表格的文章补齐结构化正文；默认最多成功回填 2 篇、回看 30 天、尝试 12 篇，失败或无视觉内容后 7 天内不重试。可用 `CONTENT_BLOCKS_BACKFILL_LIMIT`、`CONTENT_BLOCKS_BACKFILL_DAYS` 和 `CONTENT_BLOCKS_BACKFILL_ATTEMPTS` 调整，设 `CONTENT_BLOCKS_BACKFILL_LIMIT=0` 可关闭。当前轮命中率、解析策略、回退原因、图片/表格与缓存数量写入 `latest.json` 的 `structured_content`、各信源的 `last_structured_content`，并显示在 GitHub Actions Summary。

### 隐私友好行为分析

分析客户端默认关闭，只有配置公开 HTTPS 接收端后才在正式域名发送字段白名单事件；localhost、测试、GPC/DNT 和手动关闭均不发送。它不采集正文、完整搜索词、Cookie、身份、指纹或位置。事件 schema、去重规则、接收端契约和指标公式见 [`ANALYTICS.md`](ANALYTICS.md)，NDJSON 导出可用 `python3 pipeline/analytics_metrics.py export.ndjson` 先做质量校验再计算指标。

首页默认只静态输出 20 条并使用不含正文的 `latest-lite.json` 完成加载更多、搜索和收藏；首屏厂商上限、栏目软阈值、当前体积基线和一键回滚见 [`PERFORMANCE.md`](PERFORMANCE.md)。

### 每周简报

Issue [#33](https://github.com/henryhb1105-arch/datahot/issues/33) 将周报拆为三层：每日观察只提供候选信号；周度分析重新读取本周全部合格的规范化事件，并与过去 4 周可重放快照比较；个人编辑只引用已经通过校验的公共 `signal_id`，负责解释“这对 Henry 意味着什么”和行动建议。日报结论不能替代原始证据，事件校验通过也不代表跨事件趋势成立。

每周一北京时间 08:17 处理上一个完整自然周（周一至周日）。周度分析会规范化去重、按具体产品机制聚类、检查信源家族与证据独立性，并允许输出 0–3 个主题。没有历史基线时只能标记 `early_signal` 或 `unknown`；单一供应商或客户案例不能成为高置信趋势；异质事件不能因为都涉及 AI、成本或可靠性而强行合并。本周与过去 4 周的输入保存在 `site/data/weekly_inputs/`，公共信号写入 `weekly_signals.json` 及其历史目录，个人周报写入 `weekly_brief.json` 及 `weekly/`。

两层模型输出都使用固定 JSON Schema、合法 `event_id`、证据标题和跨层引用校验；失败时仅重试一次。模型未配置、调用失败、预算耗尽或任一层校验失败时，周报保持“整理中”，不会发布规则叙事，下一次定时任务仍会重试。只有 AI 结果完整通过后才进入同周不可变缓存；缓存覆盖本周输入、4 周基线、两层 Prompt、Schema 和模型版本。页面只展示结论、具体锚点、个人影响和行动，资讯标题集中在默认折叠的证据索引中。

两层调用均以 `weekly_brief` 用途计入 `llm_usage.json`，并分别标记 `weekly_signals` 与 `weekly_personal`。设置 `WEEKLY_BRIEF_ENABLED=false` 可停止生成并隐藏入口；`WEEKLY_BRIEF_FORCE=true` 只在手动触发工作流时生效。已有 `DAILY_BRIEF_ENABLED` / `DAILY_BRIEF_FORCE` 仓库变量继续作为迁移期后备值。

### Atom Feed

站点构建会生成 [`feed.xml`](https://henryhb1105-arch.github.io/datahot/feed.xml)，并在所有页面 `<head>` 声明 `application/atom+xml` 自动发现入口。每条 Feed 只包含 DataHot 标题、摘要、稳定详情链接、时间、分类和首要信源，不嵌入第三方全文、图片或任意 HTML。构建会校验 XML、HTTPS 绝对链接、稳定唯一 ID 和对应详情文件；设置 `FEED_ENABLED=false` 可停止生成并移除自动发现声明。

### 本地精华朗读

详情页可读取 `site/data/tts-manifest.json`，只在同站点 MP3 已生成且路径通过白名单校验时显示“听这篇”。朗读稿由 `pipeline/tts_text.py` 从标题、摘要、推荐理由和正文关键段落确定性提取，自动排除 URL、代码、表格、来源列表与免责声明，不调用 DeepSeek。`pipeline/tts_generate.py --dry-run` 可在没有语音模型的机器上检查待生成队列。

正式音频由带 `datahot-tts` 标签的 Mac mini self-hosted runner 使用本地 Qwen3-TTS Base 模型生成。工作流默认由 `TTS_RUNNER_ENABLED=false` 关闭；启用前需要在 runner 本机准备 Python 环境、模型、已确认的 `datahot-anchor-v1` 参考音频和准确文本，并配置：

- `TTS_RUNNER_ENABLED=true`
- `TTS_PYTHON`：本地 Qwen TTS 虚拟环境 Python 的绝对路径
- `TTS_MODEL_PATH`：本地 Qwen3-TTS Base 模型目录
- `TTS_REFERENCE_AUDIO` / `TTS_REFERENCE_TEXT_FILE`：参考音频与逐字稿
- `TTS_MAX_EVENTS_PER_RUN`：单轮上限，默认 `8`
- `TTS_MAX_CHARACTERS`：单篇字符上限，默认 `350`
- `TTS_RETENTION_DAYS`：音频保留期，默认 `30`
- `TTS_AUDIO_BITRATE`：默认 `64k`

Mac runner 只有仓库内容写权限，不拥有部署控制权；它提交 MP3 与 manifest 后，由下一轮既有定时更新发布到 Pages。生成失败不会阻塞文字站点，缺少 ready 音频的页面不会渲染播放器。将 `TTS_RUNNER_ENABLED=false` 可停止新音频任务。

## 内容声明

本站仅聚合各信源的摘要与原文链接，不转载全文，版权归原作者所有。
