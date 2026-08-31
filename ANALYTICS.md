# DataHot 匿名行为分析

## 默认状态与启用

分析客户端随站点发布，但默认 `ANALYTICS_ENABLED=false`，没有接收端时不会创建匿名 ID，也不会发送请求。启用需要同时设置 GitHub Actions Variables：

- `ANALYTICS_ENABLED=true`
- `ANALYTICS_ENDPOINT=https://...`（公开的 HTTPS 收集地址，不能包含用户名、密码或任何需要保密的 Token）
- `ANALYTICS_SITE_ID=datahot`（可选）

客户端只会在 `datahot.xiahongbin.com` 的生产页面发送事件；localhost、文件预览、测试、自动化浏览器（`navigator.webdriver=true`）和其他域名不会发送。自动化浏览器不会创建匿名 ID，也不会读取本机分析存储。`Global Privacy Control`、`Do Not Track` 或本机 opt-out 任一生效都会停止采集并删除随机 ID。

接收端应接受 `text/plain` 的 JSON batch：

```json
{"schema_version":1,"site_id":"datahot","events":[{"schema_version":1,"event_uuid":"...","name":"session_start"}]}
```

接收端必须丢弃请求 IP/Headers，不做地理解析或跨站拼接；按 `event_uuid` 幂等去重，建议原始事件最多保留 90 天。浏览器发送失败时静默丢弃，不重试到本地持久队列，也不阻断点击和导航。

## 事件、触发与去重

| 事件 | 触发 | 去重 |
|---|---|---|
| `session_start` | 生产会话首次启动 | 每个 sessionStorage 会话一次 |
| `page_view` | 正式域名页面打开 | 每次页面加载一次，立即发送 |
| `list_exposure` | 首页/主题列表卡片可见面积达到 40% | 每会话、页面、事件一次 |
| `detail_click` | 点击详情链接或整卡 | 同目标 750 ms 内一次 |
| `outbound_click` | 详情页点击原文、信源或正文外链 | 同事件 750 ms 内一次 |
| `favorite_toggle` | 添加/取消收藏 | 同事件和动作 750 ms 内一次 |
| `content_feedback` | 详情页选择有用/没用及可选原因 | 同事件、动作和原因 750 ms 内一次 |
| `search` | 搜索输入停止 600 ms | 同长度区间 3 秒内一次 |
| `filter` | 点击主题筛选 | 同筛选 750 ms 内一次 |
| `weekly_brief_click` | 点击标有 `data-analytics="weekly_brief"` 的周报入口 | 同入口 750 ms 内一次 |

字段白名单在 `pipeline/analytics_schema.py`。上下文只包含：页面类型、公开相对页面路径（无 query/hash）、事件 ID、分类、来源、随机 `session_id/device_id`、序号、宽度区间、来源类型区间，以及内容反馈的固定动作/原因枚举。设备 ID 由第一方 localStorage 随机生成并每 30 天轮换，不读取 Cookie 或浏览器指纹。

不会发送正文、摘要、完整搜索词、查询参数、外部 URL/referrer 全文、API Key、姓名、邮箱、UA、IP 或位置。搜索只发送长度区间 `1-3 / 4-8 / 9+` 与结果数量。

## 生产接收端与私有后台

- 接收端：`https://metrics.datahot.xiahongbin.com/v1/events`，仅接受来自 DataHot 正式域名的 `text/plain` 小批量请求。
- 私有后台：`https://admin.datahot.xiahongbin.com`，由 Cloudflare Access 登录保护，Worker 内还会再次核对唯一管理员身份。
- 存储：Cloudflare D1；`event_uuid` 为主键幂等去重，原始事件 90 天后由定时任务删除。
- 绕过保护：`workers.dev` 和预览地址均关闭；后台响应带 `noindex`、`no-store`、禁止嵌入和严格 CSP。
- 代码与运行手册：`ops/traffic-worker/`。仓库不会保存管理员邮箱、Access Token 或访问明细。

## 数据质量与指标

接收端导出的 NDJSON（每行可为单事件或 batch）先运行：

```bash
python3 pipeline/analytics_metrics.py export.ndjson
```

只使用 schema 合法且按 `event_uuid` 去重的事件：

- 详情点击率 = 有详情点击的 `(session_id,event_id)` 曝光对 / 唯一曝光对
- 外链点击率 = 有外链点击的详情点击对 / 唯一详情点击对
- 收藏率 = 添加收藏的曝光对 / 唯一曝光对
- 值得读比例 = 每个匿名设备对每篇文章的最后一次反馈中，`useful` 所占比例
- 反馈原因分布 = `solid/relevant/novel/source_discovery/irrelevant/shallow/marketing/duplicate/body_quality` 的计数
- 搜索/筛选使用率 = 使用该功能的会话 / `session_start` 会话
- 7 日回访率 = 有至少 7 天完整观察窗的首次设备中，在第 1–7 天再次出现的设备占比
- PV = 每个 Asia/Shanghai 自然日合法 `page_view` 数
- 可测 UV = 每个 Asia/Shanghai 自然日产生合法 `page_view` 的唯一匿名设备数
- 热门页面 = 公开相对页面路径上的 PV 与可测 UV；同一设备访问多个页面时会分别进入各页面 UV

报告同时给出合法率、解析失败、未知字段、缺字段和传输重复数。数据质量未达标前不得据此做产品决策。
