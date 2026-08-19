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
    def test_freshness_has_a_48_hour_half_life(self):
        reference = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
        self.assertAlmostEqual(run_update.freshness(reference, reference), 1.0)
        self.assertAlmostEqual(
            run_update.freshness(reference - timedelta(hours=48), reference),
            0.5,
        )

    def test_event_heat_prefers_publication_time_over_recent_ingestion(self):
        reference = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
        historical = event(
            "historical",
            importance=95,
            published=(reference - timedelta(days=100)).isoformat(),
            first_seen=reference.isoformat(),
        )
        recent = event(
            "recent",
            importance=70,
            published=(reference - timedelta(hours=2)).isoformat(),
            first_seen=(reference - timedelta(hours=2)).isoformat(),
        )

        run_update.recalc_event_heat(historical, reference_time=reference)
        run_update.recalc_event_heat(recent, reference_time=reference)

        self.assertLess(historical["heat"], recent["heat"])

    def test_empty_snowflake_release_note_is_rejected_before_enrichment(self):
        empty = item(
            "snowflake-empty",
            "10.28 release notes (no announcements) (preview)",
            source="Snowflake Release Notes",
            source_type="vendor",
            vendor_default=True,
            article_text=(
                "This release has no significant features, updates, or "
                "enhancements to announce."
            ),
        )
        substantive = dict(empty)
        substantive["id"] = "snowflake-real"
        substantive["title"] = "Snowflake 10.29 adds semantic view materialization"
        substantive["article_text"] = "This release adds semantic view materialization."
        other_source = dict(empty)
        other_source["id"] = "other-source"
        other_source["source"] = "Independent analysis"
        self.assertTrue(run_update.is_empty_release_note(empty))
        self.assertFalse(run_update.is_empty_release_note(substantive))
        self.assertFalse(run_update.is_empty_release_note(other_source))
        self.assertEqual(run_update.llm_enrich([empty], ("", "", "")), [])

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

    def test_media_policy_is_bound_to_the_named_source(self):
        configs = {
            "Official": {
                "media_hosts": ["cdn.official.invalid"],
                "media_referer": "article",
            },
            "Other": {},
        }
        self.assertEqual(run_update.source_media_policy("Official", configs), {
            "allowed_hosts": ["cdn.official.invalid"], "send_referer": True,
        })
        self.assertEqual(run_update.source_media_policy("Other", configs), {
            "allowed_hosts": [], "send_referer": False,
        })

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

    def test_chinese_original_is_direct_complete_and_idempotent(self):
        target = event("e1", title="数据平台发布")
        original = "第一段原文事实。\n\n" + "第二段包含数字 123。" * 300
        primary = item("p1", "数据平台发布", article_text=original)
        with patch.object(run_update, "llm_chat_text") as generate:
            first = run_update.generate_event_body(
                target, primary, ("k", "base", "model"), {}
            )
            second = run_update.generate_event_body(
                target, primary, ("k", "base", "model"), {}
            )
        self.assertEqual(first, original)
        self.assertEqual(second, original)
        self.assertGreater(len(first), 1200)
        self.assertEqual(target["content_mode"], "original")
        self.assertEqual(target["source_language"], "zh")
        self.assertEqual(target["translation_status"], "not_needed")
        generate.assert_not_called()

    def test_foreign_original_is_faithfully_translated_without_length_cap(self):
        target = event("foreign", zh_summary="摘要")
        primary = item("p2", "Data update", article_text="English source paragraph. " * 400)
        with patch.object(run_update, "llm_chat_text", side_effect=lambda *_a, **_k: "忠实译文段落。" * 300) as translate:
            result = run_update.generate_event_body(target, primary, ("k", "base", "model"), {})
            again = run_update.generate_event_body(target, primary, ("k", "base", "model"), {})
        self.assertEqual(result, again)
        self.assertGreater(len(result), 1200)
        self.assertEqual(target["content_mode"], "translated")
        self.assertEqual(target["translation_status"], "complete")
        self.assertGreaterEqual(translate.call_count, 1)

    def test_translation_budget_failure_keeps_foreign_original_not_ai_summary(self):
        target = event("budget", zh_summary="预算摘要")
        original = "English source fact 123. " * 80
        primary = item("p", "Data update", article_text=original)
        with patch.object(run_update, "llm_chat_text", side_effect=LLMBudgetExceeded("limit")):
            result = run_update.generate_event_body(target, primary, ("k", "base", "model"), {})
        self.assertEqual(result, original.strip())
        self.assertEqual(target["content_mode"], "original")
        self.assertEqual(target["translation_status"], "failed")

    def test_same_hash_foreign_original_retries_after_budget_failure(self):
        target = event("retry", zh_summary="预算摘要")
        original = "English source fact 123. " * 80
        primary = item("p", "Data update", article_text=original)
        with patch.object(run_update, "llm_chat_text", side_effect=LLMBudgetExceeded("limit")):
            first = run_update.generate_event_body(target, primary, ("k", "base", "model"), {})
        with patch.object(run_update, "llm_chat_text", return_value="忠实中文译文。" * 80) as translate:
            second = run_update.generate_event_body(target, primary, ("k", "base", "model"), {})
        self.assertEqual(first, original.strip())
        self.assertTrue(second.startswith("忠实中文译文"))
        self.assertEqual(target["content_mode"], "translated")
        self.assertEqual(target["translation_status"], "complete")
        translate.assert_called()

    def test_whole_article_budget_preflight_keeps_original_without_partial_calls(self):
        target = event("preflight", zh_summary="预算摘要")
        original = "English source fact 123. " * 80
        primary = item("p", "Data update", article_text=original)
        with patch.object(run_update.LLM_USAGE, "can_call", return_value=False), patch.object(
            run_update.LLM_USAGE, "budget_status",
            return_value={"available_tokens": 100, "available": False},
        ), patch.object(run_update, "llm_chat_text") as translate:
            result = run_update.generate_event_body(target, primary, ("k", "base", "model"), {})
        self.assertEqual(result, original.strip())
        self.assertEqual(target["content_parse"]["translation"]["status"], "budget_deferred")
        translate.assert_not_called()

    def test_unavailable_original_is_the_only_summary_fallback(self):
        target = event("missing", zh_summary="保留摘要")
        primary = item("p", "Data update", article_text="", summary="")
        result = run_update.generate_event_body(target, primary, ("k", "base", "model"), {})
        self.assertEqual(result, "保留摘要")
        self.assertEqual(target["content_mode"], "ai_fallback")

    def test_late_merge_can_be_disabled_for_existing_events(self):
        existing = [event("a"), event("b")]
        with patch.object(run_update, "llm_same_event") as judge:
            result = run_update.cluster_events([], existing, ("k", "base", "model"), late_merge=False)
        self.assertEqual(len(result), 2)
        judge.assert_not_called()

    def test_backfill_upgrades_chinese_text_and_visual_articles_without_llm(self):
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

        self.assertEqual(summary["ready"], 2)
        self.assertEqual(summary["attempted"], 2)
        self.assertEqual(summary["planned"], 2)
        self.assertEqual(visual["content_format"], "blocks-v1")
        self.assertEqual(visual["content_parse"]["status"], "ready")
        self.assertEqual(visual["content_parse"]["media"]["cached"], 1)
        self.assertEqual(plain["content_mode"], "original")
        translate.assert_not_called()

    def test_backfill_retries_an_old_processor_and_chinese_does_not_use_foreign_cap(self):
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
        self.assertEqual(summary["ready"], 2)
        self.assertFalse(hasattr(translated, "called_item"))
        self.assertEqual(same_site["content_parse"]["processor_version"], "original-first-v6")
        self.assertEqual(cross_site["content_mode"], "original")

    def test_media_refresh_retries_only_source_bound_recoverable_figures(self):
        figure = {
            "type": "figure", "src": "https://cdn.official.invalid/chart.png",
            "source_url": "https://example.com/allowed", "alt": "chart", "caption": "",
            "media_status": "link_only", "media_reason": "cross_site_host",
        }
        allowed = event("allowed", importance=90, content_blocks=[figure])
        allowed["items"][0]["source"] = "Official"
        blocked = event("blocked", importance=80, content_blocks=[dict(figure)])
        blocked["items"][0]["source"] = "Other"
        already_current = event("current", importance=100, content_blocks=[dict(figure)])
        already_current["items"][0]["source"] = "Official"
        already_current["content_parse"] = {
            "media": {"policy_version": run_update.MEDIA_CACHE_POLICY_VERSION},
        }
        cached_figure = dict(figure)
        cached_figure.update({
            "cached_src": "../media/allowed/0123456789abcdef01234567.png",
            "media_status": "cached",
        })
        cached_figure.pop("media_reason", None)
        report = {
            "figures": 1, "cached": 1, "link_only": 0, "bytes": 123,
            "reasons": {}, "policy_version": run_update.MEDIA_CACHE_POLICY_VERSION,
        }
        configs = {
            "Official": {
                "media_hosts": ["cdn.official.invalid"],
                "media_referer": "article",
            },
            "Other": {},
        }
        with patch.object(
            run_update, "cache_event_media", return_value=([cached_figure], report),
        ) as cache:
            summary = run_update.refresh_media_cache(
                [allowed, blocked, already_current], configs, limit=10,
            )
        self.assertEqual((summary["eligible"], summary["attempted"], summary["cached"]), (1, 1, 1))
        self.assertEqual(allowed["content_blocks"][0]["media_status"], "cached")
        self.assertEqual(
            allowed["content_parse"]["media"]["policy_version"],
            run_update.MEDIA_CACHE_POLICY_VERSION,
        )
        cache.assert_called_once()
        self.assertEqual(cache.call_args.kwargs["allowed_hosts"], ["cdn.official.invalid"])
        self.assertTrue(cache.call_args.kwargs["send_referer"])

    def test_backfill_foreign_translation_has_separate_run_cap(self):
        first = event("foreign-a", importance=90)
        second = event("foreign-b", importance=80)
        blocks = [{
            "type": "paragraph", "id": "b-foreign00001",
            "children": [{
                "type": "text", "id": "t-foreign00001",
                "text": "English source facts and benchmark numbers. " * 20,
                "marks": [],
            }],
        }]
        report = {
            "strategy": "article", "blocks": 1, "text_chars": 840,
            "figures": 0, "tables": 0, "figures_discovered": 0,
            "figures_selected": 0, "figures_rejected": 0,
        }
        def translate_when_configured(source_blocks, configured, **_kwargs):
            if not configured[0]:
                return [], {"applied": 0, "ignored": 0, "missing": 1, "complete": False}
            return source_blocks, {"applied": 1, "ignored": 0, "missing": 0, "complete": True}

        with patch.object(
            run_update, "fetch_article_content",
            return_value=("English source facts. " * 40, "", None, blocks, report),
        ), patch.object(
            run_update, "translate_article_blocks",
            side_effect=translate_when_configured,
        ) as translate, patch.object(
            run_update, "cache_event_media",
            return_value=(blocks, {"figures": 0, "cached": 0, "link_only": 0, "reasons": {}}),
        ):
            summary = run_update.backfill_structured_content(
                [first, second], ("k", "base", "model"), now=NOW,
                limit=1, lookback_days=30,
            )
        self.assertEqual(summary["ready"], 2)
        self.assertEqual(summary["deferred_foreign"], 1)
        self.assertEqual(sum(bool(call.args[1][0]) for call in translate.call_args_list), 1)
        self.assertEqual(first["content_mode"], "translated")
        self.assertEqual(second["content_mode"], "original")

    def test_backfill_retries_stored_foreign_original_without_refetching(self):
        target = event("stored", importance=90)
        target.update({
            "full_zh": "English stored original facts. " * 80,
            "content_mode": "original",
            "source_language": "other",
            "translation_status": "unavailable",
        })
        with patch.object(run_update, "fetch_article_content") as fetch, patch.object(
            run_update, "translate_plain_text", return_value="忠实中文译文。" * 80,
        ) as translate:
            summary = run_update.backfill_structured_content(
                [target], ("k", "base", "model"), now=NOW, limit=1, lookback_days=30,
            )
        self.assertEqual(summary["stored_original_retries"], 1)
        self.assertEqual(target["content_mode"], "translated")
        fetch.assert_not_called()
        translate.assert_called_once()

    def test_old_structured_foreign_original_is_refetched_before_retry(self):
        target = event("stored-old-parser", importance=91)
        target.update({
            "full_zh": "View pricing. See the product in action.",
            "content_blocks": [{
                "type": "paragraph",
                "children": [{
                    "type": "text", "text": "View pricing. See the product in action.",
                    "marks": [],
                }],
            }],
            "content_mode": "original", "source_language": "other",
            "translation_status": "unavailable",
            "content_parse": {
                "processor_version": "original-first-v1", "quality_status": "suspect",
                "status": "ready",
            },
        })
        source_blocks = [{
            "type": "paragraph",
            "children": [{
                "type": "text", "text": "Complete English article facts. " * 40, "marks": [],
            }],
        }]
        report = {
            "strategy": "semantic_container", "quality_status": "pass", "quality_flags": [],
            "blocks": 1, "text_chars": 1280, "figures": 0, "tables": 0,
            "figures_discovered": 0, "figures_selected": 0, "figures_rejected": 0,
        }
        with patch.object(
            run_update, "fetch_article_content",
            return_value=("Complete English article facts. " * 40, "", None, source_blocks, report),
        ) as fetch, patch.object(
            run_update, "cache_event_media",
            side_effect=lambda blocks, *_args, **_kwargs: (
                blocks, {"figures": 0, "cached": 0, "link_only": 0, "reasons": {}},
            ),
        ):
            summary = run_update.backfill_structured_content(
                [target], ("", "", ""), now=NOW, limit=0, lookback_days=30,
            )

        self.assertEqual(summary["ready"], 1)
        self.assertEqual(summary["stored_original_retries"], 0)
        self.assertEqual(target["content_mode"], "original")
        self.assertEqual(target["content_parse"]["processor_version"], "original-first-v6")
        self.assertEqual(target["content_parse"]["quality_status"], "pass")
        self.assertIn("Complete English article facts", target["full_zh"])
        self.assertNotIn("View pricing", target["full_zh"])
        fetch.assert_called_once()

    def test_parser_upgrade_reuses_trimmed_translation_and_repairs_publish_date(self):
        target = event("upgrade", importance=95)
        translated_blocks = [{
            "type": "paragraph",
            "id": "b-111111111111",
            "children": [{
                "type": "text", "id": "t-111111111111",
                "text": "忠实中文译文和数字 123。" * 75, "marks": [],
            }],
        }, {
            "type": "paragraph",
            "children": [{"type": "text", "text": "未找到项目。", "marks": []}],
        }, {
            "type": "heading", "level": 2,
            "children": [{"type": "text", "text": "相关文章", "marks": []}],
        }]
        target.update({
            "full_zh": "忠实中文译文和数字 123。" * 75,
            "content_blocks": translated_blocks,
            "content_mode": "translated",
            "source_language": "other",
            "translation_status": "complete",
            "source_content_hash": "old-parser-hash",
            "content_parse": {
                "processor_version": "original-first-v3",
                "status": "ready",
                "attempted_at": NOW.isoformat(),
            },
        })
        source_blocks = [{
            "type": "paragraph",
            "id": "b-111111111111",
            "children": [{
                "id": "t-111111111111",
                "type": "text",
                "text": "Faithful source facts and number 123. " * 32,
                "marks": [],
            }],
        }]
        report = {
            "strategy": "semantic_container", "quality_status": "pass",
            "quality_flags": [], "candidate_count": 2, "selected_score": 1111.5,
            "trimmed_tail_blocks": 0, "blocks": 1, "text_chars": 1184,
            "figures": 0, "tables": 0, "figures_discovered": 0,
            "figures_selected": 0, "figures_rejected": 0,
        }
        published = datetime(2026, 5, 22, tzinfo=timezone.utc)
        with patch.object(
            run_update, "fetch_article_content",
            return_value=("Faithful source facts. " * 60, "", published, source_blocks, report),
        ), patch.object(run_update, "translate_article_blocks") as translate, patch.object(
            run_update, "cache_event_media",
            side_effect=lambda blocks, *_args, **_kwargs: (
                blocks, {"figures": 0, "cached": 0, "link_only": 0, "reasons": {}},
            ),
        ), patch.dict(run_update.os.environ, {"CONTENT_BACKFILL_EVENT_IDS": "upgrade"}):
            summary = run_update.backfill_structured_content(
                [target], ("", "", ""), now=NOW, limit=0, lookback_days=30,
            )

        self.assertEqual(summary["ready"], 1)
        self.assertEqual(summary["requested_event_ids"], ["upgrade"])
        self.assertEqual(target["content_parse"]["processor_version"], "original-first-v6")
        self.assertTrue(target["content_parse"]["translation"]["reused"])
        self.assertEqual(
            target["content_parse"]["translation"]["reuse_method"],
            "aligned_stored_translation",
        )
        self.assertEqual(
            target["content_parse"]["translation"]["alignment"]["status"], "aligned",
        )
        self.assertEqual(target["content_parse"]["translation"]["trimmed_tail_blocks"], 2)
        self.assertEqual(target["content_parse"]["translation"]["trimmed_promotional_blocks"], 0)
        self.assertEqual(target["content_parse"]["quality_status"], "pass")
        self.assertNotIn("未找到项目", target["full_zh"])
        self.assertTrue(target["published"].startswith("2026-05-22"))
        translate.assert_not_called()

    def test_parser_upgrade_rejects_unaligned_stored_translation(self):
        target = event("unaligned", importance=94)
        target.update({
            "full_zh": "与当前来源无结构对应关系的旧译文。" * 60,
            "content_blocks": [{
                "type": "paragraph", "id": "b-aaaaaaaaaaaa",
                "children": [{
                    "type": "text", "id": "t-aaaaaaaaaaaa",
                    "text": "与当前来源无结构对应关系的旧译文。" * 60, "marks": [],
                }],
            }],
            "content_mode": "translated", "source_language": "other",
            "translation_status": "complete",
            "content_parse": {"processor_version": "original-first-v3", "status": "ready"},
        })
        source_blocks = [{
            "type": "paragraph", "id": "b-bbbbbbbbbbbb",
            "children": [{
                "type": "text", "id": "t-bbbbbbbbbbbb",
                "text": "Current English source facts and measured results. " * 30, "marks": [],
            }],
        }]
        report = {
            "strategy": "article", "quality_status": "pass", "quality_flags": [],
            "blocks": 1, "text_chars": 1530, "figures": 0, "tables": 0,
            "figures_discovered": 0, "figures_selected": 0, "figures_rejected": 0,
        }
        with patch.object(
            run_update, "fetch_article_content",
            return_value=("Current English source facts. " * 50, "", None, source_blocks, report),
        ), patch.object(
            run_update, "cache_event_media",
            side_effect=lambda blocks, *_args, **_kwargs: (
                blocks, {"figures": 0, "cached": 0, "link_only": 0, "reasons": {}},
            ),
        ), patch.dict(run_update.os.environ, {"CONTENT_BACKFILL_EVENT_IDS": "unaligned"}):
            summary = run_update.backfill_structured_content(
                [target], ("", "", ""), now=NOW, limit=0, lookback_days=30,
            )
        self.assertEqual(summary["ready"], 1)
        self.assertEqual(target["content_mode"], "original")
        self.assertEqual(target["translation_status"], "unavailable")
        self.assertIn("Current English source facts", target["full_zh"])
        self.assertNotIn("reused", target["content_parse"]["translation"])

    def test_old_evergreen_parser_debt_is_upgraded_outside_recent_window(self):
        target = event("old-evergreen", importance=70)
        old_time = NOW - timedelta(days=180)
        target.update({
            "published": old_time.isoformat(), "first_seen": old_time.isoformat(),
            "shelf": "evergreen", "content_mode": "original", "source_language": "zh",
            "translation_status": "not_needed",
            "content_blocks": [{
                "type": "paragraph",
                "children": [{"type": "text", "text": "旧版正文。" * 90, "marks": []}],
            }],
            "content_parse": {"processor_version": "original-first-v1", "status": "ready"},
        })
        fresh_blocks = [{
            "type": "paragraph",
            "children": [{"type": "text", "text": "重新解析后的可信正文。" * 90, "marks": []}],
        }]
        report = {
            "strategy": "article", "quality_status": "pass", "quality_flags": [],
            "blocks": 1, "text_chars": 900, "figures": 0, "tables": 0,
            "figures_discovered": 0, "figures_selected": 0, "figures_rejected": 0,
        }
        with patch.object(
            run_update, "fetch_article_content",
            return_value=("重新解析后的可信正文。" * 90, "", None, fresh_blocks, report),
        ), patch.object(
            run_update, "cache_event_media",
            side_effect=lambda blocks, *_args, **_kwargs: (
                blocks, {"figures": 0, "cached": 0, "link_only": 0, "reasons": {}},
            ),
        ):
            summary = run_update.backfill_structured_content(
                [target], ("", "", ""), now=NOW, limit=0, lookback_days=30,
            )
        self.assertEqual(summary["parser_debt_eligible"], 1)
        self.assertEqual(summary["ready"], 1)
        self.assertEqual(target["content_parse"]["processor_version"], "original-first-v6")
        self.assertTrue(target["full_zh"].startswith("重新解析后的可信正文"))

    def test_current_processor_with_unknown_quality_is_not_treated_as_complete(self):
        target = event("unknown-quality", importance=75)
        target.update({
            "content_mode": "original", "source_language": "zh",
            "translation_status": "not_needed",
            "content_blocks": [{
                "type": "paragraph",
                "children": [{"type": "text", "text": "待复核正文。" * 90, "marks": []}],
            }],
            "content_parse": {
                "processor_version": "original-first-v6", "quality_status": "unknown",
                "status": "ready", "attempted_at": (NOW - timedelta(days=8)).isoformat(),
            },
        })
        report = {
            "strategy": "article", "quality_status": "pass", "quality_flags": [],
            "blocks": 1, "text_chars": 900, "figures": 0, "tables": 0,
            "figures_discovered": 0, "figures_selected": 0, "figures_rejected": 0,
        }
        with patch.object(
            run_update, "fetch_article_content",
            return_value=("质量已确认的正文。" * 90, "", None, target["content_blocks"], report),
        ), patch.object(
            run_update, "cache_event_media",
            side_effect=lambda blocks, *_args, **_kwargs: (
                blocks, {"figures": 0, "cached": 0, "link_only": 0, "reasons": {}},
            ),
        ) as cache:
            summary = run_update.backfill_structured_content(
                [target], ("", "", ""), now=NOW, limit=0, lookback_days=30,
            )
        self.assertEqual(summary["attempted"], 1)
        self.assertEqual(target["content_parse"]["quality_status"], "pass")
        cache.assert_called_once()

    def test_metadata_backfill_repairs_recent_event_and_records_token_purpose(self):
        target = event(
            "metadata", title="English title", zh_summary="English summary",
            importance=50,
        )
        target["items"][0]["title"] = "English title"
        output = {
            "relevant": True,
            "zh_title": "数据平台英文文章标题",
            "zh_summary": "这是一段忠实的中文摘要，保留原文事实。",
            "reason": "值得数据从业者关注。",
            "category": "platform",
            "topics": [], "vendors": [], "importance": 65, "shelf": "news",
        }
        with patch.object(run_update, "llm_chat", return_value=output) as call:
            summary = run_update.backfill_event_metadata(
                [target], ("k", "base", "model"), now=NOW, limit=1,
            )
        self.assertEqual(summary["complete"], 1)
        self.assertEqual(target["zh_title"], output["zh_title"])
        self.assertEqual(target["content_parse"]["metadata_translation"]["status"], "complete")
        self.assertEqual(call.call_args.kwargs["purpose"], "metadata_translation_backfill")

    def test_update_workflow_uses_new_translation_limits_and_exact_env_names(self):
        workflow = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
        self.assertIn("MAX_LLM_TOKENS_PER_DAY: ${{ vars.MAX_LLM_TOKENS_PER_DAY || '1000000' }}", workflow)
        self.assertIn("CONTENT_TRANSLATION_BACKFILL_LIMIT:", workflow)
        self.assertIn("CONTENT_METADATA_BACKFILL_LIMIT:", workflow)
        self.assertIn("CONTENT_BACKFILL_ATTEMPTS:", workflow)
        self.assertIn("CONTENT_BACKFILL_EVENT_IDS:", workflow)
        self.assertIn("backfill_event_ids:", workflow)
        self.assertNotIn("CONTENT_BLOCKS_BACKFILL_LIMIT:", workflow)
        self.assertNotIn("CONTENT_BLOCKS_BACKFILL_ATTEMPTS:", workflow)

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

    def test_catalog_normalizer_cleans_stored_translation_and_is_idempotent(self):
        def paragraph(text):
            return {
                "type": "paragraph",
                "children": [{"type": "text", "text": text, "marks": []}],
            }

        target = event("polluted")
        target.update({
            "content_mode": "translated",
            "translation_status": "complete",
            "content_format": "blocks-v1",
            "content_blocks": [
                paragraph("收听本文 - 0:00"),
                paragraph("音频已准备好播放"),
                paragraph("您的浏览器不支持音频元素。"),
                paragraph("0:00"),
                paragraph("0:00"),
                {"type": "list", "ordered": False, "items": [{"children": [{
                    "type": "text", "text": "阅读列表", "marks": [],
                }]}]},
                paragraph("可信译文正文。" * 80),
            ],
            "full_zh": "仍包含旧播放器文案",
            "content_parse": {"processor_version": "original-first-v4", "quality_status": "pass"},
        })

        first = run_update.normalize_catalog_article_ui([target])
        second = run_update.normalize_catalog_article_ui([target])

        self.assertEqual(first["cleaned_events"], 1)
        self.assertEqual(first["removed_blocks"], 6)
        self.assertEqual(second["cleaned_events"], 0)
        self.assertTrue(target["full_zh"].startswith("可信译文正文"))
        self.assertNotIn("收听本文", target["full_zh"])
        self.assertEqual(
            target["content_parse"]["article_ui_cleanup"]["policy_version"],
            "article-chrome-v2",
        )

    def test_catalog_normalizer_persists_full_head_and_tail_boundary_cleanup(self):
        def paragraph(text, href=""):
            marks = [{"type": "link", "href": href}] if href else []
            return {
                "type": "paragraph",
                "children": [{"type": "text", "text": text, "marks": marks}],
            }

        title = "通用 Agent 进了企业，Data Agent 还要不要单独买？"
        target = event("article-chrome")
        target.update({
            "content_mode": "original",
            "translation_status": "not_needed",
            "content_format": "blocks-v1",
            "content_blocks": [
                paragraph("产品 解决方案 客户案例", "https://example.com/nav"),
                paragraph("首页 > 博客 > " + title, "https://example.com/blog"),
                {"type": "heading", "level": 2, "children": [{
                    "type": "text", "text": title, "marks": [],
                }]},
                paragraph("作者：周卫林 2026-08-19"),
                paragraph("可信正文事实与结论。" * 90),
                paragraph("下一篇"),
                paragraph("相邻文章", "https://example.com/next"),
                paragraph("相关博客"),
            ],
            "full_zh": "旧正文仍包含页面组件",
            "content_parse": {
                "processor_version": "original-first-v5", "quality_status": "pass",
            },
        })

        first = run_update.normalize_catalog_article_ui([target])
        second = run_update.normalize_catalog_article_ui([target])
        cleanup = target["content_parse"]["article_ui_cleanup"]

        self.assertEqual(first["cleaned_events"], 1)
        self.assertEqual(first["removed_blocks"], 7)
        self.assertEqual(second["cleaned_events"], 0)
        self.assertEqual(cleanup["trimmed_head_blocks"], 4)
        self.assertEqual(cleanup["trimmed_tail_blocks"], 3)
        self.assertTrue(target["full_zh"].startswith("可信正文事实"))
        self.assertNotIn("下一篇", target["full_zh"])
        self.assertEqual(target["content_parse"]["blocks"], 1)

    def test_catalog_normalizer_cleans_legacy_plain_body_without_rewriting_prose(self):
        prose = "第一句是正文。第二句仍在同一段，不应被重新切段。" * 20
        target = event("legacy-polluted")
        target.update({
            "full_zh": "\n\n".join([
                "收听本文 - 0:00",
                "音频已准备好播放",
                "您的浏览器不支持音频元素。",
                "0:00",
                "阅读列表",
                prose,
            ]),
            "content_mode": "translated",
            "translation_status": "complete",
        })

        summary = run_update.normalize_catalog_article_ui([target])

        self.assertEqual(summary["cleaned_events"], 1)
        self.assertEqual(summary["removed_blocks"], 5)
        self.assertEqual(target["full_zh"], prose)

    def test_catalog_metrics_expose_current_quality_and_parser_debt(self):
        current = event("current")
        current.update({
            "content_mode": "original",
            "content_blocks": [{
                "type": "paragraph",
                "children": [{"type": "text", "text": "可信正文。" * 80, "marks": []}],
            }],
            "content_parse": {
                "processor_version": "original-first-v6", "quality_status": "pass",
            },
        })
        debt = event("debt")
        debt.update({
            "content_mode": "translated",
            "content_blocks": [{
                "type": "paragraph",
                "children": [{"type": "text", "text": "旧版正文。" * 80, "marks": []}],
            }],
            "content_parse": {
                "processor_version": "original-first-v1", "quality_status": "unknown",
            },
        })

        metrics = run_update.catalog_content_metrics([current, debt])

        self.assertEqual(metrics["structured"], 2)
        self.assertEqual(metrics["renderable"], 2)
        self.assertEqual(metrics["current_pass"], 1)
        self.assertEqual(metrics["parser_debt"], 1)
        self.assertEqual(metrics["modes"], {"original": 1, "translated": 1})


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
