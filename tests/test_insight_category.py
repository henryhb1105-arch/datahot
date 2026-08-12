import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402
import run_update  # noqa: E402
from taxonomy import CATEGORY_LABELS, normalize_category_label  # noqa: E402


def insight_event():
    published = datetime(2026, 8, 12, tzinfo=timezone.utc).isoformat()
    return {
        "event_id": "555555555555",
        "zh_title": "员工数据揭示组织技能缺口",
        "zh_summary": "分析给出了具体的人才配置建议。",
        "reason": "这项发现可用于人才规划决策。",
        "full_zh": "正文",
        "category": "insight",
        "category_label": "AI 分析与洞察",
        "vendors": ["Visier"],
        "topics": ["组织人才"],
        "heat": 60,
        "importance": 70,
        "signal": 0,
        "star": False,
        "shelf": "news",
        "pinned": False,
        "published": published,
        "first_seen": published,
        "items": [{
            "id": "source-55",
            "source": "Visier Blog",
            "link": "https://www.visier.com/blog/example/",
            "published": published,
            "title": "Workforce insight",
        }],
    }


class InsightCategoryTests(unittest.TestCase):
    def test_category_is_rendered_with_existing_card_structure(self):
        card = build_site.render_card(insight_event())
        self.assertIn('data-cat="insight"', card)
        self.assertEqual(build_site.CAT_BADGE["insight"], "b-insight")
        self.assertEqual(build_site.CAT_LABEL["insight"], "AI分析")
        self.assertIs(build_site.CAT_LABEL, CATEGORY_LABELS)
        self.assertIn("组织人才", card)

    def test_legacy_display_label_is_normalized_from_stable_category(self):
        record = insight_event()
        self.assertTrue(normalize_category_label(record))
        self.assertEqual(record["category"], "insight")
        self.assertEqual(record["category_label"], "AI分析")
        self.assertFalse(normalize_category_label(record))

    def test_cached_legacy_label_cannot_reenter_pipeline(self):
        item = insight_event()
        cached = {"enrichment": {
            "category": "insight", "category_label": "AI 分析与洞察",
        }}
        restored = run_update._cached_enrichment(item, cached)
        self.assertEqual(restored["category_label"], "AI分析")

    def test_business_scenes_reuse_topic_taxonomy(self):
        topics = json.loads((ROOT / "pipeline" / "topics.json").read_text(encoding="utf-8"))
        names = {topic["name"] for topic in topics}
        self.assertTrue({
            "组织人才", "财务经营", "销售增长", "客户运营", "供应链", "风险管理",
        }.issubset(names))
        self.assertEqual(len({topic["slug"] for topic in topics}), len(topics))

    def test_cache_migration_is_limited_to_insight_focused_sources(self):
        base = {
            "id": "candidate",
            "link": "https://example.com/post",
            "title": "Workforce analytics",
            "summary": "Employee data analysis",
            "source": "Databricks Blog",
        }
        regular = run_update._candidate_cache_context(base, "model")
        focused = run_update._candidate_cache_context(
            dict(base, source="Visier Blog"), "model"
        )
        self.assertEqual(regular["rule_version"], run_update.ENRICH_RULE_VERSION)
        self.assertEqual(focused["rule_version"], run_update.INSIGHT_ENRICH_RULE_VERSION)
        self.assertNotEqual(regular["rule_version"], focused["rule_version"])


if __name__ == "__main__":
    unittest.main()
