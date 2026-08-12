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

    def test_low_precision_candidates_fail_closed_without_llm(self):
        strict = item(
            "community", "Analytics community post",
            source_tier="community_targeted",
        )
        trusted = item(
            "official", "Official data platform update",
            source_tier="official_high",
        )
        enriched = run_update.llm_enrich([strict, trusted], ("", "", ""))
        self.assertEqual([candidate["id"] for candidate in enriched], ["official"])

    def test_low_precision_candidates_fail_closed_when_enrichment_errors(self):
        original_cache = run_update.CANDIDATE_CACHE
        with tempfile.TemporaryDirectory() as tmp:
            run_update.CANDIDATE_CACHE = CandidateCache(
                Path(tmp) / "candidate.json", environ={}, now_fn=lambda: NOW
            )
            strict = item(
                "community", "Analytics community post",
                source_tier="community_targeted",
            )
            trusted = item(
                "official", "Official data platform update",
                source_tier="official_high",
            )
            try:
                with patch.object(run_update, "llm_chat", side_effect=TimeoutError("timeout")):
                    enriched = run_update.llm_enrich(
                        [strict, trusted], ("key", "base", "model"),
                        generate_fulltext=False,
                    )
            finally:
                run_update.CANDIDATE_CACHE = original_cache
        self.assertEqual([candidate["id"] for candidate in enriched], ["official"])

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

    def test_backfill_is_bounded_and_only_upgrades_visual_articles(self):
        visual = event("visual", title="带图文章", importance=90)
        plain = event("plain", title="纯文字文章", importance=80)
        blocks = [
            {
                "type": "paragraph", "id": "b-p",
                "children": [{"type": "text", "id": "t-p", "text": "正文" * 80, "marks": []}],
            },
            {
                "type": "figure", "id": "b-f", "src": "https://example.com/chart.png",
                "alt": "chart", "caption": "benchmark", "source_url": "https://example.com/visual",
                "width": 900, "height": 500,
            },
        ]
        visual_report = {
            "strategy": "article", "blocks": 2, "text_chars": 164,
            "figures": 1, "tables": 0, "figures_discovered": 1,
            "figures_selected": 1, "figures_rejected": 0,
        }
        plain_report = {
            "strategy": "article", "blocks": 1, "text_chars": 500,
            "figures": 0, "tables": 0, "figures_discovered": 0,
            "figures_selected": 0, "figures_rejected": 0,
        }

        def fetched(url, **_kwargs):
            if url.endswith("/visual"):
                return "正文" * 80, "", None, blocks, visual_report
            return "纯文字" * 200, "", None, blocks[:1], plain_report

        media_report = {"figures": 1, "cached": 1, "link_only": 0, "reasons": {}}
        with patch.object(run_update, "fetch_article_content", side_effect=fetched), patch.object(
            run_update, "translate_article_blocks", return_value=(blocks, {"applied": 3, "ignored": 0, "missing": 0})
        ) as translate, patch.object(
            run_update, "cache_event_media", return_value=(blocks, media_report)
        ):
            summary = run_update.backfill_structured_content(
                [visual, plain], ("k", "base", "model"), now=NOW, limit=1, lookback_days=30,
            )

        self.assertEqual(summary["ready"], 1)
        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["planned"], 1)
        self.assertEqual(visual["content_format"], "blocks-v1")
        self.assertEqual(visual["content_parse"]["status"], "ready")
        self.assertEqual(visual["content_parse"]["media"]["cached"], 1)
        self.assertNotIn("content_blocks", plain)
        self.assertEqual(translate.call_args.kwargs["purpose"], "body_blocks_backfill")

    def test_backfill_retries_an_old_processor_and_prioritizes_cacheable_media(self):
        cross_site = event("cross", title="跨站图片", importance=95)
        same_site = event("same", title="同站图片", importance=80)
        cross_site["content_parse"] = {
            "processor_version": "blocks-v1", "attempted_at": NOW.isoformat(),
            "status": "failed",
        }

        def figure_blocks(event_id, image_host):
            return [
                {
                    "type": "paragraph", "id": f"b-{event_id}0000000000"[:14],
                    "children": [{"type": "text", "id": f"t-{event_id}0000000000"[:14], "text": "正文" * 80, "marks": []}],
                },
                {
                    "type": "figure", "id": f"b-{event_id}1111111111"[:14],
                    "src": f"https://{image_host}/chart.png", "alt": "chart",
                    "source_url": f"https://example.com/{event_id}",
                    "width": 900, "height": 500,
                },
            ]

        def fetched(url, **_kwargs):
            event_id = url.rsplit("/", 1)[-1]
            host = "cdn.other.test" if event_id == "cross" else "images.example.com"
            blocks = figure_blocks(event_id, host)
            report = {
                "strategy": "article", "blocks": 2, "text_chars": 165,
                "figures": 1, "tables": 0, "figures_discovered": 1,
                "figures_selected": 1, "figures_rejected": 0,
            }
            return "正文" * 80, "", None, blocks, report

        def translated(blocks, _cfg, **kwargs):
            translated.called_item = kwargs["item_id"]
            return blocks, {"applied": 2, "ignored": 0, "missing": 0}

        media_report = {"figures": 1, "cached": 1, "link_only": 0, "reasons": {}}
        with patch.object(run_update, "fetch_article_content", side_effect=fetched), patch.object(
            run_update, "translate_article_blocks", side_effect=translated
        ), patch.object(run_update, "cache_event_media", return_value=(figure_blocks("same", "images.example.com"), media_report)):
            summary = run_update.backfill_structured_content(
                [cross_site, same_site], ("k", "base", "model"), now=NOW,
                limit=1, lookback_days=30,
            )

        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["ready"], 1)
        self.assertEqual(translated.called_item, "same")
        self.assertEqual(same_site["content_parse"]["processor_version"], "blocks-v2")
        self.assertNotIn("content_blocks", cross_site)

    def test_structured_metrics_are_scoped_to_the_current_run_and_source(self):
        current = event("current")
        current["content_parse"] = {
            "run_id": "run-current", "status": "ready", "source": "Feed",
            "strategy": "article", "figures": 2, "tables": 1,
            "media": {"cached": 1, "link_only": 1},
        }
        old = event("old")
        old["content_parse"] = {
            "run_id": "run-old", "status": "failed", "source": "Feed",
            "strategy": "document_fallback", "figures": 0, "tables": 0,
            "reason": "too_short",
        }
        metrics = run_update.structured_content_metrics([current, old], run_id="run-current")
        self.assertEqual(metrics["attempted"], 1)
        self.assertEqual(metrics["ready"], 1)
        self.assertEqual(metrics["figures"], 2)
        self.assertEqual(metrics["tables"], 1)
        self.assertEqual(metrics["media_cached"], 1)
        self.assertEqual(metrics["by_source"]["Feed"]["ready"], 1)


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
