import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from run_update import translation_retry_events
import run_update
from datetime import datetime, timezone


class TranslationCutoffTests(unittest.TestCase):
    def test_old_inventory_excluded_but_newly_ingested_old_article_can_retry(self):
        events = [
            {"event_id": "old", "first_seen": "2026-11-11T22:00:00+08:00"},
            {"event_id": "new", "first_seen": "2026-11-12T00:00:00+08:00",
             "published": "2024-01-01T00:00:00Z"},
            {"event_id": "missing", "published": "2026-11-12T00:00:00Z"},
        ]
        with patch.dict(os.environ, {"CONTENT_TRANSLATION_SINCE": "2026-11-11T15:11:35Z"}):
            selected = translation_retry_events(events)
        self.assertEqual([e["event_id"] for e in selected], ["new"])
        self.assertIs(selected[0], events[1])  # Backfill changes persist in the catalog.

    def test_cutoff_boundary_and_timezone(self):
        event = {"first_seen": "2026-11-11T23:11:35+08:00"}
        with patch.dict(os.environ, {"CONTENT_TRANSLATION_SINCE": "2026-11-11T15:11:35Z"}):
            self.assertEqual(translation_retry_events([event]), [event])

    def test_unconfigured_preserves_existing_policy(self):
        events = [{"event_id": "legacy"}]
        with patch.dict(os.environ, {"CONTENT_TRANSLATION_SINCE": ""}):
            self.assertIs(translation_retry_events(events), events)

    def test_invalid_cutoff_fails_closed(self):
        with patch.dict(os.environ, {"CONTENT_TRANSLATION_SINCE": "invalid"}):
            with self.assertRaises(ValueError):
                translation_retry_events([{"event_id": "old"}])

    def test_newly_ingested_old_original_remains_eligible_for_body_retry(self):
        event = {
            "event_id": "late", "first_seen": "2026-11-12T00:00:00+08:00",
            "published": "2024-01-01T00:00:00Z", "content_mode": "original",
            "source_language": "other", "full_zh": "An English original article. " * 30,
            "items": [{"link": "https://example.com/article", "source": "Example"}],
        }
        with patch.dict(os.environ, {"CONTENT_TRANSLATION_SINCE": "2026-11-11T15:11:35Z"}), \
             patch.object(run_update, "fetch_article_content") as fetch:
            report = run_update.backfill_structured_content(
                [event], ("", "", ""), now=datetime(2026, 11, 12, tzinfo=timezone.utc),
            )
        self.assertEqual(report["eligible"], 1)
        self.assertEqual(report["stored_original_retries"], 1)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
