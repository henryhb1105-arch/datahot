import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import run_update  # noqa: E402


EXPECTED_NEW_SOURCES = {
    "Google BigQuery Release Notes",
    "Google Looker Release Notes",
    "Microsoft Fabric Blog",
    "DuckDB Engineering Blog",
    "Apache Iceberg Blog",
    "TiDB Blog",
    "Apache Doris Blog",
    "Visier Blog",
}


class OfficialFeedParsingTests(unittest.TestCase):
    def test_rss_and_atom_are_both_supported(self):
        rss = ET.fromstring("""
            <rss><channel><item>
              <title>BigQuery adds conversational analytics</title>
              <link>https://example.com/bigquery</link>
              <pubDate>Tue, 11 Aug 2026 08:00:00 GMT</pubDate>
              <description>Official product update</description>
            </item></channel></rss>
        """)
        atom = ET.fromstring("""
            <feed xmlns="http://www.w3.org/2005/Atom"><entry>
              <title>DuckDB 1.6 released</title>
              <link rel="alternate" href="https://example.com/duckdb" />
              <updated>2026-08-11T08:00:00Z</updated>
              <summary>Official engineering update</summary>
            </entry></feed>
        """)
        rss_items = run_update.parse_feed(rss, {})
        atom_items = run_update.parse_feed(atom, {})
        self.assertEqual(rss_items[0]["link"], "https://example.com/bigquery")
        self.assertIsNotNone(rss_items[0]["published"])
        self.assertEqual(atom_items[0]["link"], "https://example.com/duckdb")
        self.assertIsNotNone(atom_items[0]["published"])

    def test_sitemap_path_filter_keeps_blog_entries(self):
        sitemap = ET.fromstring("""
          <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://doris.apache.org/blog/vector-search</loc><lastmod>2026-08-10</lastmod></url>
            <url><loc>https://doris.apache.org/docs/sql</loc><lastmod>2026-08-10</lastmod></url>
          </urlset>
        """)
        source = {
            "urls": ["https://doris.apache.org/sitemap.xml"],
            "url_include": "doris.apache.org/blog/",
        }
        with patch.object(run_update, "fetch_feed", return_value=sitemap):
            entries = run_update.fetch_sitemap(source)
        self.assertEqual([entry["title"] for entry in entries], ["vector search"])
        self.assertIsNotNone(entries[0]["published"])


class ProductionSourceConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = json.loads(
            (ROOT / "pipeline" / "sources.json").read_text(encoding="utf-8")
        )
        cls.by_name = {source["name"]: source for source in cls.sources}

    def test_source_names_are_unique_and_expected_sources_are_enabled(self):
        names = [source["name"] for source in self.sources]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(EXPECTED_NEW_SOURCES.issubset(self.by_name))
        for name in EXPECTED_NEW_SOURCES:
            self.assertTrue(self.by_name[name]["enabled"])

    def test_new_sources_have_bounded_controls(self):
        for name in EXPECTED_NEW_SOURCES:
            source = self.by_name[name]
            self.assertLessEqual(source["max_candidates_per_run"], 6)
            self.assertGreaterEqual(source["fetch_interval_hours"], 6)
            self.assertTrue(source["focus_categories"])
            self.assertIn(source.get("kind", "rss"), {"rss", "sitemap"})
            self.assertTrue(source.get("url") or source.get("urls"))

    def test_high_frequency_marketing_sources_are_targeted(self):
        for name in (
            "Google Looker Release Notes",
            "Microsoft Fabric Blog",
            "TiDB Blog",
            "Apache Doris Blog",
        ):
            source = self.by_name[name]
            self.assertTrue(source["include_keywords"])
            self.assertLessEqual(source["max_candidates_per_run"], 5)

    def test_visier_uses_bounded_official_rss_for_insight_candidates(self):
        source = self.by_name["Visier Blog"]
        self.assertEqual(source["url"], "https://www.visier.com/blog/rss.xml")
        self.assertEqual(source["fetch_interval_hours"], 24)
        self.assertEqual(source["max_candidates_per_run"], 4)
        self.assertEqual(source["focus_categories"], ["insight"])
        self.assertTrue(source["require_published"])


if __name__ == "__main__":
    unittest.main()
