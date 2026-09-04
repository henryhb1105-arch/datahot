import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from release_policy import (  # noqa: E402
    PROTECTED_EVENT_IDS,
    event_recency_time,
    should_retain_event,
)
from product_cases import product_case_event_ids  # noqa: E402
from editorial_picks import editorial_pick_event_ids  # noqa: E402


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(days=8)


class ReleasePolicyTests(unittest.TestCase):
    def test_editorial_picks_are_permanently_protected(self):
        pick_ids = editorial_pick_event_ids()
        self.assertEqual(len(pick_ids), 12)
        self.assertTrue(pick_ids.issubset(PROTECTED_EVENT_IDS))
        for event_id in pick_ids:
            self.assertTrue(should_retain_event({
                "event_id": event_id,
                "shelf": "news",
                "published": (NOW - timedelta(days=180)).isoformat(),
                "first_seen": (NOW - timedelta(days=180)).isoformat(),
            }, cutoff=CUTOFF))

    def test_curated_product_cases_are_protected_without_becoming_evergreen(self):
        case_ids = product_case_event_ids()
        self.assertGreaterEqual(len(case_ids), 8)
        self.assertTrue(case_ids.issubset(PROTECTED_EVENT_IDS))
        case_id = next(iter(case_ids))
        self.assertTrue(should_retain_event({
            "event_id": case_id,
            "shelf": "news",
            "published": (NOW - timedelta(days=30)).isoformat(),
            "first_seen": (NOW - timedelta(days=30)).isoformat(),
        }, cutoff=CUTOFF))

    def test_protected_news_survives_after_normal_retention_window(self):
        event_id = next(iter(PROTECTED_EVENT_IDS))
        event = {
            "event_id": event_id,
            "shelf": "news",
            "published": (NOW - timedelta(days=30)).isoformat(),
            "first_seen": (NOW - timedelta(days=30)).isoformat(),
        }
        self.assertTrue(should_retain_event(event, cutoff=CUTOFF))

    def test_recent_publication_keeps_rolling_event_with_older_first_seen(self):
        event = {
            "event_id": "rolling-release-notes",
            "shelf": "news",
            "published": (NOW - timedelta(days=2)).isoformat(),
            "first_seen": (NOW - timedelta(days=20)).isoformat(),
        }
        self.assertEqual(
            event_recency_time(event),
            NOW - timedelta(days=2),
        )
        self.assertTrue(should_retain_event(event, cutoff=CUTOFF))

    def test_recent_discovery_keeps_older_article_for_one_window(self):
        event = {
            "event_id": "recent-discovery",
            "shelf": "news",
            "published": (NOW - timedelta(days=90)).isoformat(),
            "first_seen": (NOW - timedelta(days=1)).isoformat(),
        }
        self.assertTrue(should_retain_event(event, cutoff=CUTOFF))

    def test_expired_unprotected_news_is_removed(self):
        event = {
            "event_id": "expired-news",
            "shelf": "news",
            "published": (NOW - timedelta(days=20)).isoformat(),
            "first_seen": (NOW - timedelta(days=20)).isoformat(),
        }
        self.assertFalse(should_retain_event(event, cutoff=CUTOFF))

    def test_evergreen_and_invalid_timestamp_behavior(self):
        self.assertTrue(should_retain_event(
            {"event_id": "evergreen", "shelf": "evergreen"},
            cutoff=CUTOFF,
        ))
        self.assertFalse(should_retain_event(
            {"event_id": "invalid", "shelf": "news", "published": "not-a-date"},
            cutoff=CUTOFF,
        ))


if __name__ == "__main__":
    unittest.main()
