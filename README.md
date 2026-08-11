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
- `pipeline/config.json` — 本地 LLM 密钥（**已 gitignore，不要提交**）
- `.github/workflows/update.yml` — 每 6 小时定时运行 + 自动发布 Pages

## 本地运行

```bash
# 1. 配置 LLM（编辑 pipeline/config.json 填入 DeepSeek Key）
cp pipeline/.env.example pipeline/config.json

# 2. 更新数据并生成站点
python3 pipeline/run_update.py && python3 pipeline/build_site.py

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

达到上限时会在 API 请求前停止新调用，不影响已采集原文的保留和静态站点构建。

## 内容声明

本站仅聚合各信源的摘要与原文链接，不转载全文，版权归原作者所有。
