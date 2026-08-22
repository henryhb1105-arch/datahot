# DataHot 重要资讯单条推送 · OpenClaw

这个适配器每 15 分钟条件请求 DataHot 的静态 Agent Feed。它不调用模型：只有新事件第一次达到 DataHot 的重要资讯规则时，才通过 OpenClaw 发出一条消息；每条消息只包含一个事件和一个可点击的 DataHot 详情链接。

DataHot 目前通常在北京时间 02:17、08:17、14:17、20:17 启动采集和构建。15 分钟轮询表示“新版本上线后通常 15 分钟内发现”，不会把上游采集本身变成实时流。

## 数据与推送契约

- Feed：`https://datahot.xiahongbin.com/data/agent-feed.json`
- 详情：`https://datahot.xiahongbin.com/e/<event_id>.html`
- 默认重要规则：编辑置顶；或重要度不低于 80；或重要度不低于 75 且至少两个独立信源
- 新鲜度：收录后 48 小时
- 限流：每轮最多 3 条、北京时间每天最多 5 条
- 首次运行：只保存当前事件作为基线，不补发历史
- 条件请求：保存 ETag，服务端未变化时不解析也不发送

DataHot 是静态站，因此这里使用条件轮询，不要求用户暴露 webhook，也不需要 DataHot API Key。

## 安装

以下路径只是推荐值。安装 Agent 应先确认当前 OpenClaw 实际使用的 workspace 和命令入口，不得猜测或覆盖同名文件。

1. 保存脚本：

   `https://datahot.xiahongbin.com/datahot-skill/openclaw/datahot_push.py`

2. 复制配置模板：

   `https://datahot.xiahongbin.com/datahot-skill/openclaw/config.example.json`

   将它保存为 `~/.openclaw/workspace/config/datahot-push.json`，填写当前通道的 `target`；多账户时同时填写 `account`。`openclaw_command` 必须是 OpenClaw CLI 或已验证的本地包装器的绝对路径。配置含私有路由标识，权限应设为 `0600`，不得提交到仓库、聊天或日志。

3. 手动运行一次脚本。成功时标准输出为 `NO_REPLY`，标准错误会显示 `baseline=True`；这一步不会补发当前 Feed 的历史事件。

4. 使用 OpenClaw 的确定性 command job 每 15 分钟执行一次。示例：

```bash
openclaw cron add \
  --name "DataHot 重要资讯单条推送" \
  --declaration-key datahot-important-push-v1 \
  --cron "*/15 * * * *" \
  --tz Asia/Shanghai \
  --exact \
  --command-argv '["python3","/ABSOLUTE/PATH/datahot_push.py"]' \
  --no-deliver \
  --timeout-seconds 90
```

脚本直接调用 `openclaw message send`，所以 cron 自身必须使用 `--no-deliver`，防止把命令输出再投递一次。它不需要 Agent turn、模型或聊天上下文。

## 微信消息形态

微信插件按纯文本发送；不要把详情链接包装成 Markdown 按钮。裸 HTTPS URL 才能稳定点击：

```text
🔥 DataHot｜重要度 82

标题

为什么值得看：……

https://datahot.xiahongbin.com/e/<event_id>.html
```

一次 OpenClaw 发送调用只承载一个事件。即使同轮命中多条，也逐条发送，不合并成日报或多条卡片。

## 状态与故障处理

默认状态文件是 `~/.openclaw/workspace/.state/datahot-push.json`。发送前，事件会先原子记录为 `attempted`；只有 OpenClaw 进程以 0 退出才记录为 `sent`。超时、非零退出或插件输出不明确时会记录为 `failed`，后续轮次不会自动重试，以免同一条微信重复出现。

`failed` 事件应先在目标聊天和投递记录中人工确认。确认没有送达后，使用 `openclaw message send` 手动发送同一条消息；不要通过删除整个状态文件重跑，因为这会重新建立基线并掩盖故障。可用 `--dry-run` 查看当前会选中的消息而不写状态、不发送。

## 其他 Agent / 通道

脚本不依赖微信业务逻辑。只要目标 OpenClaw 通道支持 `message send`，就可以在私有配置里替换 `channel`、`target` 和可选 `account`。DataHot Feed 中的 `push.recommended` 是统一服务端判断，客户端只负责新鲜度、去重、限流和投递。
