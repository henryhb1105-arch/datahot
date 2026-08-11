import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402
from llm_usage import LLMBudgetExceeded  # noqa: E402
import run_update  # noqa: E402
from weekly_brief import (  # noqa: E402
    PROMPT_VERSION, brief_cache_key, brief_input_hash, completed_week,
    generate_weekly_brief, select_weekly_events,
)


def event(
    number, *, seen="2026-08-05T08:00:00+08:00", category=None,
    heat=None, summary=None, source=None,
):
    categories = ["agent", "platform", "bi", "product"]
    category = category or categories[number % len(categories)]
    event_id = f"{number:012x}"
    source = source or f"Source {number}"
    return {
        "event_id": event_id,
        "zh_title": f"事件 {number}",
        "zh_summary": summary if summary is not None else f"摘要 {number}",
        "reason": f"推荐理由 {number}",
        "category": category,
        "category_label": build_site.CAT_LABEL[category],
        "heat": heat if heat is not None else 90 - number,
        "importance": 80 - number,
        "first_seen": seen,
        "published": seen,
        "vendors": [f"Vendor {number}"],
        "items": [{"source": source, "link": f"https://example.com/{number}"}],
    }


def ai_response():
    return {
        "headline": "本周数据基础设施变化",
        "overview": "本期高价值动态覆盖平台、Agent、BI 与数据产品。",
        "key_changes": ["平台能力继续整合", "Agent 场景进一步落地", "语义层连接更多分析入口"],
        "trend": "数据平台与 Agent 的结合继续深化，多个事件都强调可信语义和可验证输出。",
        "next_watch": ["跟踪语义层产品落地", "观察 Agent 在分析流程中的可靠性"],
    }


class WeeklyBriefSelectionTests(unittest.TestCase):
    def test_completed_week_uses_beijing_monday_to_sunday(self):
        period = completed_week(datetime(2026, 8, 11, 2, tzinfo=timezone.utc))
        self.assertEqual(period["week_id"], "2026-W32")
        self.assertEqual(str(period["period_start"]), "2026-08-03")
        self.assertEqual(str(period["period_end"]), "2026-08-09")

    def test_week_boundaries_category_coverage_and_limit(self):
        events = [event(i) for i in range(18)]
        events.append(event(30, seen="2026-08-02T23:59:00+08:00", heat=100))
        events.append(event(31, seen="2026-08-10T00:00:00+08:00", heat=100))
        selected = select_weekly_events(events, "2026-08-03", "2026-08-09")
        ids = {item["event_id"] for item in selected}
        self.assertEqual(len(selected), 15)
        self.assertNotIn(f"{30:012x}", ids)
        self.assertNotIn(f"{31:012x}", ids)
        self.assertEqual(
            {item["category"] for item in selected},
            {"agent", "platform", "bi", "product"},
        )

    def test_same_source_is_capped_at_two(self):
        shared = [event(i, source="Burst Feed", heat=100 - i) for i in range(8)]
        diverse = [event(20 + i, source=f"Diverse {i}") for i in range(12)]
        selected = select_weekly_events(shared + diverse, "2026-08-03", "2026-08-09")
        self.assertLessEqual(
            sum(item["items"][0]["source"] == "Burst Feed" for item in selected), 2,
        )
        self.assertEqual(len(selected), 14)

    def test_unfinished_or_backfilled_items_do_not_enter_week(self):
        current = [event(i) for i in range(10)]
        unfinished = event(30, heat=100, summary="")
        old = event(31, seen="2026-08-01T08:00:00+08:00", heat=100)
        selected = select_weekly_events(
            current + [unfinished, old], "2026-08-03", "2026-08-09",
        )
        ids = {item["event_id"] for item in selected}
        self.assertNotIn(unfinished["event_id"], ids)
        self.assertNotIn(old["event_id"], ids)

    def test_cache_key_covers_week_input_prompt_and_model(self):
        events = [event(i) for i in range(10)]
        original_hash = brief_input_hash(events)
        changed = [dict(item) for item in events]
        changed[0]["zh_summary"] = "内容发生变化"
        changed_hash = brief_input_hash(changed)
        self.assertNotEqual(original_hash, changed_hash)
        base = brief_cache_key("2026-W32", original_hash, PROMPT_VERSION, "deepseek-v4")
        self.assertNotEqual(base, brief_cache_key("2026-W33", original_hash, PROMPT_VERSION, "deepseek-v4"))
        self.assertNotEqual(base, brief_cache_key("2026-W32", changed_hash, PROMPT_VERSION, "deepseek-v4"))
        self.assertNotEqual(base, brief_cache_key("2026-W32", original_hash, "weekly-brief-v2", "deepseek-v4"))


