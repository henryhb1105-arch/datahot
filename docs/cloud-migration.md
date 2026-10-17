# DataHot 独立云端每日优化

任务账本：[Issue #243](https://github.com/henryhb1105-arch/datahot/issues/243)。
执行前先读远端最新 `AGENTS.md` 和本 Issue 的最新评论。本文是持久任务说明，不表示调度已启用。

## 运行目标和授权

每天北京时间（Asia/Shanghai）09:00，一天一次，独立完成观察、选题、实现、必要测试、合入、统一发布和线上验收。Mac mini 关机不影响运行；禁止依赖本机目录、浏览器登录、个人 skills、共享上下文或本机 heartbeat。Henry 已授权常规提交、合入、发布和验收，不停在草稿 PR 或 READY_FOR_RELEASE。账号缺失权限由 Henry 安全授权；不购买服务、扩大权限、对外营销或恢复暂停分发任务。

产品目标：让数据与 AI 从业者以更低的时间和认知成本发现可信的重要变化，理解为什么值得关注，找到可用于实际工作的内容。每天从真实线上体验、最新主线、Issue/PR/发布证据中列少量候选，按价值、证据、成本风险选择一项。记录用户任务、障碍、最小有效改变和验收依据；没有明确收益时只测量调查，不为提交制造功能。优先接续有价值的未完任务。

## 每次运行

1. 按 Asia/Shanghai 当天日期检查 Issue 和发布，避免同日重复。搜索重叠 Issue；先在唯一任务 Issue 声明 STATUS、scope、paths、base_sha、publish_required、dependencies、lease_until（不超过 2 小时，持续工作及时续期）。协调未过期冲突租约。
2. 从最新 origin/main 创建 `codex/issue-<number>-<slug>` 和独立 worktree。不清理别人文件；提交前 fetch 同步主线，重建并重测。
3. 简单克制、移动优先兼顾桌面。筛选按钮轻量、时间轴风格协调、底部导航反馈明确、关注切换快、推荐理由默认展开。详情保留清洗后的原文和图表，只在需要时忠实翻译，不以 AI 摘要替代已有原文。性能改动记录可比前后证据，验收排除流量统计。
4. 执行 Python/Node 回归、构建、链接和数据完整性检查。site/data、site/e 只能从最新主线生成；用最新线上/主线基线比较，允许规则明确的过期下架，不使用固定历史数量作为目标。
5. 合入后标记 READY_FOR_RELEASE。检查所有 Actions 的 `datahot-publish` 使用者（deploy.yml 及调用它的 update/tts），已有 queued/in_progress 就协调等待，不重复 dispatch。只有统一发布工作流可以写 Pages。发布失败诊断并重跑原失败 job/run，不绕过质量检查。
6. 标记 PUBLISHING，核对 `data/release.json` 的 source SHA、run ID、数据和资源字节版本；运行手机与桌面真实交互测试、审阅截图。只在合入、正式发布、线上版本及功能都通过后 LIVE_VERIFIED 并关闭 Issue。记录日期、证据、选择理由、修改、测试、PR/commit、运行链接、截图和结果。

## 可重建的浏览器验收

依赖：Python 3.11+、Node 22+、Git、Linux Chromium。无需 Mac 路径或用户浏览器。

```sh
python -m pip install --require-hashes -r requirements.txt
npm ci --prefix ops/cloud-acceptance --ignore-scripts
npm exec --prefix ops/cloud-acceptance -- playwright install --with-deps chromium
python -m unittest discover -s tests
node --test tests/*.test.js
python pipeline/build_site.py
node tests/cloud-acceptance.cjs
```

构建命令内置完整链接检查，无需再次重复运行。

已有系统 Chromium 时可设置 `CHROME_PATH=/usr/bin/chromium`。脚本在 local 模式自行启动临时 HTTP 服务。结果默认写 `artifacts/cloud-acceptance`，可用 `DATAHOT_ARTIFACT_DIR` 指定目录；不要提交生成站点或验收临时文件。

生产验收必须指定已知的预期发布 SHA：

```sh
DATAHOT_TEST_BASE=https://datahot.xiahongbin.com/ \
DATAHOT_EXPECTED_SHA=<40位已发布source_sha> \
node tests/cloud-acceptance.cjs
```

脚本覆盖全部当前资讯详情、重复 ID、manifest 数量、资源 SHA256 版本、390/1440px 页面溢出、搜索换序/全半角、空结果恢复、默认展开推荐理由、详情跳转、关注持久化、浏览器异常和失效资源。使用 DNT、GPC、本地 opt-out，并阻断统计请求；不得将验收算作真实用户。前后检查发布版本一致，避免跨版本误验收。

`.github/workflows/cloud-acceptance.yml` 使用 GitHub 托管 Ubuntu runner，支持 PR 检查和手动 local/production 验收，上传截图及 JSON 结果。**PASS 仅证明自动检查通过；截图必须由执行智能体实际审阅后才能记录视觉验收通过。** 这个工作流不发布、不调用模型、不承担每日自主选题。

## 调度迁移门槛

在 Issue #243 记录以下证据后才启用每日新调度：

- 调度服务与执行环境 ID，以及仓库绑定和模型授权的真实成功调用；仅存在云端聊天或普通提醒不算。
- 一次独立云端端到端试运行：选题去重、测试、合入、统一发布、线上交互与截图审阅。2026-10-17 的产品优化已由 #241/#242 完成，迁移试运行不重复产品修改。
- 调度 ID、Asia/Shanghai 09:00、下次执行时间；记录服务可能的延迟语义，不能宣称 cron 保证精确启动。
- 新任务真正验证后，停用旧本地 `id=datahot`（“DataHot 每日第一性原理优化”，原会话 `01a0f17a-a74f-75f1-8de5-866382b9d15b`）。无本地任务管理权时，由 Henry 在原会话停用并确认；不得假称已停。

当前能力与阻塞随 Issue 更新。不要将 ChatGPT 普通 automations 自动视为 Codex Cloud 环境调度，不在未验证时建立重复每日任务。若采用 GitHub Actions 调度 + Codex 非交互执行的备选方案，必须先确认模型凭据可用、预算授权、仓库写/PR/Actions 权限、故障重试与 Issue 去重；不得复制本会话临时凭据或将 Mac runner 伪装为云端。
