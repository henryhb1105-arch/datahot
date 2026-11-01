"""Narrow, evidence-bound repairs for historical cross-source metadata merges.

These repairs do not certify source completeness or replace stored article bodies.
Issue #262: the PERIOD tutorial inherited an unrelated release-note summary.
"""
import hashlib
from urllib.parse import urlsplit


def repair_content_metadata(events):
    """Repair only the reviewed body/source and known stale summary; return count."""
    repaired = 0
    for event in events:
        if event.get("event_id") != "113da8bd65f9":
            continue
        items = event.get("items") or []
        source = urlsplit(str(items[0].get("link", ""))) if items else None
        if not source or source.hostname != "medium.com" or source.path != (
            "/snowflake/query-time-ranges-with-snowflakes-period-data-type-ce229d2306bd"
        ):
            continue
        if event.get("source_content_hash") != "121e1c58182f7f199d2831cb":
            continue
        body_hash = hashlib.sha256(str(event.get("full_zh", "")).encode()).hexdigest()
        if body_hash != "915c60da4cce12bbe442d83bc987432c5f7bca988f3a81f34a85efbda240769c":
            continue
        if not str(event.get("zh_summary", "")).startswith("Snowflake 发布 10.32 版本说明"):
            continue
        event["zh_summary"] = (
            "已收录正文通过生效日期查找、历史记录关联和跨报告周时长分配三个 SQL 示例，"
            "介绍 Snowflake PERIOD 时间范围类型。示例涉及范围包含、相交及半开区间边界；"
            "正文完整性仍待核验，使用前请对照原文和官方文档。"
        )
        event["reason"] = (
            "适合需要处理生效时间、历史版本或跨周期统计的数据从业者，作为查询写法参考。"
            "示例不构成性能或合规保证。"
        )
        repaired += 1
    return repaired
