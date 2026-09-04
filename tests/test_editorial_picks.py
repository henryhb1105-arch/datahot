import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from editorial_picks import (  # noqa: E402
    apply_editorial_picks,
    editorial_pick_event_ids,
    load_editorial_picks,
)
from import_manual_batch import norm_url, stable_id  # noqa: E402


EXPECTED_IDS = {
    "477745cf963d", "44517f2e6a68", "87c9acba5c38", "e7420873acde",
    "2a6cb6153284", "74499ad15c94", "7dc53089a3b8", "7e23299ee03d",
    "9653f52649c8", "9e059ac6ed28", "875c99b3755b", "8f1d134628cf",
}


class EditorialPickTests(unittest.TestCase):
    def test_registry_contains_every_historical_x_selection_with_stable_identity(self):
        items = load_editorial_picks()
        self.assertEqual(len(items), 12)
        self.assertEqual(editorial_pick_event_ids(), EXPECTED_IDS)
        self.assertEqual(
            {stable_id(item["source_url"]) for item in items}, EXPECTED_IDS,
        )
        self.assertEqual(len({norm_url(item["source_url"]) for item in items}), 12)
        self.assertEqual(len({norm_url(item["discovery_url"]) for item in items}), 12)

    def test_registry_matches_x_discovered_records_in_the_reviewed_batches(self):
        batch_names = {
            "2026-08-12-x-first.json",
            "2026-08-12-hr-ai-insights.json",
            "2026-09-04-jason-cui-data-agent-context.json",
        }
        expected = {}
        for batch_name in batch_names:
            batch = json.loads((
                ROOT / "pipeline" / "manual_batches" / batch_name
            ).read_text(encoding="utf-8"))
            for record in batch["items"]:
                if record.get("discovery_url"):
                    expected[stable_id(record["source_url"])] = {
                        "curated_at": batch["ingested_at"],
                        "source_url": norm_url(record["source_url"]),
                        "discovery_url": norm_url(record["discovery_url"]),
                    }
        actual = {
            item["event_id"]: {
                "curated_at": item["curated_at"],
                "source_url": norm_url(item["source_url"]),
                "discovery_url": norm_url(item["discovery_url"]),
            }
            for item in load_editorial_picks()
        }
        self.assertEqual(actual, expected)

    def test_application_adds_selection_metadata_without_replacing_primary_source(self):
        event = {
            "event_id": "8f1d134628cf",
            "items": [{"source": "a16z", "link": "https://a16z.com/your-data-agents-need-context/"}],
        }
        untouched = {"event_id": "000000000000", "items": [{"source": "Official"}]}
        self.assertEqual(apply_editorial_picks([event, untouched]), 1)
        self.assertTrue(event["editorial_pick"])
        self.assertEqual(event["curated_at"], "2026-09-04T09:55:00+08:00")
        self.assertEqual(event["items"][0]["source"], "a16z")
        self.assertNotIn("editorial_pick", untouched)

    def test_registry_rejects_duplicate_event_ids(self):
        item = dict(load_editorial_picks()[0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "picks.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "items": [item, dict(item)],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate editorial pick event_id"):
                load_editorial_picks(path)


if __name__ == "__main__":
    unittest.main()
