"""Render the reviewed, original-source candidate list. No network or model calls."""
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode

ROOT = Path(__file__).parent
ROWS = []

def add(category, vendor, date, title, url, facts, reason, boundary, evidence, priority='A', extra=None):
    ROWS.append(dict(id=f'R{len(ROWS)+1:02}', category=category, vendor=vendor,
                     source_date=date, title=title, source_url=url, facts=facts,
                     recommendation=reason, boundary=boundary, evidence=evidence,
                     priority=priority, extra_sources=extra or []))

add('数据 Agent','Databricks','2026-02-06',
    '用业务问题集把 Genie Space 从能演示做到可验收',
    'https://www.databricks.com/blog/how-build-production-ready-genie-spaces-and-build-trust-along-way',
    '以营销分析为例，逐步修正元数据、关联关系、CTR 等指标定义和业务规则，用 benchmark 检查每次修改。',
    '最适合先读：可以直接借鉴“业务问题—参考答案—失败归因—回归验证”的上线流程。',
    '文中的 13 题及准确率提升属于厂商示例，不能当作生产环境通用准确率。', '官方实操教程')
add('数据 Agent','Snowflake','2026-03-13',
    'Cortex Agent 评测：既检查答案，也检查工具执行过程',
    'https://www.snowflake.com/en/blog/engineering/cortex-agent-evaluations/',
    '把问题、参考答案与执行轨迹结合，检查答案正确性和逻辑一致性，并比较不同配置的成本与延迟。',
    '适合建立数据 Agent 的质量门槛，区分选错工具、执行出错和最终回答错误。',
    '文章发布时工具选择和工具执行评测为 private preview，不能将所有评测能力都写成 GA。', '官方工程文章')
add('数据 Agent','Google Cloud','2026-02-19',
    '从 API 搭建 BigQuery 对话式数据 Agent',
    'https://cloud.google.com/blog/products/data-analytics/build-data-agents-with-conversational-analytics-api',
    '教程给出数据源与上下文配置、会话管理、流式回复，以及 SQL、结果表和 Vega-Lite 图表的处理方式。',
    '能回答“怎么把数据 Agent 接进自己的产品”，适合作为实现参考。',
    '这是示例实现；指定表引用不能替代 IAM 授权、查询额度和应用侧访问控制。', '官方代码教程')
add('数据 Agent','Databricks','2026-04-17',
    'Genie Agent Mode：围绕假设反复查询，解释业务变化',
    'https://www.databricks.com/blog/introducing-genie-agent-mode',
    '对复杂问题先规划，再执行多次查询、检验假设并调整方向；答案附 SQL 和图表，并按问题复杂度分配推理。',
    '有助于设计从“查一个数”升级到“解释为什么”的分析流程及证据展示。',
    '发布时通过 Workspace Previews 启用；API 和非结构化文档分析当时仍是后续计划。相关性分解不等于因果证明。', '官方产品机制说明')
add('数据 Agent','Cube','2026-06-02',
    '把周报和流失分析沉淀成可版本管理的 Agent Skills',
    'https://cube.dev/blog/introducing-cube-agent-skills',
    '将重复分析步骤写成项目内 Markdown skill，与数据模型一起评审、测试和部署，可通过按钮、命令或意图匹配调用。',
    '适合把固定业务分析做成可复用产品能力，减少每次重新组织长提示词。',
    '首版没有单 skill 数据隔离、外部动作、参数化输入和模型选择；当时定时执行仍在规划中。', '官方实现与示例')
add('数据 Agent','Microsoft Fabric','2026-08（GA 月份）',
    '多数据源 Agent 如何把问题路由到正确的数据集',
    'https://learn.microsoft.com/en-us/fabric/fundamentals/whats-new#data-science',
    '官方更新列出数据源路由 GA：结合 schema、数据源描述、示例查询和路由规则，选择 lakehouse、warehouse、语义模型或 KQL 数据库。',
    '适合解决企业接入很多数据源后，Agent 选错表、选错引擎的问题。',
    '日期按官方更新表的月份记录；不推定具体上线日，也不将路由能力等同于任意跨源联邦查询。', '官方发布记录', extra=['https://learn.microsoft.com/en-us/fabric/data-science/data-agent-configurations'])
