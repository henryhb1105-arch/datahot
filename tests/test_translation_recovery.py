import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from recover_translations import recover


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.runtime = SimpleNamespace(
            TZ=timezone.utc,
            LLM_USAGE=SimpleNamespace(can_call=Mock(return_value=True),
                                     snapshot=Mock(return_value={"failures": 0})),
            is_pending_original=lambda e: e.get("enrichment_status") == "pending",
            backfill_event_metadata=Mock(return_value={"complete": 8}),
            backfill_structured_content=Mock(return_value={"translated": 1}),
            repair_content_metadata=Mock(), recalc_event_heat=Mock(),
            rank_hot_events=Mock(return_value=[]),
        )
        self.payload = {"events": [{
            "event_id": str(i), "enrichment_status": "pending",
            "content_mode": "original", "source_language": "other",
            "full_zh": "Retained original", "items": [{"link": "https://example.com"}],
        } for i in range(19)], "sources": [{"name": "existing"}]}

    def run_recovery(self, payload=None):
        return recover(payload or self.payload, self.runtime, ("key", "base", "model"),
                       now=datetime(2026, 11, 11, tzinfo=timezone.utc))

    def test_batches_preserve_inventory_and_input(self):
        original = copy.deepcopy(self.payload)
        result = self.run_recovery()
        self.assertEqual(self.payload, original)
        self.assertEqual(result["events"], original["events"])
        self.assertEqual(result["sources"], original["sources"])
        self.assertEqual([len(c.args[0]) for c in self.runtime.backfill_event_metadata.call_args_list], [8, 8, 3])
        self.assertEqual(self.runtime.backfill_structured_content.call_count, 19)

    def test_budget_exhaustion_calls_no_provider(self):
        self.runtime.LLM_USAGE.can_call.return_value = False
        result = self.run_recovery()
        self.runtime.backfill_event_metadata.assert_not_called()
        self.runtime.backfill_structured_content.assert_not_called()
        self.assertEqual(result["events"], self.payload["events"])

    def test_provider_failure_stops_remaining_work(self):
        self.runtime.backfill_event_metadata.return_value = {"failed": 1}
        self.runtime.LLM_USAGE.snapshot.return_value = {"failures": 1}
        self.run_recovery()
        self.assertEqual(self.runtime.backfill_event_metadata.call_count, 1)
        self.runtime.backfill_structured_content.assert_not_called()

    def test_body_failure_does_not_repeat_or_continue(self):
        self.runtime.backfill_structured_content.return_value = {"failed": 1}
        self.run_recovery()
        self.assertEqual(self.runtime.backfill_structured_content.call_count, 1)

    def test_successful_changes_are_preserved_without_mutating_baseline(self):
        def translate(events, *args, **kwargs):
            for event in events:
                event.update(enrichment_status="complete", zh_title="中文标题")
            return {"complete": len(events)}
        self.runtime.backfill_event_metadata.side_effect = translate
        result = self.run_recovery()
        self.assertTrue(all(e["zh_title"] == "中文标题" for e in result["events"]))
        self.assertTrue(all(e["enrichment_status"] == "pending" for e in self.payload["events"]))

    def test_invalid_metadata_stops_even_without_transport_failure(self):
        self.runtime.backfill_event_metadata.return_value = {"failed": 1}
        self.run_recovery()
        self.runtime.backfill_structured_content.assert_not_called()

    def test_no_retranslation_of_chinese_completed_or_editorial(self):
        events = self.payload["events"][:5]
        events[0]["source_language"] = "zh"
        events[1]["content_mode"] = "translated"
        events[2]["content_mode"] = "editorial_excerpt"
        events[3]["enrichment_status"] = "rejected"
        events[4]["translation_status"] = "complete"
        self.run_recovery({"events": events})
        self.runtime.backfill_structured_content.assert_not_called()

    def test_missing_config_and_duplicate_ids_fail_before_processing(self):
        with self.assertRaises(RuntimeError):
            recover(self.payload, self.runtime, (None, "base", "model"))
        self.payload["events"].append(self.payload["events"][0])
        with self.assertRaises(ValueError):
            self.run_recovery()
        self.runtime.backfill_event_metadata.assert_not_called()


if __name__ == "__main__":
    unittest.main()
