import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from candidate_cache import CandidateCache  # noqa: E402
from lite_data import lite_event  # noqa: E402
import run_update  # noqa: E402
from work_tags import (  # noqa: E402
    DIMENSION_NAMES, TAXONOMY_VERSION, audit_events, merge_work_tags,
    normalize_work_tags, validation_errors,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 12, 10, 0, tzinfo=TZ)


def item(item_id="work-tags", **overrides):
    values = {
        "id": item_id,
        "title": "Semantic metrics for analytics agents",
        "zh_title": "面向分析Agent的语义指标",
        "summary": "A governed semantic layer is exposed to analytics agents.",
        "zh_summary": "治理后的语义指标开放给分析Agent。",
        "reason": "",
        "link": f"https://example.com/{item_id}",
        "source": "Official Blog",
        "source_type": "rss",
        "category": "platform",
        "category_label": "AI 数据平台",
        "vendors": [],
        "vendor_default": True,
        "published": NOW.isoformat(),
        "ingested_at": NOW.isoformat(),
        "_pub_dt": NOW,
        "signal": 0,
        "importance": 50,
        "topics": [],
        "shelf": "news",
        "heat": 50,
        "star": False,
        "article_text": "Semantic metrics and evaluation facts.",
    }
    values.update(overrides)
    return values


class WorkTagTests(unittest.TestCase):
    def test_normalize_uses_closed_vocabulary_deduplicates_and_caps(self):
        normalized = normalize_work_tags({
            "taxonomy_version": "untrusted-version",
            "product_objects": ["指标与语义", "非法标签", "指标与语义", "知识与上下文", "数据资产"],
            "use_cases": "Agent构建",
            "decision_concerns": ["可靠性与评估", 42, "成本与性能", "权限与安全"],
        })
        self.assertEqual(normalized["taxonomy_version"], TAXONOMY_VERSION)
        self.assertEqual(normalized["product_objects"], ["指标与语义", "知识与上下文"])
        self.assertEqual(normalized["use_cases"], [])
        self.assertEqual(normalized["decision_concerns"], ["可靠性与评估", "成本与性能"])

    def test_merge_is_optional_ordered_and_capped(self):
        self.assertIsNone(merge_work_tags(None, None))
        merged = merge_work_tags(
            {"product_objects": ["指标与语义"], "use_cases": ["Agent构建"]},
            {"product_objects": ["知识与上下文", "数据资产"], "use_cases": ["方案封装与分发"]},
        )
        self.assertEqual(merged["product_objects"], ["指标与语义", "知识与上下文"])
        self.assertEqual(merged["use_cases"], ["Agent构建", "方案封装与分发"])

    def test_enrichment_adds_tags_in_existing_call_and_cache_payload(self):
        original_cache = run_update.CANDIDATE_CACHE
        with tempfile.TemporaryDirectory() as tmp:
            run_update.CANDIDATE_CACHE = CandidateCache(
                Path(tmp) / "candidate.json", environ={}, now_fn=lambda: NOW
            )
            output = {
                "relevant": True,
                "zh_title": "语义指标开放给分析Agent",
                "zh_summary": "摘要",
                "reason": "推荐理由",
                "category": "agent",
                "topics": ["Data Agent", "语义层"],
                "work_tags": {
                    "product_objects": ["指标与语义", "非法标签"],
                    "use_cases": ["Agent构建"],
                    "decision_concerns": ["可靠性与评估"],
                },
                "vendors": [],
                "importance": 70,
                "shelf": "news",
            }
            try:
                with patch.object(run_update, "llm_chat", return_value=output) as llm_call:
                    enriched = run_update.llm_enrich(
                        [item()], ("key", "base", "model"), generate_fulltext=False
                    )
                run_update.CANDIDATE_CACHE.finalize()
                cache_payload = json.loads((Path(tmp) / "candidate.json").read_text())
            finally:
                run_update.CANDIDATE_CACHE = original_cache
        self.assertEqual(llm_call.call_count, 1)
        self.assertEqual(enriched[0]["work_tags"]["product_objects"], ["指标与语义"])
        cached = next(iter(cache_payload["entries"].values()))["enrichment"]
        self.assertEqual(cached["work_tags"], enriched[0]["work_tags"])

    def test_event_merge_and_lite_projection_keep_valid_tags(self):
        primary = item(work_tags=normalize_work_tags({
            "product_objects": ["指标与语义"],
            "use_cases": ["Agent构建"],
        }))
        event = run_update.make_event(primary)
        secondary = item("secondary", work_tags={
            "product_objects": ["知识与上下文"],
            "use_cases": ["方案封装与分发"],
            "decision_concerns": ["可靠性与评估"],
        })
        run_update.merge_into(event, secondary)
        self.assertEqual(event["work_tags"]["product_objects"], ["指标与语义", "知识与上下文"])
        self.assertEqual(lite_event(event)["work_tags"], event["work_tags"])
        self.assertEqual(validation_errors(event["work_tags"]), [])

    def test_legacy_event_remains_untagged_and_valid_for_projection(self):
        legacy = run_update.make_event(item())
        self.assertNotIn("work_tags", legacy)
        self.assertNotIn("work_tags", lite_event(legacy))

    def test_audit_reports_coverage_and_invalid_events(self):
        good = {"event_id": "good", "work_tags": normalize_work_tags({"use_cases": ["指标问答"]})}
        bad = {"event_id": "bad", "work_tags": {
            "taxonomy_version": "old",
            "product_objects": ["非法标签"],
            "use_cases": [],
            "decision_concerns": [],
        }}
        report = audit_events([good, bad, {"event_id": "legacy"}])
        self.assertEqual(report["processed_events"], 2)
        self.assertEqual(report["tagged_events"], 1)
        self.assertEqual(report["processed_coverage"], 0.6667)
        self.assertEqual(report["tagged_coverage"], 0.3333)
        self.assertIn("bad", report["invalid_events"])
        self.assertEqual(tuple(report["counts"]), DIMENSION_NAMES)

    def test_prompt_and_cache_version_are_tied_to_taxonomy(self):
        self.assertIn("work_tags", run_update.ENRICH_RULES)
        self.assertIn("指标与语义", run_update.ENRICH_RULES)
        self.assertIn(TAXONOMY_VERSION, run_update.ENRICH_RULE_VERSION)
        self.assertIn("AI分析与洞察分类边界", run_update.ENRICH_RULES)
        self.assertIn("组织人才", run_update.ENRICH_RULES)
        self.assertIn("agent|platform|bi|product|insight", run_update.ENRICH_RULES)


if __name__ == "__main__":
    unittest.main()
