# DataHot · 2026 数据与 AI 精选候选

审阅稿 · 2026 年 9 月 12 日 · [Issue #204](https://github.com/henryhb1105-arch/datahot/issues/204)

已整理 **20 条新增候选**：数据 Agent 7 条、AI 数据平台 4 条、语义层 4 条、AI 数据分析 3 条、AI 看板 / 数据产品 2 条。**其中 8 条有本次 X 采集证据，12 条由官方网页补充**。以下是选题卡片与推荐意见，不是原文翻译，也尚未导入站点。

本次查询覆盖 **2026-01-01 至 2026-09-12 12:50（北京时间）**。分月、分主题抽样，每片最多 10 条，共 30 次历史搜索，返回 **193 条资源 / 178 个不同帖子**。有 26 个查询仍有下一页，为控制成本没有继续翻页。因此它是年度范围内的精选回看，不能声称穷尽 2026 年所有相关 X 内容；9 月以后尚未发生的内容也不在范围内。

**费用：X 保守估算 $0.965，约 $0.97。** 按 [X 官方定价](https://docs.x.com/x-api/getting-started/pricing) $0.005/返回帖子计算；若平台当日去重正常生效，178 个不同帖子对应 $0.89。账单实扣未核验，报告按较高值预算。本次没有另行调用付费模型 API 或付费抓取服务；当前 Codex 会话用量不计入这个 X 费用数字，账户特定的 GitHub 费用和税费也未计入。没有购买订阅或充值。

原授权上限 $5；实际程序只预留最多 300 条 / $1.50。遇到预算账本冲突时在下一次 X 请求之前停止，恢复时跳过已完成查询，未重读付费结果。现在账本已关闭，临时采集触发器已删除，没有后续自动消费任务。

本次查询的 12 个账号条件：@bennstancil, @cube_dev, @databricks, @dbt_labs, @googlecloud, @hexanalytics, @metabase, @motherduck, @MSPowerBI, @simonw, @Snowflake, @thoughtspot。这是查询范围，不表示每个账号都有返回结果，也不能以某个查询无结果推断公司没有发布相关内容。后续须按信源分别评估命中率；泛 AI 账号的 `agent` 一词噪声偏高，应限定数据分析场景，Google 的 Genie 也存在与世界模型重名的误命中。

筛选依据：能否解决一个明确的产品或工程问题；是否有代码、架构、实验或具名实践支撑；是否可复用；是否带来新的认知；功能状态能否核对。互动量不作主要排序依据。A 级为本轮优先阅读的编辑判断，不是实验评分；厂商性能或成本数字均未独立复现。

下面先按方向浏览，再看完整推荐理由。每条的“原文要点”仅陈述来源内容，“推荐理由”是本次编辑判断。

| 编号 | 方向 | 内容 | 来源路径 |
|---|---|---|---|

| R01 | 数据 Agent | [用业务问题集把 Genie Space 从能演示做到可验收](#r01) | X + 官网 |
| R02 | 数据 Agent | [Cortex Agent 评测：既检查答案，也检查工具执行过程](#r02) | 官网补充 |
| R03 | 数据 Agent | [从 API 搭建 BigQuery 对话式数据 Agent](#r03) | 官网补充 |
| R04 | 数据 Agent | [Genie Agent Mode：围绕假设反复查询，解释业务变化](#r04) | X + 官网 |
| R05 | 数据 Agent | [把周报和流失分析沉淀成可版本管理的 Agent Skills](#r05) | 官网补充 |
| R06 | 数据 Agent | [多数据源 Agent 如何把问题路由到正确的数据集](#r06) | 官网补充 |
| R07 | 数据 Agent | [dbt MCP 的生产模式与大表查询成本陷阱](#r07) | 官网补充 |
| R08 | AI 数据平台 | [Cortex Agents 平台：版本、租户隔离、预算与工具治理](#r08) | X + 官网 |
| R09 | AI 数据平台 | [Genie Code：把长任务、数据资产与 ML 工程放进同一工作区](#r09) | X + 官网 |
| R10 | AI 数据平台 | [Knowledge Catalog：为 Agent 聚合、补全和检索业务上下文](#r10) | 官网补充 |
| R11 | AI 数据平台 | [Context Studio：观察真实问答，再测试并发布上下文修正](#r11) | 官网补充 |
| R12 | 语义层 | [Snowflake 内部实践：语义定义、物化加速与问题路由一起做](#r12) | 官网补充 |
| R13 | 语义层 | [语义上下文是否有效：同题、同模型的配对评测](#r13) | 官网补充 |
| R14 | 语义层 | [AI 可以重写语义模型，业务问答契约应该保留在哪里](#r14) | X + 官网 |
| R15 | 语义层 | [把 Snowflake 指标导入 ThoughtSpot，避免 AI 与看板各算一套](#r15) | X + 官网 |
| R16 | AI 数据分析 | [Looker Embedded：在业务应用里继续多轮分析并解释 SQL](#r16) | X + 官网 |
| R17 | AI 数据分析 | [IAS：从看板异常追到 dbt SQL，再用只读查询验证](#r17) | 官网补充 |
| R18 | AI 数据分析 | [Chat with App：利用当前看板的逻辑和筛选状态继续追问](#r18) | 官网补充 |
| R19 | AI 看板 / 数据产品 | [Generative Data Apps：可生成的界面建立在可检查的分析计算之上](#r19) | 官网补充 |
| R20 | AI 看板 / 数据产品 | [Dashboards as code：AI 生成看板后进入 Git 审阅流程](#r20) | X + 官网 |

<a id="r01"></a>

## R01 · 用业务问题集把 Genie Space 从能演示做到可验收

数据 Agent · Databricks · 2026-02-06 · 官方实操教程

**原文要点：** 以营销分析为例，逐步修正元数据、关联关系、CTR 等指标定义和业务规则，用 benchmark 检查每次修改。

**推荐理由：** 最适合先读：可以直接借鉴“业务问题—参考答案—失败归因—回归验证”的上线流程。

**状态与边界：** 文中的 13 题及准确率提升属于厂商示例，不能当作生产环境通用准确率。

[阅读原文](https://www.databricks.com/blog/how-build-production-ready-genie-spaces-and-build-trust-along-way)

[X 线索 1](https://x.com/i/status/2025960628834148810)（2026-02-23）

<a id="r02"></a>

## R02 · Cortex Agent 评测：既检查答案，也检查工具执行过程

数据 Agent · Snowflake · 2026-03-13 · 官方工程文章

**原文要点：** 把问题、参考答案与执行轨迹结合，检查答案正确性和逻辑一致性，并比较不同配置的成本与延迟。

**推荐理由：** 适合建立数据 Agent 的质量门槛，区分选错工具、执行出错和最终回答错误。

**状态与边界：** 文章发布时工具选择和工具执行评测为 private preview，不能将所有评测能力都写成 GA。

[阅读原文](https://www.snowflake.com/en/blog/engineering/cortex-agent-evaluations/)

发现方式：官网补充；不冒充 X 发现。

<a id="r03"></a>

## R03 · 从 API 搭建 BigQuery 对话式数据 Agent

数据 Agent · Google Cloud · 2026-02-19 · 官方代码教程

**原文要点：** 教程给出数据源与上下文配置、会话管理、流式回复，以及 SQL、结果表和 Vega-Lite 图表的处理方式。

**推荐理由：** 能回答“怎么把数据 Agent 接进自己的产品”，适合作为实现参考。

**状态与边界：** 这是示例实现；指定表引用不能替代 IAM 授权、查询额度和应用侧访问控制。

[阅读原文](https://cloud.google.com/blog/products/data-analytics/build-data-agents-with-conversational-analytics-api)

发现方式：官网补充；不冒充 X 发现。

<a id="r04"></a>

## R04 · Genie Agent Mode：围绕假设反复查询，解释业务变化

数据 Agent · Databricks · 2026-04-17 · 官方产品机制说明

**原文要点：** 对复杂问题先规划，再执行多次查询、检验假设并调整方向；答案附 SQL 和图表，并按问题复杂度分配推理。

**推荐理由：** 有助于设计从“查一个数”升级到“解释为什么”的分析流程及证据展示。

**状态与边界：** 发布时通过 Workspace Previews 启用；API 和非结构化文档分析当时仍是后续计划。相关性分解不等于因果证明。

[阅读原文](https://www.databricks.com/blog/introducing-genie-agent-mode)

[X 线索 1](https://x.com/i/status/2051001369331421464)（2026-05-03）

<a id="r05"></a>

## R05 · 把周报和流失分析沉淀成可版本管理的 Agent Skills

数据 Agent · Cube · 2026-06-02 · 官方实现与示例

**原文要点：** 将重复分析步骤写成项目内 Markdown skill，与数据模型一起评审、测试和部署，可通过按钮、命令或意图匹配调用。

**推荐理由：** 适合把固定业务分析做成可复用产品能力，减少每次重新组织长提示词。

**状态与边界：** 首版没有单 skill 数据隔离、外部动作、参数化输入和模型选择；当时定时执行仍在规划中。

[阅读原文](https://cube.dev/blog/introducing-cube-agent-skills)

发现方式：官网补充；不冒充 X 发现。

<a id="r06"></a>

## R06 · 多数据源 Agent 如何把问题路由到正确的数据集

数据 Agent · Microsoft Fabric · 2026-08（GA 月份） · 官方发布记录

**原文要点：** 官方更新列出数据源路由 GA：结合 schema、数据源描述、示例查询和路由规则，选择 lakehouse、warehouse、语义模型或 KQL 数据库。

**推荐理由：** 适合解决企业接入很多数据源后，Agent 选错表、选错引擎的问题。

**状态与边界：** 日期按官方更新表的月份记录；不推定具体上线日，也不将路由能力等同于任意跨源联邦查询。

[阅读原文](https://learn.microsoft.com/en-us/fabric/fundamentals/whats-new#data-science) · [补充来源 1](https://learn.microsoft.com/en-us/fabric/data-science/data-agent-configurations)

发现方式：官网补充；不冒充 X 发现。

<a id="r07"></a>

## R07 · dbt MCP 的生产模式与大表查询成本陷阱

数据 Agent · dbt Labs · 2026-05-01（6 月 16 日更新） · 官方生产经验

**原文要点：** 总结受治理指标问答、文档初稿、CI 测试和跨工具编排；明确指出大表全扫描容易引发超时和仓库费用，应预物化或设置查询限制。

**推荐理由：** 对“控制成本”尤其有用：MCP 接通后，还要限制扫描量、执行时间和可调用工具。

**状态与边界：** 发布日期由页面结构化元数据核对；复杂多表查询仍建议人工参与，文章不提供跨场景成本保证。

[阅读原文](https://www.getdbt.com/blog/5-dbt-mcp-server-patterns-that-work-in-production)

发现方式：官网补充；不冒充 X 发现。

<a id="r08"></a>

## R08 · Cortex Agents 平台：版本、租户隔离、预算与工具治理

AI 数据平台 · Snowflake · 2026-04-21 · 官方平台架构与发布说明

**原文要点：** 将 MCP 连接、可复用 skills、Python 沙箱与 Agent 版本管理、租户隔离、预算和评测放在同一运行平台。

**推荐理由：** 适合梳理 AI 数据平台的必要底座，尤其是多租户、执行环境和费用归属。

**状态与边界：** 发布稿含 generally available soon 和 public preview soon 等状态；应视为能力路线与分阶段发布，不能统称全部已上线。

[阅读原文](https://www.snowflake.com/en/blog/enterprise-ai-agent-platform/)

[X 线索 1](https://x.com/i/status/2046590966661030367)（2026-04-21）

<a id="r09"></a>

## R09 · Genie Code：把长任务、数据资产与 ML 工程放进同一工作区

AI 数据平台 · Databricks · 2026-06-17 · 官方平台更新

**原文要点：** 全页工作区支持多任务状态和结果审阅；Agent 可使用 MLflow 实验与血缘、服务端点信息，以及团队指令、skills 和连接器。

**推荐理由：** 产品价值在任务执行与审阅闭环，适合参考数据开发平台如何承载持续工作。

**状态与边界：** 定时任务在文章发布时仍为即将推出；客户效率数字不是独立测评，ZeroOps 是相关但独立的产品。

[阅读原文](https://www.databricks.com/blog/whats-new-genie-code-data-ai-summit-2026)

[X 线索 1](https://x.com/i/status/2067326444212981865)（2026-06-17）

<a id="r10"></a>

## R10 · Knowledge Catalog：为 Agent 聚合、补全和检索业务上下文

AI 数据平台 · Google Cloud · 2026-04-22 · 官方架构与发布说明

**原文要点：** 围绕上下文聚合、语义补全和检索组织目录，关联技术元数据、语义定义、验证查询和数据产品，并考虑源系统访问权限。

**推荐理由：** 适合定义 AI 数据平台的上下文基础设施，而不是再造一个表清单。

**状态与边界：** 元数据聚合、数据产品等与自动上下文整理、验证查询等功能的 GA/Preview 状态不同。

[阅读原文](https://cloud.google.com/blog/products/data-analytics/introducing-the-google-cloud-knowledge-catalog)

发现方式：官网补充；不冒充 X 发现。

<a id="r11"></a>

## R11 · Context Studio：观察真实问答，再测试并发布上下文修正

AI 数据平台 · Hex · 2026-01-28 · 官方版本记录

**原文要点：** 提供问题观察、Thread 检查、上下文认证与语义模型管理，以及部署前预览和版本控制。

**推荐理由：** 把数据团队从逐个补提示词，带到可观察、可修正、可发布的管理流程。

**状态与边界：** 发布记录限定 Team/Enterprise 的管理员和经理；敏感 Thread 有额外可见性限制。

[阅读原文](https://learn.hex.tech/changelog/2026-01-28)

发现方式：官网补充；不冒充 X 发现。

<a id="r12"></a>

## R12 · Snowflake 内部实践：语义定义、物化加速与问题路由一起做

语义层 · Snowflake · 2026-08-17 · 官方内部实践

**原文要点：** 用语义视图统一指标，通过代码评审与测试维护；用热门看板问题构造评测集，以物化减少慢查询，并持续整理路由规则。

**推荐理由：** 既讲指标口径，也讲响应速度和维护方式，适合长期保留。

**状态与边界：** 文章是 2026 年发布的经验总结，其中使用量例证来自 2025 年；不能把它们标成 2026 年新成绩。

[阅读原文](https://www.snowflake.com/en/blog/snowflake-internal-context-layer-for-ai-agents/)

发现方式：官网补充；不冒充 X 发现。

<a id="r13"></a>

## R13 · 语义上下文是否有效：同题、同模型的配对评测

语义层 · Cube · 2026-04-28 · 厂商公开配对实验

**原文要点：** 比较仅给 schema 与额外提供一份 4 KB 业务语义文档的结果，公开问题、参考 SQL、方法和代码，报告约 17–23 个百分点的提升。

**推荐理由：** 值得借鉴评测设计：先固定业务题与执行条件，再验证语义投入是否改善结果。

**状态与边界：** 厂商实验，100 题设计中统计检验 n=99；单零售数据集和单次生成条件不能代表所有生产环境，也不等于证明必须购买 Cube。

[阅读原文](https://cube.dev/blog/why-semantic-layers-make-llm-analytics-reliable-a-paired-benchmark-across-three-frontier-models) · [补充来源 1](https://github.com/cubedevinc/semantic-layer-benchmark) · [补充来源 2](https://arxiv.org/abs/2604.25149)

发现方式：官网补充；不冒充 X 发现。

<a id="r14"></a>

## R14 · AI 可以重写语义模型，业务问答契约应该保留在哪里

语义层 · MotherDuck · 2026-08-20 · 公司工程实践

**原文要点：** 团队用 Agent 生成并验证 Malloy 模型；在其测试中，Markdown + SQL 更省 token。文章主张用问题与答案对保留业务意图和验收条件。

**推荐理由：** 提供一个有价值的设计视角：把业务意图与生成代码分开维护，并为重新生成建立验收依据。

**状态与边界：** 属于特定 Malloy 实验和团队观点，不是“语义层不再需要”的普遍结论；仍保留模型抽象、指标统一更新与约束查询的价值。

[阅读原文](https://motherduck.com/blog/AI-writes-the-semantic-layer/)

[X 线索 1](https://x.com/i/status/2090803621046743188)（2026-08-21）

<a id="r15"></a>

## R15 · 把 Snowflake 指标导入 ThoughtSpot，避免 AI 与看板各算一套

语义层 · ThoughtSpot · 2026-05-13（X 分享日） · 官方操作说明

**原文要点：** 原生导入 Semantic Views 的指标、维度与关系，审阅后保存为 ThoughtSpot Model，供 Spotter 和看板使用；另有开源 skills 路径做双向转换。

**推荐理由：** 适合关注跨产品语义复用，以及同步、人工修改和刷新责任应该放在哪里。

**状态与边界：** 原生导入当时为 Early Access；原生双向同步和自动刷新仍在规划，不能与 skills 方案混写。日期暂按已获取的 X 分享记录。

[阅读原文](https://www.thoughtspot.com/blog/snowflake-semantic-views-thoughtspot-one-ai-context-layer)

[X 线索 1](https://x.com/i/status/2054583131886555189)（2026-05-13）

<a id="r16"></a>

## R16 · Looker Embedded：在业务应用里继续多轮分析并解释 SQL

AI 数据分析 · Google Cloud · 2026-04-06 · 官方产品接入说明

**原文要点：** 将基于 Looker 语义模型的对话分析通过 iframe、SDK 或 API 嵌入应用；支持多轮问题、多个 Explore、代码解释器与 SQL 解释。

**推荐理由：** 可以参考如何让分析进入业务现场，同时复用身份管理、指标定义和可解释的查询。

**状态与边界：** 此文发布的是嵌入场景能力，不应写成 Looker 对话分析首次上线；应用仍需正确配置用户身份与数据权限。

[阅读原文](https://cloud.google.com/blog/products/business-intelligence/looker-embedded-adds-conversational-analytics)

[X 线索 1](https://x.com/i/status/2045985794947498038)（2026-04-19）

<a id="r17"></a>

## R17 · IAS：从看板异常追到 dbt SQL，再用只读查询验证

AI 数据分析 · dbt Labs / IAS · 2026-07-07 · 具名客户架构案例

**原文要点：** 结合 Looker 入口、dbt 模型与血缘、Databricks 只读 SQL；Agent 调查指标逻辑，按业务用户或分析师输出不同细节。

**推荐理由：** 最贴近可落地的数据诊断产品：还给出了工具拆分、模型分档和多 Agent 路由的取舍。

**状态与边界：** 文章采用案例分享和示例问题；耗时改善为受访者描述。专用编译器列级血缘在文中属于后续计划。

[阅读原文](https://courses.getdbt.com/blog/mcp-dbt-databricks)

发现方式：官网补充；不冒充 X 发现。

<a id="r18"></a>

## R18 · Chat with App：利用当前看板的逻辑和筛选状态继续追问

AI 数据分析 · Hex · 2026-01-21 · 官方版本记录

**原文要点：** 对已发布应用提问，理解底层逻辑、定位单元格并调整筛选器和输入；同时引入只使用经数据团队认证上下文的模式。

**推荐理由：** 适合设计看板内分析助手：用户已有的上下文可以减少重复解释和错误选数。

**状态与边界：** 发布时要求 Explorer 及 Can explore 权限；新增分析逻辑当时仍在计划中，不能据此声称支持 Generative Apps。

[阅读原文](https://learn.hex.tech/changelog/2026-01-21)

发现方式：官网补充；不冒充 X 发现。

<a id="r19"></a>

## R19 · Generative Data Apps：可生成的界面建立在可检查的分析计算之上

AI 看板 / 数据产品 · Hex · 2026-05-12 · 官方发布记录与文档

**原文要点：** Agent 生成 JavaScript 界面与图表，数据查询和变换仍由 Hex 项目承载，并沿用上下文、发布和数据刷新机制。

**推荐理由：** 适合搭建 AI 数据产品：生成界面、分析计算和发布权限需要各有明确责任。

**状态与边界：** 发布时及当前文档均标 Beta；当前仍有限制，包括 PDF、saved views 和 Chat with App，不能当成完整替代经典应用。

[阅读原文](https://learn.hex.tech/changelog/2026-05-12) · [补充来源 1](https://learn.hex.tech/docs/share-insights/apps/generative-apps)

发现方式：官网补充；不冒充 X 发现。

<a id="r20"></a>

## R20 · Dashboards as code：AI 生成看板后进入 Git 审阅流程

AI 看板 / 数据产品 · Metabase · 2026-05-20 · 官方版本记录

**原文要点：** AI 工具读取 Metabase 元数据、编写查询并生成 dashboard YAML，提交 Git 待审阅；版本同时加入 AI 权限、token 限额与使用量分析。

**推荐理由：** 适合希望可回滚、可评审并控制 AI 费用的数据产品团队。

**状态与边界：** Dashboards as code 需要 Remote Sync；权限、token 限额等治理功能的发布稿链接指向 Pro。生成文件仍需验证指标口径。

[阅读原文](https://www.metabase.com/releases/metabase-61)

[X 线索 1](https://x.com/i/status/2059324685985464550)（2026-05-26）


## 去重与淘汰记录

以本次基线的 414 条站内事件及其中 19 条常驻精选为去重参照，移除跟踪参数、统一域名与路径后，20 条候选均未命中已有原文链接；这不意味着同一产品从未报道过。当前站点持续更新，正式入库前还应针对最新主线再查一次。

| 淘汰内容 | 原因 |
|---|---|
| ThoughtSpot AgentQL | 已收录，事件 5422d3495b2d |
| ThoughtSpot ChartSpec | 已收录，事件 ecaefd096734 |
| Google Data Agent Kit 跨源分析教程 | 已收录，事件 b37fd3d1c6d4 |
| OpenAI 内部数据 Agent、a16z 数据 Agent 上下文、Databricks 质量与成本评测 | 已有同源内容，不重复计为新候选 |
| Snowflake 同一天发布的三条相同平台消息 | 合并到 R08，作为一条选题 |
| 峰会报名、获奖、融资、模型接入、节日营销 | 缺少本次关注的可复用产品或工程内容 |
| 泛 coding agent、浏览器生成、Google 世界模型 Genie | 与数据 Agent 场景不符 |

## 在 DataHot 上怎么展示

建议沿用现有内容卡片，增加或映射这五类主题标签，不另建 X 时间流。卡片展示中文标题、公司、原文日期和一句具体推荐理由；X 只是发现来源，放在来源区，正文仍以原文章节、代码和图表为中心。跨平台的同一产品发布只保留一个事件。

详情页保留原文入口；需要中文时沿原文结构忠实翻译。编辑判断放在“推荐理由”，不要混入原文。若拿不到全文，显示简短摘介和原文链接，不用 AI 扩写冒充原文。本文卡片的要点只供选题审阅。

历史精选进入长期主题库，以真实发布时间显示，不伪装成今天的新闻。官网与 X 链接都作为来源保留；不要在首屏加载 X 嵌入脚本或实时调用 X API，避免增加页面加载负担和阅读依赖。

## 下一轮成本建议（尚未启用）

每周先查官方 changelog、博客和可用 RSS，再用 X 补漏；通常取 50–100 条新帖子，不做固定数量的发布任务。建议 X 月度总读取上限 500 条，对应公开单价下最多 $2.50。查询按账号和明确主题拆分，逐次预留预算，保存 since_id / 时间边界，失败不盲目重试；同一 URL 和产品事件跨来源合并。

193 条返回资源最后支撑了 8 条入选内容，说明 X 有补充价值；同时，按相关性取前 10 条会偏向热门发布，不能据此评价全部账号质量。本轮不需要扩到 800 条，也不建议为找齐更多帖子继续花钱。

此次只完成采集验证与候选审阅稿，没有启动每周自动任务，没有发布这 20 条内容。正式入库要按最新主线重新去重，并完成原文、图片、功能状态及站点发布验证。
