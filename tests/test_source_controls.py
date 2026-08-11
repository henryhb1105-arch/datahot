import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from source_controls import (  # noqa: E402
    accepted_categories_by_source,
    prefilter_entries,
    source_candidate_limit,
    source_control_snapshot,
    source_due,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 11, 4, 0, tzinfo=UTC)


class SourceSchedulingTests(unittest.TestCase):
    def test_never_fetched_source_is_due(self):
        due, reason = source_due({"fetch_interval_hours": 24}, {}, NOW, environ={})
        self.assertTrue(due)
        self.assertEqual(reason, "never_fetched")

    def test_source_waits_for_its_own_interval(self):
        source = {"fetch_interval_hours": 24}
        state = {"last_attempt": (NOW - timedelta(hours=6)).isoformat()}
        due, reason = source_due(source, state, NOW, environ={})
        self.assertFalse(due)
        self.assertIn("frequency_gate", reason)
        due, reason = source_due(source, state, NOW + timedelta(hours=18), environ={})
        self.assertTrue(due)
        self.assertEqual(reason, "interval_elapsed")

    def test_force_fetch_is_reversible_environment_override(self):
        due, reason = source_due(
            {"fetch_interval_hours": 24},
            {"last_attempt": NOW.isoformat()},
            NOW,
            environ={"FORCE_SOURCE_FETCH": "true"},
        )
        self.assertTrue(due)
        self.assertEqual(reason, "forced")

    def test_each_source_limit_and_defaults_are_independent(self):
        self.assertEqual(source_candidate_limit({"max_candidates_per_run": 4}), 4)
        self.assertEqual(source_candidate_limit({}), 20)
        snapshot = source_control_snapshot({
            "tier": "media_low", "fetch_interval_hours": 24,
            "focus_categories": ["bi", "product", "invalid"],
        })
        self.assertEqual(snapshot["tier"], "media_low")
        self.assertEqual(snapshot["fetch_interval_hours"], 24)
        self.assertEqual(snapshot["max_candidates_per_run"], 20)
        self.assertEqual(snapshot["focus_categories"], ["bi", "product"])

    def test_final_cluster_category_is_attributed_to_source(self):
        events = [{
            "category": "bi", "items": [
                {"id": "a", "source": "Hex Blog"},
                {"id": "b", "source": "Other"},
            ],
        }, {"category": "product", "items": [{"id": "c", "source": "Hex Blog"}]}]
        self.assertEqual(
            accepted_categories_by_source(events, {"a", "c"}),
            {"Hex Blog": {"bi": 1, "product": 1}},
        )


class SourcePrefilterTests(unittest.TestCase):
    def entry(self, title, days=0, link=None, summary=""):
        return {
            "title": title,
            "summary": summary,
            "link": link or f"https://example.com/blog/{title}",
            "published": NOW - timedelta(days=days) if days is not None else None,
        }

    def test_time_path_keyword_and_exclusion_filters_are_auditable(self):
        entries = [
            self.entry("analytics-agent", days=1),
            self.entry("analytics-old", days=8),
            self.entry("analytics-news", days=1, link="https://example.com/news/x"),
            self.entry("consumer-ai", days=1),
            self.entry("analytics-job", days=1),
            self.entry("analytics-undated", days=None),
        ]
        source = {
            "lookback_days": 3,
            "require_published": True,
            "path_include": "/blog/",
            "include_keywords": ["analytics", "database"],
            "exclude_keywords": ["job"],
        }
        kept, stats = prefilter_entries(entries, source, NOW)
        self.assertEqual([entry["title"] for entry in kept], ["analytics-agent"])
        self.assertEqual(stats["fetched"], 6)
        self.assertEqual(stats["eligible"], 1)
        self.assertEqual(stats["dropped"]["time"], 1)
        self.assertEqual(stats["dropped"]["missing_date"], 1)
        self.assertEqual(stats["dropped"]["path"], 1)
        self.assertEqual(stats["dropped"]["keyword"], 1)
        self.assertEqual(stats["dropped"]["excluded"], 1)

    def test_entries_are_sorted_newest_first_before_unseen_limit(self):
        entries = [
            self.entry("data-old", days=2),
            self.entry("data-new", days=0),
            self.entry("data-mid", days=1),
        ]
        kept, _ = prefilter_entries(entries, {"include_keywords": ["data"]}, NOW)
        self.assertEqual(
            [entry["title"] for entry in kept],
            ["data-new", "data-mid", "data-old"],
        )

    def test_short_ascii_keywords_match_words_not_substrings(self):
        entries = [
            self.entry("mobile phone"),
            self.entry("BI dashboard"),
        ]
        kept, stats = prefilter_entries(entries, {"include_keywords": ["BI"]}, NOW)
        self.assertEqual([entry["title"] for entry in kept], ["BI dashboard"])
        self.assertEqual(stats["dropped"]["keyword"], 1)

    def test_production_tiers_protect_high_precision_sources(self):
        sources = json.loads((ROOT / "pipeline" / "sources.json").read_text(encoding="utf-8"))
        by_name = {source["name"]: source for source in sources}
        for name in ("Snowflake Release Notes", "Databricks Blog", "dbt Blog"):
            source = by_name[name]
            self.assertEqual(source["fetch_interval_hours"], 6)
            self.assertFalse(source.get("include_keywords"))
        claude = by_name["Claude 官方博客"]
        self.assertEqual(claude["fetch_interval_hours"], 24)
        self.assertEqual(claude["max_candidates_per_run"], 8)
        self.assertTrue(claude["require_published"])
        self.assertTrue(claude["include_keywords"])
        for name in ("Hex Blog", "Amplitude Blog", "Netflix Technology Blog"):
            source = by_name[name]
            self.assertLessEqual(source["max_candidates_per_run"], 5)
            self.assertTrue(source["require_published"])
            self.assertTrue(source["include_keywords"])
            self.assertTrue(source["focus_categories"])


if __name__ == "__main__":
    unittest.main()
