"""Conservative, body-based promotion policy; never delete source material.

Unknown evidence stays visible. A failed/partial extraction is a separate status,
not a quality verdict. This deliberately does not use LLM summaries or scores as
proof of substance, since they can make a thin announcement sound useful.
"""
import os
import re
from functools import lru_cache

POLICY_VERSION = "information-value-v2"


def _has(pattern, text):
    return bool(re.search(pattern, text, re.I))


def information_value(event):
    report = event.get("content_parse") or {}
    titles = (str(event.get("zh_title") or event.get("title") or ""),) + tuple(
        str(item.get("title") or "") for item in event.get("items") or []
    )
    status, reason = _assess(
        str(event.get("content_mode") or ""),
        str(event.get("full_zh") or event.get("article_text") or "").strip(),
        str(report.get("status") or ""), str(report.get("quality_status") or ""),
        str(report.get("strategy") or ""), titles,
    )
    return {"policy_version": POLICY_VERSION, "status": status, "reason": reason}


@lru_cache(maxsize=4096)
def _assess(content_mode, body, parse_status, quality_status, strategy, titles):
    # Key by immutable evidence, not event ID: content edits invalidate the result.
    # Return tuples so callers cannot mutate the shared cached assessment.
    def result(status, reason):
        return status, reason

    if content_mode == "editorial_excerpt":
        return result("reviewed_excerpt", "manually_reviewed_reading_notes")
    # RSS fallbacks can look complete while containing only a teaser (Iceberg
    # 0.7.0 is a real example). Never classify them as low information.
    if (not body or parse_status != "ready"
            or quality_status != "pass"
            or "fallback" in strategy.lower()):
        return result("insufficient_body", "full_body_not_verified")

    if _has(r"加入\s*SHRM.{0,25}独家访问权限|SHRM会员可无限访问|SHRM会员.{0,12}登录以访问完整报告|\bjoin SHRM.{0,40}exclusive access\b", body):
        return result("insufficient_body", "access_wall_instead_of_article")
    if _has(r"简介[：:].{0,1500}目录\s+热门文章\s*$", body.replace("\n", " ")):
        return result("insufficient_body", "article_wrapper_without_body")
    if len(body) < 200 and _has(r"阅读文章\s*>|Read (?:the )?article\s*>", body):
        return result("insufficient_body", "linked_article_snippet")

    context = " ".join(titles) + " " + body
    resource_pointer = _has(r"(?:在.{0,8}(?:指南|手册)中|在这本手册中|指南.{0,8}(?:涵盖|分享)|编制了.{0,8}指南|整理了.{0,25}手册|阅读全文.{0,15}了解)|\b(?:inside the guide|in this playbook|put together a (?:practical )?(?:guide|playbook)|read the full post)\b", body)
    announcement_scope = resource_pointer or _has(r"发布|公告|预览|推出|版本|新指南|指南|\b(?:release|announc\w*|preview|launch\w*|introduc\w*|guide)\b", context)

    # Only body evidence counts. Dates, PR totals and contributor counts are
    # deliberately absent. Technical words alone (AI, SQL, plugin) do not count.
    evidence = (
        r"(?:现在|新增).{0,5}支持增量扫描|\bnow supports incremental scans?\b",
        r"(?:现在可以|现可|新增|支持|引入)\s*(?:JSON|CSV|Parquet|IPv[46]|Iceberg|OAuth|JWT|JDBC|API|SQL|行级权限)",
        r"\b(?:now (?:can|allows?)|supports?|support for|adds?|introduces?)\s+(?:JSON|CSV|Parquet|IPv[46]|Iceberg|OAuth|JWT|JDBC|API|SQL)\b",
        r"(?:自然语言|用户问题|商家请求).{0,55}(?:转化|转换|生成).{0,35}(?:SQL|查询|可视化)",
        r"\b(?:natural language|user questions?).{0,65}\b(?:translat\w*|convert\w*|generat\w*).{0,40}\b(?:SQL|queries|visualizations?)\b",
        r"(?:多.?Agent|多智能体).{0,55}(?:协调|编排|协作).{0,25}\d+",
        r"\bmulti.agent.{0,65}\b(?:coordinat\w*|orchestrat\w*).{0,25}\d+",
        r"(?:修复|修正|不再支持|改为|默认禁用|默认启用|不可.{0,5}禁用)",
        r"\b(?:fixed|no longer|disabled by default|enabled by default|can no longer)\b",
        r"(?:仅限|限制为|必须|需要先|上限|不支持).{0,45}(?:账户|角色|权限|版本|区域|请求|用户|模型|条|次|GB|MB|SQL)",
        r"\b(?:requires?|limited to|only available|not supported)\b.{0,65}\b(?:account|role|permission|version|region|request|user|model|GB|MB)\b",
        r"(?:打开|点击|选择|运行|执行|设置|启用).{0,60}(?:菜单|目录|命令|参数|配置|连接器|属性|按钮|SQL)",
        r"\b(?:open|click|select|run|execute|set|enable)\b.{0,65}\b(?:menu|directory|command|parameter|config\w*|connector|property|button|SQL)\b",
        r"(?:存储|校验|验证|排序|联接|下推|剪枝|编码|隔离).{0,55}(?:IPv[46]|128|数值|谓词|行级|令牌|schema|SQL|子网)",
        r"(?:IPv[46]|128.bit|predicate|row.level|token|schema).{0,55}\b(?:stor\w*|validat\w*|sort\w*|join\w*|prun\w*|encod\w*|isolat\w*)\b",
        r"(?:延迟|吞吐|准确率|成本|耗时).{0,30}\d+(?:\.\d+)?\s*(?:%|毫秒|秒|倍|美元)",
        r"\b(?:latency|throughput|accuracy|cost)\b.{0,35}\d+(?:\.\d+)?\s*(?:%|ms|seconds|USD)",
        r"\b(?:SELECT\s+.+\s+FROM|ALTER\s+|CREATE\s+|pip install|npm install|curl -)",
    )
    # A promise to teach SQL/repairs later is not an operation performed here.
    # Inspect sentences independently so an actual instruction elsewhere in the
    # same announcement can still override the teaser verdict.
    promise = r"(?:在.{0,8}(?:指南|手册)中|在这本手册中|指南.{0,8}(?:涵盖|分享)|将(?:介绍|讲解|教你)|您将了解|如何.{0,25}(?:修复|运行|执行|设置))|\b(?:inside the guide|in this playbook|guide,? we share|will (?:cover|teach|learn)|how to)\b"
    chunks = re.split(r"(?<=[。！？])|\n\s*\n|(?<=\.)\s+(?=[A-Z])", body)
    fact_body = "\n".join(chunk for chunk in chunks if not _has(promise, chunk) or _has(r"\bSELECT\s+.+\s+FROM\b|\bpip install\s+\S+|\bcurl -", chunk))
    if any(_has(pattern, fact_body) for pattern in evidence):
        return result("substantive", "concrete_body_evidence")

    # A resource announcement that only promises what a linked guide will teach.
    # Require both the teaser and an outbound call to read/download the resource.
    teaser = resource_pointer or _has(r"(?:在指南中|指南.{0,8}(?:涵盖|分享)|编制了.{0,8}指南)|\b(?:inside the guide|guide,? we share|put together a guide)\b", body)
    cta = _has(r"(?:查看|下载|获取|阅读).{0,16}(?:这里|此处|指南|报告|全文)|\b(?:check it out|download the guide|read the full guide|read the full post)\b", body)
    if teaser and cta:
        return result("low_information", "resource_teaser_without_details")

    # For other announcements, only hide when every sentence is recognisable
    # boilerplate. An unfamiliar sentence prevents a negative verdict.
    generic = r"敬请期待|即将发布|敬请关注|赋能|释放.{0,8}潜力|革命性|贡献者|\bPRs?\b|完整变更日志|\b(?:stay tuned|coming soon|revolutionary|unlock|empower|contributors?|full changelog)\b"
    sentences = [s.strip() for s in re.split(r"[。！？\n]+|(?<=[a-z])\.\s+", body) if len(s.strip()) > 2]
    launch_only = (
        r"^(?:我们|社区)?(?:很高兴|欣然|隆重)?宣布(?:发布|全新平台|版本发布|版本更新)$"
        r"|^(?:(?:The .{0,35}community is|We are) )?(?:pleased|excited|proud|thrilled) to announce (?:version [\d.]+|[A-Za-z0-9_-]+ [\d.]+)[.!]?$"
    )
    if sentences and all(_has(generic, sentence) or _has(launch_only, sentence) for sentence in sentences):
        return result("low_information", "announcement_boilerplate_only")
    return result("unclassified", "needs_editorial_review" if announcement_scope else "outside_announcement_scope")


def policy_enabled():
    return os.getenv("LOW_INFORMATION_FILTER_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def promotion_review_required(event):
    # Historical weekly snapshots are metadata projections, not failed captures.
    # New projections carry the server decision explicitly; never infer a new
    # extraction failure from a projection intentionally omitting article text.
    if not any(key in event for key in ("full_zh", "article_text", "content_parse")):
        return policy_enabled() and event.get("body_review_required") is True
    return policy_enabled() and information_value(event)["status"] == "insufficient_body"


def suppress_from_lists(event):
    return policy_enabled() and information_value(event)["status"] == "low_information"
