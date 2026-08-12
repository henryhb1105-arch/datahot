# DataHot 安全边界

DataHot 是部署在 GitHub Pages 上的纯静态站。仓库内的主要攻击面不是服务端登录或数据库，而是外部 RSS/API 内容进入 HTML、JSON 和浏览器脚本后的内容注入风险。

## 已实施的仓库内防护

- 所有生成 HTML 都包含 CSP：脚本仅允许同源文件和构建时计算出的内联脚本 SHA-256；禁止内联事件处理器、`object`、`frame`、表单提交和 worker。
- 外部 URL 只接受无用户名/密码的 `http` 或 `https` 地址；危险协议和歧义 URL 会被丢弃并安全降级。
- 事件 ID 只能包含字母、数字、下划线和连字符，防止生成详情页时发生路径穿越。
- 新窗口外链统一使用 `noopener noreferrer`。
- JSON 写入 `<script>` 前会转义 HTML 解析敏感字符，避免 `</script>` 提前闭合。
- 页面使用 `strict-origin-when-cross-origin` Referrer Policy，并自动升级不安全资源请求。

## 托管层限制

HTML `<meta>` 形式的 CSP 不能设置 `frame-ancestors`，也不能替代 `X-Frame-Options`、`X-Content-Type-Options`、HSTS、COOP/COEP 等 HTTP 响应头。若后续需要点击劫持防护、WAF、速率限制、Bot 管理或更强 DDoS 策略，应在支持自定义响应头的 CDN/反向代理层配置；这不属于本静态仓库代码的能力范围。

## 验证

```bash
PYTHONPYCACHEPREFIX=/tmp/datahot-security-pycache python3 -m unittest tests.test_security_hardening
PYTHONDONTWRITEBYTECODE=1 python3 pipeline/build_site.py
```

安全测试会验证 CSP 哈希、危险 URL、脚本闭合注入、外链隔离和详情页路径穿越。
