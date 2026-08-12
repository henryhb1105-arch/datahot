# DataHot 多对话协作规则

本文件适用于所有在本仓库中工作的 AI 对话和自动化任务。目标是让 GitHub Issue 成为跨对话的共享状态源，并确保 GitHub Pages 始终只有一个发布者。

## 1. Issue 是唯一任务账本

- 任何实现、提交、推送或发布开始前，先搜索现有 Issue；有重叠问题时复用原 Issue，不得重复创建。
- 在 Issue 留下工作声明后才能改代码。声明必须包含：`STATUS`、修改范围、预计文件、基线 SHA、是否影响发布、依赖项、`lease_until`。
- 统一状态为：`CLAIMED -> CODING -> READY_FOR_RELEASE -> PUBLISHING -> LIVE_VERIFIED`。
- 工作租约默认不超过 2 小时；继续工作时用新的状态评论续期。租约过期且没有新进展后，其他对话才可接管。
- 若另一个未过期租约覆盖同一路径或同一数据集，停止修改，在 Issue 协调；不得各自完成后相互覆盖。

推荐声明格式：

```text
STATUS: CLAIMED
scope: <本次只处理什么>
paths: <预计修改的路径>
base_sha: <origin/main SHA>
publish_required: yes|no
dependencies: <Issue 或 none>
lease_until: <ISO 8601 时间>
```

## 2. 每个 Issue 使用隔离工作树

- 从最新 `origin/main` 创建 `codex/issue-<number>-<slug>` 分支和独立 worktree。
- 不得在共享的脏工作树中开发、清理、reset 或提交其他任务产生的文件。
- 提交前重新 fetch，并 rebase/merge 最新 `origin/main`；随后重新生成站点并执行相关测试。
- `site/data/**`、`site/e/**` 等生成结果必须来自最新主线数据，不得用旧 worktree 的整份输出覆盖远端。
- 完成或交接时，在 Issue 记录分支、提交、测试结果和仍需处理的事项；不靠聊天上下文交接。

## 3. 发布采用单写者与远端租约

- 普通开发对话禁止直接推送 `gh-pages`。只有仓库统一 GitHub Actions 发布流程可以写入 Pages；break-glass 例外见下文。
- 请求发布前先检查 `datahot-publish` 是否已有 queued/in_progress 运行。若存在，更新 Issue 为等待该运行，不能再次 dispatch 或另起直接发布。
- 一个发布运行可以包含多个已合入 `main` 的 Issue；各对话将自己的 Issue 标记为 `READY_FOR_RELEASE`，由最新主线的一次构建统一发布。
- 发布失败时，由当前 `PUBLISHING` 的任务诊断并重跑原失败 job/run；其他对话不得同时重新发布。
- 发布前必须验证候选站点没有异常丢失近期事件、详情页或已知验收 URL。发现数据缩水时立即阻断，回到对应 Issue 修复。
- break-glass 直接发布必须先在 Issue 写明原因、目标 SHA、影响范围和回滚点；完成后仍要线上验证并记录证据。

## 4. 完成标准

- 代码完成不等于发布完成，Actions 成功也不等于页面已生效。
- 影响站点的任务只有在 commit 已合入、Pages 已发布、目标线上 URL 已验证后，才能写 `LIVE_VERIFIED` 并关闭 Issue。
- 仅修改协作规则或仓库文档时，至少验证文件已存在于远端 `main`，并在 Issue 留下 commit 证据。
- 若发布被其他运行、权限或数据回退保护阻断，明确记录 blocker 和唯一下一步，不得声称完成。
