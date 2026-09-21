"""Reader relevance, separate from editorial quality and social heat.

Only titles, short source summaries and explicit topics are considered. A
vendor name, broad category or recommendation prose is not evidence that an
ordinary database release concerns AI data products.
"""
import re

FOCUS_AREAS = (
    ("data-agent", "数据 Agent"),
    ("ai-platform", "AI 数据平台"),
    ("semantic-layer", "语义层"),
    ("ai-analysis", "AI 数据分析"),
    ("ai-dashboard", "AI 看板"),
)


def _has(pattern, text):
    return bool(re.search(pattern, text, re.I))


def content_focus(event):
    title = str(event.get("zh_title") or event.get("title") or "")
    text = title + " " + str(event.get("zh_summary") or event.get("summary") or "")
    topics = {str(t).casefold() for t in (event.get("topics") or [])}
    ai = _has(r"(?<![a-z0-9])(?:AI|LLM|agentic|generative|copilot)(?![a-z0-9])|人工智能|生成式|智能体|自然语言", text)
    data_context = _has(r"业务|数据仓库|数据平台|数据分析|数据查询|问数|取数|SQL|语义|指标口径|表结构|schema|metadata|analytics|dbt|数据与上下文|数据集|经营|库存|订单", text)
    agent_pattern = r"data\s+agents?|数据\s*(?:Agent|智能体|代理)|(?:取数|分析|问数)(?:型)?\s*(?:Agent|智能体|代理)|Genie|Cortex\s+Agents?|Fabric\s+Data\s+Agent|Metabot|Spotter"
    agent = _has(agent_pattern, title) or (data_context and _has(agent_pattern, text))
    platform = ai and _has(r"(?:AI|智能体|Agent)[\s\w]{0,12}数据平台|数据平台.{0,18}(?:AI|智能体|Agent)|上下文.{0,6}(?:目录|管理|发布)|Context\s+Studio|Knowledge\s+Catalog|AI\s+data\s+platform|AI\s+Functions", text)
    semantic = _has(r"语义层|语义模型|语义视图|指标口径|业务契约|semantic\s+(?:layer|model|view)|metrics?\s+layer", text) or "语义层" in topics
    dashboard = ai and _has(r"看板|仪表[盘板]|dashboard|liveboard|ChartSpec|generative\s+data\s+apps", text)
    analysis = (ai and _has(r"数据分析|对话分析|分析计算|问数|Text.to.SQL|分析助手|AI\s+analyst|conversational\s+analytics", text)) or "chatbi" in topics
    if agent or ("data agent" in topics and data_context):
        index = 0
    elif platform:
        index = 1
    elif semantic:
        index = 2
    elif dashboard and _has(r"看板|仪表[盘板]|dashboard|liveboard|ChartSpec|generative\s+data\s+apps", title):
        index = 4
    elif analysis:
        index = 3
    elif dashboard:
        index = 4
    else:
        index = 5
    practical = index < 5 and _has(
        r"评测|评估|验收|基准|权限|身份|上下文|口径|交互|可编辑|执行轨迹|纠错|恢复|"
        r"benchmark|evaluat|permission|context|workflow|trace", text,
    )
    identity, label = FOCUS_AREAS[index] if index < 5 else ("other", "其他数据动态")
    return {"id": identity, "label": label, "priority": index, "practical": practical}


def focus_sort_key(event):
    focus = content_focus(event)
    return (-focus["priority"], int(focus["practical"]))
