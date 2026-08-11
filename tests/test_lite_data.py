import json
import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from lite_data import (  # noqa: E402
    build_lite_payload, find_forbidden_fields, rank_home_events,
)


def event(index, *, vendor="Vendor", category="platform", importance=50, heat=45, sources=1):
    event_id = f"{index:012x}"[-12:]
    return {
        "event_id": event_id, "zh_title": f"Event {index}", "zh_summary": "Summary",
        "reason": "Why", "full_zh": "forbidden full body", "content_blocks": [{"type": "p"}],
        "category": category, "category_label": category, "vendors": [vendor], "topics": ["Topic"],
        "heat": heat, "importance": importance, "star": False, "shelf": "news", "pinned": False,
        "published": f"2026-08-{(index % 9) + 1:02d}T12:00:00+08:00",
        "first_seen": f"2026-08-{(index % 9) + 1:02d}T12:{index % 60:02d}:00+08:00",
        "items": [
            {"source": f"Source {n}", "link": "https://example.com", "article_text": "forbidden"}
            for n in range(sources)
        ],
    }


class LitePayloadTests(unittest.TestCase):
    def test_payload_never_contains_article_body_fields(self):
        payload = build_lite_payload([event(1)], "2026-08-11T12:00:00+08:00")
        self.assertEqual(find_forbidden_fields(payload), [])
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("forbidden full body", encoded)
        self.assertNotIn("https://example.com", encoded)

    def test_explicit_empty_home_ranking_does_not_fall_back_to_all_events(self):
        payload = build_lite_payload([event(1)], "2026-08-11T12:00:00+08:00", ranking=[])
        self.assertEqual(payload["home_event_ids"], [])

    def test_first_page_enforces_vendor_cap(self):
        events = [event(i, vendor="Dominant") for i in range(12)]
        events += [event(100 + i, vendor=f"Vendor {i}", category="bi") for i in range(20)]
        ranked = rank_home_events(events, page_size=20, vendor_cap=4)
        counts = Counter((item.get("vendors") or [""])[0] for item in ranked[:20])
        self.assertLessEqual(counts["Dominant"], 4)
        self.assertEqual(len(ranked), len(events))

    def test_sparse_mix_keeps_hard_vendor_cap_even_if_page_is_short(self):
        events = [event(i, vendor="Only Vendor") for i in range(12)]
        first = rank_home_events(events, page_size=20, vendor_cap=4, first_page_only=True)
        self.assertEqual(len(first), 4)

    def test_category_overflow_requires_quality_until_floor_relaxation(self):
        dominant = [event(i, vendor=f"P{i}", category="platform") for i in range(18)]
        balanced = [event(100 + i, vendor=f"B{i}", category="bi") for i in range(10)]
        ranked = rank_home_events(dominant + balanced, page_size=20, category_soft_cap=12)
        first = ranked[:20]
        self.assertLessEqual(Counter(item["category"] for item in first)["platform"], 12)
        self.assertEqual(len(first), 20)

    def test_high_quality_event_can_cross_soft_category_cap(self):
        events = [event(i, vendor=f"V{i}", category="platform") for i in range(16)]
        events[-1]["importance"] = 85
        ranked = rank_home_events(events, page_size=13, category_soft_cap=12, minimum_page_size=0)
        first_ids = {item["event_id"] for item in ranked[:13]}
        self.assertIn(events[-1]["event_id"], first_ids)


if __name__ == "__main__":
    unittest.main()
