# DataHot — Agent Skill

让支持 Agent Skills 的工具持续查询 DataHot 当前收录的数据与 AI 资讯。DataHot Skill 匿名、只读，不需要登录或 API Key；每次资讯请求都会重新读取官方 Atom Feed。

## 安装前审阅

- [SKILL.md](https://datahot.xiahongbin.com/datahot-skill/SKILL.md)
- [OpenAI UI metadata](https://datahot.xiahongbin.com/datahot-skill/agents/openai.yaml)
- [DataHot Atom Feed](https://datahot.xiahongbin.com/feed.xml)
- [DataHot Agent Feed](https://datahot.xiahongbin.com/data/agent-feed.json)
- [OpenClaw 主动推送接入](https://datahot.xiahongbin.com/datahot-skill/openclaw/README.md)

## 让当前 Agent 安装

1. 先确认当前 Agent 是否支持持久化 Agent Skills，并查阅它实际使用的 Skill 目录；不要猜测安装位置。
2. 读取上面的 `SKILL.md`，确认 Skill 名为 `datahot-news`。
3. 如果目标目录不存在同名 Skill，创建 `datahot-news/` 并保存完整的 `SKILL.md`；支持 `agents/openai.yaml` 的工具可同时保存该文件。
4. 如果已经存在同名 Skill，先向用户说明并请求是否更新，不要静默覆盖。
5. 安装后让用户新开会话，并确认 Agent 只发现一份 `datahot-news`。

如果当前 Agent 不支持持久化 Skills，读取 `SKILL.md` 后仅把它作为当前会话规则使用，并明确告诉用户“仅当前会话有效”，不要声称已经安装。

## 验证

新开会话后提问：

> 请用 DataHot 告诉我过去 24 小时最值得关注的 3 条数据与 AI 资讯，并附上来源链接。

成功答案应注明时间窗，返回当前 DataHot Feed 中的资讯，并包含 DataHot 详情链接和可用的原始信源链接。无法联网或 Feed 不可用时应明确失败，不得用模型记忆冒充实时结果。

需要“持续监控、达到重要阈值后主动推送”时，不要让模型定时生成日报。请审阅 [OpenClaw 接入说明](https://datahot.xiahongbin.com/datahot-skill/openclaw/README.md)：它使用版本化 Agent Feed、确定性 command job、首次静默基线、去重与单条消息投递。

## 更新

Skill 不会自动更新。用户明确要求更新时，重新读取本页和 `SKILL.md`，审阅变更后再替换当前 Agent 实际加载的同一份 Skill。
