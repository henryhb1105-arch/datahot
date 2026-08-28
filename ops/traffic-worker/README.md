# DataHot 私有流量后台

本模块提供两个自有域名入口：

- `metrics.datahot.xiahongbin.com`：公开但严格受限的匿名事件接收端。
- `admin.datahot.xiahongbin.com`：仅管理员可进入的 PV/UV 运营后台。

## 安全与隐私边界

- 后台使用 Worker 原生密码登录，密码哈希与会话签名密钥均使用 Cloudflare 加密 secret，明文密码只保存在管理员 Mac 钥匙串中。
- 登录成功后仅签发 12 小时有效的 `HttpOnly`、`Secure`、`SameSite=Strict` Cookie；退出时立即清除。
- `workers.dev` 与预览 URL 必须关闭，避免绕过自有后台域名。
- 接收端只允许 `https://datahot.xiahongbin.com`，单批最多 20 条、32 KiB。
- 不读取或存储请求 IP、Header、UA、地理位置、Cookie、查询参数、完整 referrer、正文或完整搜索词。
- `event_uuid` 唯一约束负责传输去重，超过 90 天的原始事件每日清理。
- `.dev.vars` 只可用于本机，禁止提交；生产环境只设置 `ADMIN_PASSWORD_HASH` 与 `SESSION_SECRET`，禁止提交。

## 本地验证

```bash
npm install
npm run db:migrate:local
npx wrangler dev --local --port 8787 --var LOCAL_DEV:true --var MEASUREMENT_START_DATE:2026-08-10
npm test
```

本地 `LOCAL_DEV=true` 是显式的开发开关，生产配置不包含它。生产部署前 `npm run check:production` 会拒绝 D1 占位 ID，并确认公开备用地址已关闭。

## 生产启用清单

1. 创建 D1 `datahot-traffic`，将真实 UUID 写入 `wrangler.toml`。
2. 应用远端 migration。
3. 生成高强度管理员密码，将明文只存入 Mac 钥匙串；其 SHA-256 写入 Worker secret `ADMIN_PASSWORD_HASH`，并设置独立随机 `SESSION_SECRET`。两项均不得提交到仓库。
4. 部署 Worker，确认两个 Custom Domain 已激活且 `workers.dev`、preview URL 均关闭。
5. 分别验证：未登录跳转登录页、错误密码被拦截、管理员密码可打开并退出；采集域名不能打开后台。
7. 设置 GitHub Actions Variables：
   - `ANALYTICS_ENABLED=true`
   - `ANALYTICS_ENDPOINT=https://metrics.datahot.xiahongbin.com/v1/events`
   - `ANALYTICS_SITE_ID=datahot`
8. 发布 DataHot，验证正式页面产生第一条真实 `page_view`，再开始目标自然日计时。

所有线上变更仍遵循仓库 Issue、独立工作树和统一 Pages 发布规则。