class WeeklyBriefGenerationTests(unittest.TestCase):
    def paths(self, directory):
        root = Path(directory)
        return root / "cache.json", root / "brief.json", root / "weekly"

    def test_same_week_is_immutable_and_does_not_call_llm_twice(self):
        calls = []

        def fake(prompt, *, item_id):
            calls.append((prompt, item_id))
            return ai_response()

        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            events = [event(i) for i in range(15)]
            first, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=fake,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            events[0]["zh_summary"] = "同周后续回填改变了输入"
            second, second_status = generate_weekly_brief(
                events, now=datetime(2026, 8, 16, 8, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=fake,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            self.assertEqual(status, "generated_ai")
            self.assertEqual(second_status, "weekly_cache_hit")
            self.assertEqual(len(calls), 1)
            self.assertEqual(first["cache_key"], second["cache_key"])
            self.assertEqual(len(first["items"]), 15)
            self.assertTrue((archive / "2026-W32.json").exists())

    def test_new_completed_week_creates_new_archive(self):
        calls = []

        def fake(_prompt, *, item_id):
            calls.append(item_id)
            return ai_response()

        week_32 = [event(i) for i in range(10)]
        week_33 = [event(20 + i, seen="2026-08-12T08:00:00+08:00") for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            generate_weekly_brief(
                week_32 + week_33, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=fake,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            second, status = generate_weekly_brief(
                week_32 + week_33, now=datetime(2026, 8, 18, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=fake,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            self.assertEqual(status, "generated_ai")
            self.assertEqual(second["week_id"], "2026-W33")
            self.assertEqual(calls, ["2026-W32", "2026-W33"])
            self.assertTrue((archive / "2026-W32.json").exists())
            self.assertTrue((archive / "2026-W33.json").exists())

    def test_monday_waits_until_eight_in_beijing(self):
        events = [event(20 + i, seen="2026-08-12T08:00:00+08:00") for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            brief, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 16, 18, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=lambda *_args, **_kwargs: ai_response(),
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            self.assertIsNone(brief)
            self.assertEqual(status, "before_publish_time")
            self.assertFalse(output.exists())
            brief, status = generate_weekly_brief(
                events, now=datetime(2026, 8, 17, 0, 17, tzinfo=timezone.utc),
                model="", llm_generate=None,
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            self.assertEqual(status, "generated_rule")
            self.assertEqual(brief["week_id"], "2026-W33")

    def test_unconfigured_failed_and_budget_exhausted_have_rule_fallback(self):
        cases = [
            ("", None, "llm_unconfigured"),
            ("deepseek-v4", lambda *_args, **_kwargs: {}, "invalid_llm_response"),
            (
                "deepseek-v4",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(LLMBudgetExceeded("limit")),
                "LLMBudgetExceeded",
            ),
        ]
        for index, (model, callback, reason) in enumerate(cases):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                cache, output, archive = self.paths(tmp)
                brief, status = generate_weekly_brief(
                    [event(i) for i in range(10)],
                    now=datetime(2026, 8, 11, 2 + index, tzinfo=timezone.utc),
                    model=model, llm_generate=callback,
                    cache_path=cache, output_path=output, archive_dir=archive,
                )
                self.assertEqual(status, "generated_rule")
                self.assertFalse(brief["ai_assisted"])
                self.assertEqual(brief["fallback_reason"], reason)

    def test_fewer_than_ten_items_waits_without_call_or_cache(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            brief, status = generate_weekly_brief(
                [event(i) for i in range(9)],
                now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=lambda *args, **kwargs: calls.append(args),
                cache_path=cache, output_path=output, archive_dir=archive,
            )
            self.assertIsNone(brief)
            self.assertEqual(status, "insufficient_items")
            self.assertFalse(calls)
            self.assertFalse(cache.exists())
            self.assertFalse(output.exists())

    def test_run_update_marks_weekly_usage_and_manual_force_only(self):
        config = ("key", "https://example.test", "deepseek-v4")
        now = datetime(2026, 8, 11, 2, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            with patch.object(run_update, "llm_chat", return_value=ai_response()) as chat:
                brief, status = run_update.generate_weekly_brief_for_events(
                    [event(i) for i in range(10)], config, now,
                    cache_path=cache, output_path=output, archive_dir=archive,
                )
            self.assertEqual(status, "generated_ai")
            self.assertTrue(brief["ai_assisted"])
            self.assertEqual(chat.call_args.kwargs["purpose"], "weekly_brief")
            self.assertEqual(chat.call_args.kwargs["source"], "weekly_brief")
            self.assertEqual(chat.call_args.kwargs["item_id"], "2026-W32")

            with patch.dict(
                run_update.os.environ,
                {"WEEKLY_BRIEF_FORCE": "true", "GITHUB_EVENT_NAME": "schedule"},
                clear=False,
            ):
                with patch.object(run_update, "llm_chat", return_value=ai_response()) as scheduled:
                    _brief, cache_status = run_update.generate_weekly_brief_for_events(
                        [event(i) for i in range(10)], config, now,
                        cache_path=cache, output_path=output, archive_dir=archive,
                    )
            self.assertEqual(cache_status, "weekly_cache_hit")
            scheduled.assert_not_called()

            with patch.dict(
                run_update.os.environ,
                {"WEEKLY_BRIEF_FORCE": "true", "GITHUB_EVENT_NAME": "workflow_dispatch"},
                clear=False,
            ):
                with patch.object(run_update, "llm_chat", return_value=ai_response()) as manual:
                    _brief, manual_status = run_update.generate_weekly_brief_for_events(
                        [event(i) for i in range(10)], config, now,
                        cache_path=cache, output_path=output, archive_dir=archive,
                    )
            self.assertEqual(manual_status, "generated_ai")
            manual.assert_called_once()

    def test_feature_switch_stops_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, output, archive = self.paths(tmp)
            with patch.dict(run_update.os.environ, {"WEEKLY_BRIEF_ENABLED": "false"}, clear=False):
                with patch.object(run_update, "llm_chat") as chat:
                    brief, status = run_update.generate_weekly_brief_for_events(
                        [event(i) for i in range(10)], ("key", "base", "model"),
                        datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                        cache_path=cache, output_path=output, archive_dir=archive,
                    )
            self.assertIsNone(brief)
            self.assertEqual(status, "disabled")
            chat.assert_not_called()


class WeeklyBriefBuildTests(unittest.TestCase):
    def make_brief(self, events):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache.json"
            output = Path(tmp) / "brief.json"
            brief, _status = generate_weekly_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v4", llm_generate=lambda *_args, **_kwargs: ai_response(),
                cache_path=cache, output_path=output, archive_dir=Path(tmp) / "weekly",
            )
            return brief

    def test_page_teaser_history_and_analytics(self):
        events = [event(i) for i in range(15)]
        brief = self.make_brief(events)
        teaser = build_site.render_weekly_brief_teaser(brief)
        page = build_site.render_weekly_brief_page(
            brief, events, "", archives=[brief],
        )
        self.assertIn('href="weekly.html" data-analytics="weekly_brief"', teaser)
        self.assertIn("WEEKLY BRIEF", teaser)
        self.assertIn("2026-08-03 至 2026-08-09", page)
        self.assertIn('href="weekly/2026-W32.html"', page)
        self.assertEqual(page.count('class="weekly-row"'), 15)
        self.assertIn("本周趋势判断", page)
        self.assertIn("下周继续关注", page)
        for item in brief["items"]:
            self.assertIn(f'href="e/{item["event_id"]}.html"', page)

    def test_archived_page_falls_back_to_original_source(self):
        brief = self.make_brief([event(i) for i in range(10)])
        page = build_site.render_weekly_brief_page(
            brief, [], "", prefix="../", archives=[brief], archive_prefix="",
        )
        self.assertNotIn('href="../e/', page)
        self.assertIn('href="https://example.com/', page)
        self.assertIn("原始信源 ↗", page)
        self.assertIn('href="2026-W32.html"', page)

    def test_empty_teaser_is_compact_and_daily_url_redirects(self):
        teaser = build_site.render_weekly_brief_teaser(None)
        redirect = build_site.render_legacy_daily_redirect()
        self.assertIn('class="weekly-waiting"', teaser)
        self.assertNotIn('class="weekly-teaser"', teaser)
        self.assertNotIn("<h2>", teaser)
        self.assertIn('url=weekly.html', redirect)
        self.assertIn('href="weekly.html"', redirect)

    def test_feature_switch_removes_navigation_entry(self):
        with patch.dict(build_site.os.environ, {"WEEKLY_BRIEF_ENABLED": "false"}, clear=False):
            self.assertNotIn("weekly.html", build_site.sidebar("home"))
            self.assertNotIn("weekly.html", build_site.tabbar("home"))


if __name__ == "__main__":
    unittest.main()