add('数据 Agent','dbt Labs','2026-05-01（6 月 16 日更新）',
    'dbt MCP 的生产模式与大表查询成本陷阱',
    'https://www.getdbt.com/blog/5-dbt-mcp-server-patterns-that-work-in-production',
    '总结受治理指标问答、文档初稿、CI 测试和跨工具编排；明确指出大表全扫描容易引发超时和仓库费用，应预物化或设置查询限制。',
    '对“控制成本”尤其有用：MCP 接通后，还要限制扫描量、执行时间和可调用工具。',
    '发布日期由页面结构化元数据核对；复杂多表查询仍建议人工参与，文章不提供跨场景成本保证。', '官方生产经验')

add('AI 数据平台','Snowflake','2026-04-21',
    'Cortex Agents 平台：版本、租户隔离、预算与工具治理',
    'https://www.snowflake.com/en/blog/enterprise-ai-agent-platform/',
    '将 MCP 连接、可复用 skills、Python 沙箱与 Agent 版本管理、租户隔离、预算和评测放在同一运行平台。',
    '适合梳理 AI 数据平台的必要底座，尤其是多租户、执行环境和费用归属。',
    '发布稿含 generally available soon 和 public preview soon 等状态；应视为能力路线与分阶段发布，不能统称全部已上线。', '官方平台架构与发布说明')
add('AI 数据平台','Databricks','2026-06-17',
    'Genie Code：把长任务、数据资产与 ML 工程放进同一工作区',
    'https://www.databricks.com/blog/whats-new-genie-code-data-ai-summit-2026',
    '全页工作区支持多任务状态和结果审阅；Agent 可使用 MLflow 实验与血缘、服务端点信息，以及团队指令、skills 和连接器。',
    '产品价值在任务执行与审阅闭环，适合参考数据开发平台如何承载持续工作。',
    '定时任务在文章发布时仍为即将推出；客户效率数字不是独立测评，ZeroOps 是相关但独立的产品。', '官方平台更新')
add('AI 数据平台','Google Cloud','2026-04-22',
    'Knowledge Catalog：为 Agent 聚合、补全和检索业务上下文',
    'https://cloud.google.com/blog/products/data-analytics/introducing-the-google-cloud-knowledge-catalog',
    '围绕上下文聚合、语义补全和检索组织目录，关联技术元数据、语义定义、验证查询和数据产品，并考虑源系统访问权限。',
    '适合定义 AI 数据平台的上下文基础设施，而不是再造一个表清单。',
    '元数据聚合、数据产品等与自动上下文整理、验证查询等功能的 GA/Preview 状态不同。', '官方架构与发布说明')
add('AI 数据平台','Hex','2026-01-28',
    'Context Studio：观察真实问答，再测试并发布上下文修正',
    'https://learn.hex.tech/changelog/2026-01-28',
    '提供问题观察、Thread 检查、上下文认证与语义模型管理，以及部署前预览和版本控制。',
    '把数据团队从逐个补提示词，带到可观察、可修正、可发布的管理流程。',
    '发布记录限定 Team/Enterprise 的管理员和经理；敏感 Thread 有额外可见性限制。', '官方版本记录')

add('语义层','Snowflake','2026-08-17',
    'Snowflake 内部实践：语义定义、物化加速与问题路由一起做',
    'https://www.snowflake.com/en/blog/snowflake-internal-context-layer-for-ai-agents/',
    '用语义视图统一指标，通过代码评审与测试维护；用热门看板问题构造评测集，以物化减少慢查询，并持续整理路由规则。',
    '既讲指标口径，也讲响应速度和维护方式，适合长期保留。',
    '文章是 2026 年发布的经验总结，其中使用量例证来自 2025 年；不能把它们标成 2026 年新成绩。', '官方内部实践')
