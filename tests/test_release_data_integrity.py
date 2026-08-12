import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "site" / "data" / "latest.json"
DETAILS = ROOT / "site" / "e"


class ReleaseDataIntegrityTests(unittest.TestCase):
    """Keep known public reference pages in source data and generated output."""

    PROTECTED_EVENT_IDS = {"65c35101abc1", "dfb9071b69e0"}

    def test_protected_events_remain_in_latest_data(self):
        payload = json.loads(LATEST.read_text(encoding="utf-8"))
        event_ids = {event.get("event_id") for event in payload.get("events", [])}
        self.assertEqual(self.PROTECTED_EVENT_IDS - event_ids, set())

    def test_protected_detail_pages_remain_generated(self):
        missing = {
            event_id
            for event_id in self.PROTECTED_EVENT_IDS
            if not (DETAILS / f"{event_id}.html").is_file()
        }
        self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()
