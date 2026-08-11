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
from daily_brief import (  # noqa: E402
    PROMPT_VERSION, brief_cache_key, brief_input_hash, generate_daily_brief,
    select_daily_events,
)
from llm_usage import LLMBudgetExceeded  # noqa: E402
import run_update  # noqa: E402


def event(number, *, seen="2026-08-11T08:00:00+08:00", category=None, heat=None, summary=None):
    categories = ["agent", "platform", "bi", "product"]
    category = category or categories[number % len(categories)]
    event_id = f"{number:012x}"
    return {
        "event_id": event_id,
        "zh_title": f"事件 {number}",
        "zh_summary": summary if summary is not None else f"摘要 {number}",
        "category": category,
        "category_label": build_site.CAT_LABEL[category],
        "heat": heat if heat is not None else 90 - number,
        "importance": 80 - number,
        "first_seen": seen,
        "published": seen,
        "items": [{"source": f"Source {number}", "link": f"https://example.com/{number}"}],
    }


def ai_response():
    return {
        "headline": "今日数据基础设施变化",
        "overview": "十条高价值动态覆盖平台、Agent、BI 与数据产品。",
        "key_changes": ["平台能力继续整合", "Agent 场景进一步落地"],
    }


class DailyBriefSelectionTests(unittest.TestCase):
    def test_beijing_date_boundary_and_selection_limit(self):
        events = [event(i) for i in range(12)]
        events.append(event(20, seen="2026-08-10T15:59:00+00:00"))  # 08-10 23:59 Beijing
        events.append(event(21, seen="2026-08-10T16:00:00+00:00", heat=99))  # 08-11 00:00 Beijing
        selected = select_daily_events(events, "2026-08-11")
        ids = {item["event_id"] for item in selected}
        self.assertEqual(len(selected), 10)
        self.assertIn(f"{21:012x}", ids)
        self.assertNotIn(f"{20:012x}", ids)
        self.assertEqual({item["category"] for item in selected}, {"agent", "platform", "bi", "product"})

    def test_cache_key_covers_date_input_prompt_and_model(self):
        events = [event(i) for i in range(8)]
        original_hash = brief_input_hash(events)
        changed = [dict(item) for item in events]
        changed[0]["zh_summary"] = "内容发生变化"
        changed_hash = brief_input_hash(changed)
        self.assertNotEqual(original_hash, changed_hash)
        base = brief_cache_key("2026-08-11", original_hash, PROMPT_VERSION, "deepseek-v3")
        self.assertNotEqual(base, brief_cache_key("2026-08-12", original_hash, PROMPT_VERSION, "deepseek-v3"))
        self.assertNotEqual(base, brief_cache_key("2026-08-11", changed_hash, PROMPT_VERSION, "deepseek-v3"))
        self.assertNotEqual(base, brief_cache_key("2026-08-11", original_hash, "daily-brief-v2", "deepseek-v3"))
        self.assertNotEqual(base, brief_cache_key("2026-08-11", original_hash, PROMPT_VERSION, "deepseek-v4"))


