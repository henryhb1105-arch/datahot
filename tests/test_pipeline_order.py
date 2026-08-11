import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from candidate_cache import CandidateCache  # noqa: E402
from cluster_cache import ClusterDecisionCache, cluster_pair_key  # noqa: E402
from llm_usage import LLMBudgetExceeded  # noqa: E402
import run_update  # noqa: E402


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=TZ)


def item(item_id, title, source="Media", **overrides):
    values = {
        "id": item_id,
        "title": title,
        "zh_title": title,
        "summary": "data analytics platform update",
        "zh_summary": "这是一条数据平台更新摘要。",
        "reason": "",
        "link": f"https://example.com/{item_id}",
        "source": source,
        "source_type": "media",
        "category": "platform",
        "category_label": "AI 数据平台",
        "vendors": [],
        "vendor_default": False,
        "published": NOW.isoformat(),
        "ingested_at": NOW.isoformat(),
        "_pub_dt": NOW,
        "signal": 0,
        "importance": 50,
        "topics": [],
        "shelf": "news",
        "heat": 50,
        "star": False,
        "article_text": "原文事实。" * 1000,
    }
    values.update(overrides)
    return values


def event(event_id, title="同一数据平台发布", **overrides):
    values = {
        "event_id": event_id,
        "zh_title": title,
        "zh_summary": "事件摘要",
        "reason": "",
        "full_zh": "",
        "category": "platform",
        "category_label": "AI 数据平台",
        "vendors": [],
        "heat": 50,
        "star": False,
        "importance": 50,
        "signal": 0,
        "topics": [],
        "shelf": "news",
        "pinned": False,
        "published": NOW.isoformat(),
        "first_seen": NOW.isoformat(),
        "items": [{
            "id": event_id,
            "source": "Feed",
            "link": f"https://example.com/{event_id}",
            "published": NOW.isoformat(),
            "title": title,
        }],
    }
    values.update(overrides)
    return values