add('语义层','Cube','2026-04-28',
    '语义上下文是否有效：同题、同模型的配对评测',
    'https://cube.dev/blog/why-semantic-layers-make-llm-analytics-reliable-a-paired-benchmark-across-three-frontier-models',
    '比较仅给 schema 与额外提供一份 4 KB 业务语义文档的结果，公开问题、参考 SQL、方法和代码，报告约 17–23 个百分点的提升。',
    '值得借鉴评测设计：先固定业务题与执行条件，再验证语义投入是否改善结果。',
    '厂商实验，100 题设计中统计检验 n=99；单零售数据集和单次生成条件不能代表所有生产环境，也不等于证明必须购买 Cube。', '厂商公开配对实验', extra=['https://github.com/cubedevinc/semantic-layer-benchmark','https://arxiv.org/abs/2604.25149'])
add('语义层','MotherDuck','2026-08-20',
    'AI 可以重写语义模型，业务问答契约应该保留在哪里',
    'https://motherduck.com/blog/AI-writes-the-semantic-layer/',
    '团队用 Agent 生成并验证 Malloy 模型；在其测试中，Markdown + SQL 更省 token。文章主张用问题与答案对保留业务意图和验收条件。',
    '提供一个有价值的设计视角：把业务意图与生成代码分开维护，并为重新生成建立验收依据。',
    '属于特定 Malloy 实验和团队观点，不是“语义层不再需要”的普遍结论；仍保留模型抽象、指标统一更新与约束查询的价值。', '公司工程实践')
add('语义层','ThoughtSpot','2026-05-13（X 分享日）',
    '把 Snowflake 指标导入 ThoughtSpot，避免 AI 与看板各算一套',
    'https://www.thoughtspot.com/blog/snowflake-semantic-views-thoughtspot-one-ai-context-layer',
    '原生导入 Semantic Views 的指标、维度与关系，审阅后保存为 ThoughtSpot Model，供 Spotter 和看板使用；另有开源 skills 路径做双向转换。',
    '适合关注跨产品语义复用，以及同步、人工修改和刷新责任应该放在哪里。',
    '原生导入当时为 Early Access；原生双向同步和自动刷新仍在规划，不能与 skills 方案混写。日期暂按已获取的 X 分享记录。', '官方操作说明')

add('AI 数据分析','Google Cloud','2026-04-06',
    'Looker Embedded：在业务应用里继续多轮分析并解释 SQL',
    'https://cloud.google.com/blog/products/business-intelligence/looker-embedded-adds-conversational-analytics',
    '将基于 Looker 语义模型的对话分析通过 iframe、SDK 或 API 嵌入应用；支持多轮问题、多个 Explore、代码解释器与 SQL 解释。',
    '可以参考如何让分析进入业务现场，同时复用身份管理、指标定义和可解释的查询。',
    '此文发布的是嵌入场景能力，不应写成 Looker 对话分析首次上线；应用仍需正确配置用户身份与数据权限。', '官方产品接入说明')
add('AI 数据分析','dbt Labs / IAS','2026-07-07',
    'IAS：从看板异常追到 dbt SQL，再用只读查询验证',
    'https://courses.getdbt.com/blog/mcp-dbt-databricks',
    '结合 Looker 入口、dbt 模型与血缘、Databricks 只读 SQL；Agent 调查指标逻辑，按业务用户或分析师输出不同细节。',
    '最贴近可落地的数据诊断产品：还给出了工具拆分、模型分档和多 Agent 路由的取舍。',
    '文章采用案例分享和示例问题；耗时改善为受访者描述。专用编译器列级血缘在文中属于后续计划。', '具名客户架构案例')
