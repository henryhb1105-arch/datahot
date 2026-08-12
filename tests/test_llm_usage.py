import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from llm_usage import LLMBudgetExceeded, LLMUsageTracker  # noqa: E402
import run_update  # noqa: E402


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 11, 10, 30, tzinfo=TZ)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class LLMUsageTrackerTests(unittest.TestCase):
    def make_tracker(self, directory, **env):
        return LLMUsageTracker(
            Path(directory) / "usage.json",
            environ=env,
            now_fn=lambda: NOW,
        )

    def test_persists_metadata_and_actions_summary_without_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.md"
            tracker = self.make_tracker(
                tmp,
                GITHUB_RUN_ID="42",
                GITHUB_RUN_ATTEMPT="2",
                GITHUB_STEP_SUMMARY=str(summary),
            )
            reservation = tracker.before_call("enrich", "item-1", estimated_tokens=100)
            tracker.record(
                model="deepseek-test",
                purpose="enrich",
                source="Example Feed",
                item_id="item-1",
                prompt_chars=123,
                response_chars=45,
                usage={"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42},
                reserved_tokens=reservation,
            )
            tracker.record(
                model="deepseek-test",
                purpose="cluster",
                source="event-cluster",
                item_id="pair-1",
                prompt_chars=20,
                success=False,
                error_type="TimeoutError",
                reserved_tokens=10,
            )

            tracker.finalize()
            data = json.loads((Path(tmp) / "usage.json").read_text(encoding="utf-8"))
            run = data["runs"][0]

            self.assertEqual(run["run_id"], "github-42-2")
            self.assertEqual(run["calls"], 2)
            self.assertEqual(run["failures"], 1)
            self.assertEqual(run["total_tokens"], 42)
            self.assertGreater(run["accounted_tokens"], 42)
            self.assertEqual(run["by_purpose"]["enrich"]["total_tokens"], 42)
            self.assertEqual(run["by_source"]["Example Feed"]["calls"], 1)
            serialized = json.dumps(data, ensure_ascii=False)
            self.assertNotIn("secret prompt", serialized)
            self.assertNotIn("secret response", serialized)
            self.assertIn("DeepSeek usage", summary.read_text(encoding="utf-8"))

    def test_concurrent_reservations_prevent_run_budget_overshoot(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = self.make_tracker(tmp, MAX_LLM_TOKENS_PER_RUN="100")
            first = tracker.before_call("enrich", "a", estimated_tokens=70)
            with self.assertRaises(LLMBudgetExceeded):
                tracker.before_call("enrich", "b", estimated_tokens=40)
            tracker.record(
                model="m", purpose="enrich", item_id="a",
                usage={"total_tokens": 50}, reserved_tokens=first,
            )
            second = tracker.before_call("enrich", "b", estimated_tokens=40)
            self.assertEqual(second, 40)

    def test_daily_budget_uses_persisted_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.json"
            path.write_text(json.dumps({
                "daily": {
                    NOW.date().isoformat(): {"total_tokens": 90}
                }
            }), encoding="utf-8")
            tracker = self.make_tracker(tmp, MAX_LLM_TOKENS_PER_DAY="100")
            with self.assertRaises(LLMBudgetExceeded):
                tracker.before_call("enrich", "a", estimated_tokens=11)

    def test_budget_preflight_is_read_only_and_reports_both_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.json"
            path.write_text(json.dumps({
                "daily": {NOW.date().isoformat(): {"accounted_tokens": 60}}
            }), encoding="utf-8")
            tracker = self.make_tracker(
                tmp, MAX_LLM_TOKENS_PER_RUN="50", MAX_LLM_TOKENS_PER_DAY="100",
            )
            status = tracker.budget_status(estimated_tokens=45)
            self.assertEqual(status["run_remaining"], 50)
            self.assertEqual(status["daily_remaining"], 40)
            self.assertEqual(status["available_tokens"], 40)
            self.assertFalse(status["available"])
            self.assertFalse(tracker.can_call(45))
            self.assertEqual(tracker.skipped["budget"], 0)
            self.assertEqual(tracker.snapshot()["calls"], 0)

    def test_compile_limit_counts_unique_events_not_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = self.make_tracker(tmp, MAX_COMPILE_EVENTS_PER_RUN="1")
            tracker.before_call("compile", "article-a")
            tracker.before_call("compile", "article-a")
            with self.assertRaises(LLMBudgetExceeded):
                tracker.before_call("compile", "article-b")
            self.assertEqual(tracker.skipped["compile_limit"], 1)


class LLMCallInstrumentationTests(unittest.TestCase):
    def setUp(self):
        self.original_tracker = run_update.LLM_USAGE
        self.tmp = tempfile.TemporaryDirectory()
        run_update.LLM_USAGE = LLMUsageTracker(
            Path(self.tmp.name) / "usage.json",
            environ={},
            now_fn=lambda: NOW,
        )

    def tearDown(self):
        run_update.LLM_USAGE = self.original_tracker
        self.tmp.cleanup()

    def test_json_call_records_provider_usage(self):
        payload = {
            "choices": [{"message": {"content": '{"relevant": true}'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        }
        with patch.object(run_update.urllib.request, "urlopen", return_value=FakeResponse(payload)):
            result = run_update.llm_chat(
                "https://example.test", "key", "model", "secret prompt",
                purpose="enrich", source="Feed A", item_id="item-1",
            )
        self.assertTrue(result["relevant"])
        snap = run_update.LLM_USAGE.snapshot()
        self.assertEqual(snap["total_tokens"], 25)
        self.assertEqual(snap["by_purpose"]["enrich"]["calls"], 1)
        self.assertNotIn("secret prompt", json.dumps(snap))

    def test_strict_json_call_uses_provider_json_mode_without_thinking(self):
        provider_payload = {
            "choices": [{"message": {"content": '{"signals": []}'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        }
        captured = {}

        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data))
            return FakeResponse(provider_payload)

        with patch.object(run_update.urllib.request, "urlopen", side_effect=fake_urlopen):
            result = run_update.llm_chat(
                "https://api.deepseek.com", "key", "deepseek-v4-flash", "JSON only",
                strict_object=True, purpose="weekly_brief", item_id="2026-W32:signals",
            )

        self.assertEqual(result, {"signals": []})
        self.assertEqual(captured["response_format"], {"type": "json_object"})
        self.assertEqual(captured["thinking"], {"type": "disabled"})

    def test_failed_call_is_recorded_separately(self):
        with patch.object(run_update.urllib.request, "urlopen", side_effect=TimeoutError("slow")):
            with self.assertRaises(TimeoutError):
                run_update.llm_chat_text(
                    "https://example.test", "key", "model", "secret response",
                    purpose="compile", source="Feed B", item_id="item-2",
                )
        call = run_update.LLM_USAGE.snapshot()["calls_detail"][0]
        self.assertFalse(call["success"])
        self.assertEqual(call["error_type"], "TimeoutError")
        self.assertFalse(call["usage_reported"])
        self.assertEqual(call["total_tokens"], 0)
        self.assertGreater(call["accounted_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
