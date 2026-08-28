import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import run_update  # noqa: E402


NOW = datetime(2026, 8, 28, 6, 0, tzinfo=timezone.utc)


class ScoringTests(unittest.TestCase):
    def test_quality_breakdown_is_auditable_and_determines_score(self):
        score, breakdown = run_update.normalize_quality_result({
            "quality_score": 99,
            "quality_breakdown": {
                "originality": 20,
                "evidence_density": 19,
                "information_gain": 18,
                "actionability_depth": 17,
            },
        })
        self.assertEqual(score, 74)
        self.assertEqual(sum(breakdown.values()), 74)

    def test_incomplete_quality_breakdown_falls_back_safely(self):
        score, breakdown = run_update.normalize_quality_result({
            "quality_score": 81,
            "quality_breakdown": {"originality": 25},
        })
        self.assertEqual(score, 81)
        self.assertEqual(breakdown, {})

    def test_quality_and_trend_are_independent_but_heat_stays_compatible(self):
        published = NOW
        trend = run_update.calc_trend_score(
            published, signal=100, extra_sources=2, reference_time=NOW,
        )
        low_quality_heat = run_update.calc_heat(
            30, published, signal=100, extra_sources=2, reference_time=NOW,
        )
        high_quality_heat = run_update.calc_heat(
            90, published, signal=100, extra_sources=2, reference_time=NOW,
        )
        self.assertGreaterEqual(trend, 80)
        self.assertGreater(high_quality_heat, low_quality_heat)
        self.assertEqual(
            low_quality_heat,
            round(0.45 * 30 + 0.55 * trend),
        )

    def test_event_recalculation_migrates_legacy_importance(self):
        event = {
            "importance": 76,
            "published": NOW.isoformat(),
            "signal": 0,
            "items": [{"source": "A"}],
        }
        run_update.recalc_event_heat(event, reference_time=NOW)
        self.assertEqual(event["quality_score"], 76)
        self.assertIn("trend_score", event)
        self.assertTrue(event["star"])


if __name__ == "__main__":
    unittest.main()