class EventFirstPipelineTests(unittest.TestCase):
    def test_candidate_cache_precedes_rule_filter(self):
        original_cache = run_update.CANDIDATE_CACHE
        with tempfile.TemporaryDirectory() as tmp:
            cache = CandidateCache(Path(tmp) / "candidate.json", environ={}, now_fn=lambda: NOW)
            candidate = item("cached", "Analytics update")
            cache.remember(
                **run_update._candidate_cache_context(candidate, "model"),
                status="rejected",
            )
            run_update.CANDIDATE_CACHE = cache
            try:
                prechecked = run_update.precheck_candidate_cache(
                    [candidate], ("k", "base", "model")
                )
            finally:
                run_update.CANDIDATE_CACHE = original_cache
        self.assertEqual(prechecked, [])

    def test_rule_filter_is_high_recall_for_data_and_rejects_obvious_consumer_ai(self):
        candidates = [
            item("data", "New semantic layer for analytics"),
            item("phone", "New AI smartphone and gaming features", summary="consumer device"),
        ]
        kept = run_update.rule_prefilter_candidates(candidates)
        self.assertEqual([candidate["id"] for candidate in kept], ["data"])

    def test_current_run_candidates_cluster_before_enrichment(self):
        candidates = [
            item("a", "Databricks launches analytics agent"),
            item("b", "Databricks launches analytics agent today"),
        ]
        with patch.object(run_update, "llm_same_event", return_value=[True]) as judge:
            groups = run_update.group_candidate_items(candidates, ("k", "base", "model"))
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)
        judge.assert_called_once()

    def test_official_source_is_selected_as_primary(self):
        group = [
            item("media", "Data update", source="News"),
            item("official", "Data update", source="Databricks Blog", vendor_default=True),
        ]
        configs = {
            "News": {"tier": "media_low", "weight": 2},
            "Databricks Blog": {"tier": "official_high", "weight": 3},
        }
        self.assertEqual(
            run_update.select_primary_source(group, configs)["id"],
            "official",
        )

    def test_metadata_enrichment_can_skip_fulltext(self):
        original_cache = run_update.CANDIDATE_CACHE
        with tempfile.TemporaryDirectory() as tmp:
            run_update.CANDIDATE_CACHE = CandidateCache(
                Path(tmp) / "candidate.json", environ={}, now_fn=lambda: NOW
            )
            output = {
                "relevant": True,
                "zh_title": "数据平台更新",
                "zh_summary": "摘要",
                "reason": "值得关注",
                "category": "platform",
                "topics": [],
                "vendors": [],
                "importance": 60,
                "shelf": "news",
            }
            try:
                with patch.object(run_update, "llm_chat", return_value=output), patch.object(
                    run_update, "compile_fulltext"
                ) as compile_call:
                    enriched = run_update.llm_enrich(
                        [item("a", "Analytics update")],
                        ("k", "base", "model"),
                        generate_fulltext=False,
                    )
            finally:
                run_update.CANDIDATE_CACHE = original_cache
        self.assertEqual(len(enriched), 1)
        compile_call.assert_not_called()

    def test_body_generation_is_idempotent_and_standard_length_is_bounded(self):
        target = event("e1", title="数据平台发布")
        primary = item("p1", "Data platform launch")
        body = "## 关键事实\n" + "数" * 1300
        with patch.object(run_update, "llm_chat_text", return_value=body) as generate:
            first = run_update.generate_event_body(
                target, primary, ("k", "base", "model"), {"deep_used": 0, "max_deep": 0}
            )
            second = run_update.generate_event_body(
                target, primary, ("k", "base", "model"), {"deep_used": 0, "max_deep": 0}
            )
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 600)
        self.assertLessEqual(len(first), 1200)
        self.assertEqual(target["content_level"], "standard")
        generate.assert_called_once()

    def test_short_or_budget_exhausted_body_degrades_to_summary(self):
        short = event("short", zh_summary="保留摘要")
        primary = item("p2", "Data update")
        with patch.object(run_update, "llm_chat_text", return_value="过短"):
            result = run_update.generate_event_body(
                short, primary, ("k", "base", "model"), {"deep_used": 0, "max_deep": 0}
            )
        self.assertEqual(result, "保留摘要")
        self.assertEqual(short["content_level"], "summary")

        budget = event("budget", zh_summary="预算摘要")
        with patch.object(
            run_update, "llm_chat_text", side_effect=LLMBudgetExceeded("limit")
        ):
            result = run_update.generate_event_body(
                budget, primary, ("k", "base", "model"), {"deep_used": 0, "max_deep": 0}
            )
        self.assertEqual(result, "预算摘要")
        self.assertEqual(budget["content_level"], "summary")

    def test_deep_generation_has_explicit_gate_and_run_cap(self):
        state = {"deep_used": 0, "max_deep": 1}
        primary = item("p", "Evergreen data guide")
        deep = event("deep", shelf="evergreen", importance=90)
        capped = event("capped", shelf="evergreen", importance=90)
        with patch.object(run_update, "compile_fulltext", return_value="深度正文" * 200) as compile_call, patch.object(
            run_update, "llm_chat_text", return_value="标准正文" * 200
        ) as standard_call:
            run_update.generate_event_body(deep, primary, ("k", "base", "model"), state)
            run_update.generate_event_body(capped, primary, ("k", "base", "model"), state)
        self.assertEqual(deep["content_level"], "deep")
        self.assertEqual(capped["content_level"], "standard")
        self.assertEqual(state["deep_used"], 1)
        compile_call.assert_called_once()
        standard_call.assert_called_once()

    def test_late_merge_can_be_disabled_for_existing_events(self):
        existing = [event("a"), event("b")]
        with patch.object(run_update, "llm_same_event") as judge:
            result = run_update.cluster_events([], existing, ("k", "base", "model"), late_merge=False)
        self.assertEqual(len(result), 2)
        judge.assert_not_called()


class ClusterCacheTests(unittest.TestCase):
    def test_pair_key_is_order_independent(self):
        self.assertEqual(cluster_pair_key("A", "B"), cluster_pair_key("B", "A"))

    def test_llm_cluster_decision_is_reused(self):
        original = run_update.CLUSTER_CACHE
        with tempfile.TemporaryDirectory() as tmp:
            run_update.CLUSTER_CACHE = ClusterDecisionCache(
                Path(tmp) / "cluster.json", environ={}, now_fn=lambda: NOW
            )
            try:
                with patch.object(run_update, "llm_chat", return_value={"same": True}) as call:
                    first = run_update.llm_same_event([("A", "B")], ("k", "base", "model"))
                    second = run_update.llm_same_event([("B", "A")], ("k", "base", "model"))
            finally:
                run_update.CLUSTER_CACHE = original
        self.assertEqual(first, [True])
        self.assertEqual(second, [True])
        self.assertEqual(call.call_count, 1)


if __name__ == "__main__":
    unittest.main()