class DailyBriefGenerationTests(unittest.TestCase):
    def paths(self, directory):
        return Path(directory) / "cache.json", Path(directory) / "brief.json"

    def test_same_day_is_immutable_and_does_not_call_llm_twice(self):
        calls = []

        def fake(prompt, *, item_id):
            calls.append((prompt, item_id))
            return ai_response()

        with tempfile.TemporaryDirectory() as tmp:
            cache, output = self.paths(tmp)
            events = [event(i) for i in range(10)]
            first, status = generate_daily_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc), model="deepseek-v3",
                llm_generate=fake, cache_path=cache, output_path=output,
            )
            events[0]["zh_summary"] = "同日后续更新改变了输入"
            second, second_status = generate_daily_brief(
                events, now=datetime(2026, 8, 11, 8, tzinfo=timezone.utc), model="deepseek-v3",
                llm_generate=fake, cache_path=cache, output_path=output,
            )
            self.assertEqual(status, "generated_ai")
            self.assertEqual(second_status, "daily_cache_hit")
            self.assertEqual(len(calls), 1)
            self.assertEqual(first["cache_key"], second["cache_key"])
            self.assertEqual(len(first["items"]), 10)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), first)

    def test_unconfigured_failed_and_budget_exhausted_calls_have_rule_fallback(self):
        cases = [
            ("", None, "llm_unconfigured"),
            ("deepseek-v3", lambda *_args, **_kwargs: {}, "invalid_llm_response"),
            ("deepseek-v3", lambda *_args, **_kwargs: (_ for _ in ()).throw(LLMBudgetExceeded("limit")), "LLMBudgetExceeded"),
        ]
        for index, (model, callback, reason) in enumerate(cases):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                cache, output = self.paths(tmp)
                brief, status = generate_daily_brief(
                    [event(i) for i in range(10)],
                    now=datetime(2026, 8, 11, 2 + index, tzinfo=timezone.utc),
                    model=model, llm_generate=callback, cache_path=cache, output_path=output,
                )
                self.assertEqual(status, "generated_rule")
                self.assertFalse(brief["ai_assisted"])
                self.assertEqual(brief["fallback_reason"], reason)
                self.assertEqual(len(brief["items"]), 10)

    def test_fewer_than_eight_items_waits_without_call_or_cache(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            cache, output = self.paths(tmp)
            brief, status = generate_daily_brief(
                [event(i) for i in range(7)], now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc),
                model="deepseek-v3", llm_generate=lambda *args, **kwargs: calls.append(args),
                cache_path=cache, output_path=output,
            )
            self.assertIsNone(brief)
            self.assertEqual(status, "insufficient_items")
            self.assertFalse(calls)
            self.assertFalse(cache.exists())
            self.assertFalse(output.exists())

    def test_run_update_marks_daily_brief_usage_purpose(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, output = self.paths(tmp)
            with patch.object(run_update, "llm_chat", return_value=ai_response()) as chat:
                brief, status = run_update.generate_daily_brief_for_events(
                    [event(i) for i in range(10)], ("key", "https://example.test", "deepseek-v3"),
                    datetime(2026, 8, 11, 2, tzinfo=timezone.utc), cache_path=cache, output_path=output,
                )
            self.assertEqual(status, "generated_ai")
            self.assertTrue(brief["ai_assisted"])
            self.assertEqual(chat.call_args.kwargs["purpose"], "daily_brief")
            self.assertEqual(chat.call_args.kwargs["source"], "daily_brief")
            self.assertEqual(chat.call_args.kwargs["item_id"], "2026-08-11")

    def test_feature_switch_stops_generation_without_calling_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, output = self.paths(tmp)
            with patch.dict(run_update.os.environ, {"DAILY_BRIEF_ENABLED": "false"}, clear=False):
                with patch.object(run_update, "llm_chat") as chat:
                    brief, status = run_update.generate_daily_brief_for_events(
                        [event(i) for i in range(10)], ("key", "https://example.test", "deepseek-v3"),
                        datetime(2026, 8, 11, 2, tzinfo=timezone.utc), cache_path=cache, output_path=output,
                    )
            self.assertIsNone(brief)
            self.assertEqual(status, "disabled")
            chat.assert_not_called()
            self.assertFalse(cache.exists())

    def test_force_flag_is_ignored_for_schedule_and_allowed_for_manual_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, output = self.paths(tmp)
            config = ("key", "https://example.test", "deepseek-v3")
            now = datetime(2026, 8, 11, 2, tzinfo=timezone.utc)
            with patch.dict(run_update.os.environ, {"DAILY_BRIEF_FORCE": "true", "GITHUB_EVENT_NAME": "schedule"}, clear=False):
                with patch.object(run_update, "llm_chat", return_value=ai_response()) as chat:
                    run_update.generate_daily_brief_for_events(
                        [event(i) for i in range(10)], config, now, cache_path=cache, output_path=output,
                    )
                    _brief, status = run_update.generate_daily_brief_for_events(
                        [event(i) for i in range(10)], config, now, cache_path=cache, output_path=output,
                    )
            self.assertEqual(status, "daily_cache_hit")
            self.assertEqual(chat.call_count, 1)
            with patch.dict(run_update.os.environ, {"DAILY_BRIEF_FORCE": "true", "GITHUB_EVENT_NAME": "workflow_dispatch"}, clear=False):
                with patch.object(run_update, "llm_chat", return_value=ai_response()) as manual_chat:
                    _brief, manual_status = run_update.generate_daily_brief_for_events(
                        [event(i) for i in range(10)], config, now, cache_path=cache, output_path=output,
                    )
            self.assertEqual(manual_status, "generated_ai")
            manual_chat.assert_called_once()


class DailyBriefBuildTests(unittest.TestCase):
    def test_page_and_home_entry_show_links_timestamp_ai_label_and_analytics(self):
        events = [event(i) for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            cache, output = Path(tmp) / "cache.json", Path(tmp) / "brief.json"
            brief, _status = generate_daily_brief(
                events, now=datetime(2026, 8, 11, 2, tzinfo=timezone.utc), model="deepseek-v3",
                llm_generate=lambda *_args, **_kwargs: ai_response(), cache_path=cache, output_path=output,
            )
        teaser = build_site.render_daily_brief_teaser(brief)
        page = build_site.render_daily_brief_page(brief, events, "")
        self.assertIn('href="daily.html" data-analytics="daily_brief"', teaser)
        self.assertIn("AI 整理", teaser)
        self.assertIn("2026-08-11 10:00", page)
        self.assertEqual(page.count('class="daily-row"'), 10)
        for item in brief["items"]:
            self.assertIn(f'href="e/{item["event_id"]}.html"', page)
        self.assertIn('data-analytics-list="1"', page)

    def test_feature_switch_removes_navigation_entry(self):
        with patch.dict(build_site.os.environ, {"DAILY_BRIEF_ENABLED": "false"}, clear=False):
            self.assertNotIn("daily.html", build_site.sidebar("home"))
            self.assertNotIn("daily.html", build_site.tabbar("home"))


if __name__ == "__main__":
    unittest.main()