add('AI 数据分析','Hex','2026-01-21',
    'Chat with App：利用当前看板的逻辑和筛选状态继续追问',
    'https://learn.hex.tech/changelog/2026-01-21',
    '对已发布应用提问，理解底层逻辑、定位单元格并调整筛选器和输入；同时引入只使用经数据团队认证上下文的模式。',
    '适合设计看板内分析助手：用户已有的上下文可以减少重复解释和错误选数。',
    '发布时要求 Explorer 及 Can explore 权限；新增分析逻辑当时仍在计划中，不能据此声称支持 Generative Apps。', '官方版本记录')

add('AI 看板 / 数据产品','Hex','2026-05-12',
    'Generative Data Apps：可生成的界面建立在可检查的分析计算之上',
    'https://learn.hex.tech/changelog/2026-05-12',
    'Agent 生成 JavaScript 界面与图表，数据查询和变换仍由 Hex 项目承载，并沿用上下文、发布和数据刷新机制。',
    '适合搭建 AI 数据产品：生成界面、分析计算和发布权限需要各有明确责任。',
    '发布时及当前文档均标 Beta；当前仍有限制，包括 PDF、saved views 和 Chat with App，不能当成完整替代经典应用。', '官方发布记录与文档', extra=['https://learn.hex.tech/docs/share-insights/apps/generative-apps'])
add('AI 看板 / 数据产品','Metabase','2026-05-20',
    'Dashboards as code：AI 生成看板后进入 Git 审阅流程',
    'https://www.metabase.com/releases/metabase-61',
    'AI 工具读取 Metabase 元数据、编写查询并生成 dashboard YAML，提交 Git 待审阅；版本同时加入 AI 权限、token 限额与使用量分析。',
    '适合希望可回滚、可评审并控制 AI 费用的数据产品团队。',
    'Dashboards as code 需要 Remote Sync；权限、token 限额等治理功能的发布稿链接指向 Pro。生成文件仍需验证指标口径。', '官方版本记录')

def canonical(url):
    p=urlsplit(url)
    host=p.netloc.lower().removeprefix('www.').replace('courses.getdbt.com','getdbt.com')
    keep=[(k,v) for k,v in parse_qsl(p.query) if k in ('v',)]
    return host+p.path.rstrip('/').lower()+('?' + urlencode(keep) if keep else '')

def main():
    posts=json.loads(Path('/tmp/datahot-x-review-2026/posts.json').read_text())
    existing=json.loads((ROOT/'existing-index.json').read_text())
    for row in ROWS:
        key=canonical(row['source_url'])
        row['x_posts']=[{'url':'https://x.com/i/status/'+p['id'],'date':p['date'][:10]}
                        for p in posts if any(canonical(u)==key for u in p['urls'])]
        if row['id']=='R20':
            row['x_posts']=[{'url':'https://x.com/i/status/2059324685985464550','date':'2026-05-26',
                             'match':'X 帖明确写 v61 dashboards-as-code；按版本号定位官方发布记录，不是链接精确匹配'}]
        row['discovery']='X 线索 + 官网核对' if row['x_posts'] else '官网补充'
        row['existing_matches']=[e['event_id'] for e in existing if any(canonical(u)==key for u in e['urls'])]
        row['duplicate_status']='已有同源内容' if row['existing_matches'] else '未命中已有源链接'
    assert len(ROWS)==20
    assert len({canonical(r['source_url']) for r in ROWS})==20
    assert not any(r['existing_matches'] for r in ROWS), 'Existing content must not count as a new candidate'
    assert all(r['source_date'].startswith('2026-') for r in ROWS)
    (ROOT/'candidates.json').write_text(json.dumps(ROWS,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'candidates':len(ROWS),'categories':dict(Counter(r['category'] for r in ROWS)),
                      'x_matched_candidates':sum(bool(r['x_posts']) for r in ROWS)},ensure_ascii=False))

if __name__=='__main__': main()
