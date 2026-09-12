import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build_site
import run_update
from import_manual_batch import import_batch, import_registered_batches, stable_id

BATCH = ROOT / "pipeline/manual_batches/2026-09-12-x-review-picks.json"


class ReviewPublicationTests(unittest.TestCase):
    def test_registry_replay_imports_only_approved_records_and_is_idempotent(self):
        records = json.loads(BATCH.read_text())["items"]
        pick = {"source_batch": BATCH.name, "event_id": stable_id(records[0]["source_url"])}
        with tempfile.TemporaryDirectory() as temp:
            latest = Path(temp) / "latest.json"
            latest.write_text(json.dumps({"events": [], "generated_at": ""}))
            with patch("import_manual_batch.load_editorial_picks", return_value=[pick]):
                report = import_registered_batches(latest)
                self.assertEqual(report[0]["added"], 1)
                self.assertEqual(report[0]["records"], 1)
                self.assertEqual(import_registered_batches(latest)[0]["unchanged"], 1)
            imported = json.loads(latest.read_text())["events"]
            self.assertEqual([e["event_id"] for e in imported], [pick["event_id"]])

    def test_reviewed_batch_preserves_provenance_dates_and_reader_labels(self):
        records = json.loads(BATCH.read_text())["items"]
        with tempfile.TemporaryDirectory() as temp:
            latest = Path(temp) / "latest.json"
            latest.write_text(json.dumps({"events": [], "generated_at": ""}))
            self.assertEqual(import_batch(BATCH, latest)["added"], 20)
            first = latest.read_bytes()
            self.assertEqual(import_batch(BATCH, latest)["unchanged"], 20)
            self.assertEqual(first, latest.read_bytes())
            events = {e["event_id"]: e for e in json.loads(first)["events"]}
        self.assertEqual(sum(bool(r.get("discovery_url")) for r in records), 8)
        for record in records:
            event = events[stable_id(record["source_url"])]
            self.assertTrue(event["editorial_pick"])
            self.assertEqual(event["shelf"], "evergreen")
            self.assertEqual(event["items"][0]["link"], record["source_url"])
            page = build_site.render_detail(event, list(events.values()), "")
            self.assertIn('class="meta-content-mode">编辑导读</span>', page)
            self.assertIn(record["source_date_label"], page)
            self.assertIn(record["source_url"], page)
            self.assertNotIn('class="meta-content-mode">历史编译稿</span>', page)
            if not record.get("published"):
                self.assertNotIn('"datePublished"', page)
                self.assertIn(record["source_date_label"], build_site.card_time(event))
            if record.get("discovery_url"):
                self.assertIn(record["discovery_url"], page)
                self.assertEqual(event["discovery_source"], "X")
                self.assertNotIn("X·@", page)
            else:
                self.assertNotIn("discovery_source", event)

    def test_approved_excerpt_does_not_trigger_automatic_fetch_or_translation(self):
        now = datetime(2026, 9, 12, tzinfo=timezone.utc)
        event = {
            "event_id": "reviewed1234", "content_mode": "editorial_excerpt",
            "full_zh": "已批准的阅读提示", "published": "", "first_seen": now.isoformat(),
            "shelf": "evergreen", "items": [{"link": "https://example.com/source"}],
        }
        with patch.dict("os.environ", {"CONTENT_BACKFILL_EVENT_IDS": ""}), \
                patch.object(run_update, "fetch_article_content") as fetch, \
                patch.object(run_update, "llm_chat_text") as llm_call:
            report = run_update.backfill_structured_content([event], {}, now=now)
        self.assertEqual(report["eligible"], 0)
        fetch.assert_not_called()
        llm_call.assert_not_called()
        self.assertEqual(event["full_zh"], "已批准的阅读提示")
