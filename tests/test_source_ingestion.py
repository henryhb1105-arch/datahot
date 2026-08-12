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
EXPECTED_PEOPLE_AI_SOURCES = {
    "Anthropic Economic Index",
    "Indeed Hiring Lab",
    "Josh Bersin",
    "AIHR",
    "Handshake Network Trends",
}
EXPECTED_PEOPLE_AI_WAVE2_SOURCES = {
    "SHRM Research",
    "Mercer Insights",
    "ADP Research",
    "Workday Newsroom",
    "Microsoft WorkLab",
    "Lightcast Research",
}


class OfficialFeedParsingTests(unittest.TestCase):
    def test_parse_date_normalizes_date_only_values_to_utc(self):
        parsed = run_update.parse_date("2026-08-12")
        self.assertEqual(parsed.tzinfo, run_update.timezone.utc)
        self.assertEqual(parsed.isoformat(), "2026-08-12T00:00:00+00:00")

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

    def test_rss_full_content_html_is_preserved_for_structured_detail_body(self):
        rss = ET.fromstring("""
            <rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item>
              <title>中文完整文章</title>
              <link>https://example.com/full</link>
              <description>只有摘要</description>
              <content:encoded><![CDATA[
                <article><h2>第一部分</h2><p>这是 RSS 中的完整中文正文。</p>
                <table><tr><th>指标</th><td>123</td></tr></table>
                <figure><img src="https://example.com/chart.png" alt="趋势图"
                  width="900" height="500"><figcaption>完整图表</figcaption></figure>
                </article>
              ]]></content:encoded>
            </item></channel></rss>
        """)
        parsed = run_update.parse_feed(rss, {})[0]
        self.assertIn("<table>", parsed["feed_content_html"])
        self.assertIn("完整中文正文", parsed["summary"])

    def test_full_rss_body_can_replace_a_less_complete_web_page(self):
        page_html = '<article><p>' + "网页短正文。" * 70 + '</p></article>'
        page_blocks, page_report = run_update.parse_html_blocks_with_report(
            page_html, "https://example.com/full",
        )
        page_text = run_update.blocks_plain_text(page_blocks)
        feed_html = (
            '<article><h2>完整章节</h2><p>' + "RSS 完整正文与事实。" * 100
            + '</p><table><tr><th>指标</th><td>123</td></tr></table></article>'
        )
        text, blocks, report = run_update.prefer_rss_article_content(
            page_text, page_blocks, page_report, feed_html, "https://example.com/full",
        )
        self.assertTrue(report["strategy"].startswith("rss_"))
        self.assertIn("RSS 完整正文", text)
        self.assertIn("table", [block["type"] for block in blocks])

    def test_atom_xhtml_content_keeps_structural_tags(self):
        atom = ET.fromstring("""
          <feed xmlns="http://www.w3.org/2005/Atom"><entry>
            <title>Atom full article</title>
            <link href="https://example.com/atom-full" />
            <updated>2026-08-12T08:00:00Z</updated>
            <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">
              <p>Full Atom paragraph.</p>
              <table><tr><th>Metric</th><td>42</td></tr></table>
            </div></content>
          </entry></feed>
        """)
        rich = run_update.parse_feed(atom, {})[0]["feed_content_html"]
        blocks = run_update.parse_html_blocks_with_report(
            rich, "https://example.com/atom-full",
        )[0]
        self.assertIn("table", [block["type"] for block in blocks])

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

    def test_handshake_html_list_keeps_both_network_trends_paths(self):
        source = {
            "url": "https://joinhandshake.com/research/",
            "base": "https://joinhandshake.com",
            "link_re": r"(/(?:(?:blog/)?network-trends|research/economic-research)/[a-z0-9-]+/)",
        }
        page = b'''<a class="report-card" href="/blog/network-trends/ai-workforce/"><img alt="cover"></a>
        <a class="report-card" href="/blog/network-trends/ai-workforce/"><h3>AI workforce report</h3></a>
        <a href="/network-trends/gen-z-hiring/"><span>Gen Z hiring trends</span></a>
        <a href="/research/economic-research/ai-job-outlook/"><span>AI job outlook</span></a>
        <a href="/blog/employers/promo/">Promotion</a>'''
        with patch.object(run_update, "fetch_url", return_value=page):
            entries = run_update.fetch_html_list(source)
        self.assertEqual(
            [entry["link"] for entry in entries],
            [
                "https://joinhandshake.com/blog/network-trends/ai-workforce/",
                "https://joinhandshake.com/network-trends/gen-z-hiring/",
                "https://joinhandshake.com/research/economic-research/ai-job-outlook/",
            ],
        )


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
        self.assertTrue(EXPECTED_PEOPLE_AI_SOURCES.issubset(self.by_name))
        for name in EXPECTED_PEOPLE_AI_SOURCES:
            self.assertTrue(self.by_name[name]["enabled"])
        self.assertTrue(EXPECTED_PEOPLE_AI_WAVE2_SOURCES.issubset(self.by_name))
        for name in EXPECTED_PEOPLE_AI_WAVE2_SOURCES:
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

    def test_official_media_cdns_are_source_bound(self):
        expected = {
            "爱分析": "ifenxi-csp.oss-cn-beijing.aliyuncs.com",
            "Claude 官方博客": "cdn.prod.website-files.com",
            "AWS Big Data Blog": "d2908q01vomqb2.cloudfront.net",
            "Fivetran Blog": "cdn.prod.website-files.com",
            "Visier Blog": "images.ctfassets.net",
            "InfoQ 中文": "static001.geekbang.org",
        }
        for source_name, host in expected.items():
            source = self.by_name[source_name]
            self.assertIn(host, source["media_hosts"])
            self.assertEqual(source["media_referer"], "article")
            self.assertTrue(all("/" not in item and ":" not in item for item in source["media_hosts"]))
        self.assertNotIn("media_hosts", self.by_name["人人都是产品经理"])

    def test_visier_uses_bounded_official_rss_for_insight_candidates(self):
        source = self.by_name["Visier Blog"]
        self.assertEqual(source["url"], "https://www.visier.com/blog/rss.xml")
        self.assertEqual(source["fetch_interval_hours"], 24)
        self.assertEqual(source["max_candidates_per_run"], 4)
        self.assertIn("insight", source["focus_categories"])
        self.assertIn("agent", source["focus_categories"])
        self.assertIn("bi", source["focus_categories"])
        self.assertEqual(source["tier"], "low_precision")
        self.assertTrue(source["require_published"])

    def test_people_ai_sources_are_bounded_and_editorially_reviewed(self):
        for name in EXPECTED_PEOPLE_AI_SOURCES:
            source = self.by_name[name]
            self.assertEqual(source["tier"], "low_precision")
            self.assertEqual(source["fetch_interval_hours"], 24)
            self.assertLessEqual(source["max_candidates_per_run"], 4)
            self.assertTrue(source["include_keywords"])
            self.assertIn("insight", source["focus_categories"])
            self.assertTrue(source.get("homepage", "").startswith("https://"))

    def test_broad_sources_keep_existing_data_topics_and_people_ai_terms(self):
        for name in ("OpenAI News", "Claude 官方博客"):
            terms = {str(term).casefold() for term in self.by_name[name]["include_keywords"]}
            self.assertIn("agent", terms)
            self.assertTrue({"data", "analytics"}.issubset(terms))
            self.assertTrue({"workforce", "skills", "talent"}.issubset(terms))

    def test_new_sources_can_route_beyond_their_audit_focus(self):
        josh = self.by_name["Josh Bersin"]
        now = run_update.datetime.now(run_update.timezone.utc)
        entries = [
            {"title": "Multi-Agent AI for talent acquisition", "summary": "", "link": "https://example.com/agent", "published": now},
            {"title": "People analytics reveals a pay equity gap", "summary": "", "link": "https://example.com/insight", "published": now},
        ]
        kept, _stats = run_update.prefilter_entries(entries, josh, now)
        self.assertEqual(len(kept), 2)
        self.assertIn("agent", josh["focus_categories"])

    def test_people_ai_wave2_uses_controlled_recent_windows(self):
        research_sitemaps = {
            "SHRM Research", "Mercer Insights", "Microsoft WorkLab", "Lightcast Research",
        }
        research_feeds = {"ADP Research", "Workday Newsroom"}
        for name in EXPECTED_PEOPLE_AI_WAVE2_SOURCES:
            source = self.by_name[name]
            self.assertEqual(source["tier"], "low_precision")
            self.assertTrue(source["require_published"])
            self.assertLessEqual(source["max_candidates_per_run"], 2)
            self.assertTrue(source["include_keywords"])
            self.assertTrue(source.get("homepage", "").startswith("https://"))
            self.assertIn("insight", source["focus_categories"])
        for name in research_sitemaps:
            source = self.by_name[name]
            self.assertEqual(source["kind"], "sitemap")
            self.assertEqual(source["fetch_interval_hours"], 48)
            self.assertEqual(source["lookback_days"], 180)
            self.assertTrue(source["path_include"])
        for name in research_feeds:
            source = self.by_name[name]
            self.assertNotIn("kind", source)
            self.assertEqual(source["fetch_interval_hours"], 24)
            self.assertEqual(source["lookback_days"], 120)

    def test_people_ai_wave2_filters_keep_research_and_drop_corporate_noise(self):
        now = run_update.datetime.now(run_update.timezone.utc)
        fixtures = {
            "SHRM Research": (
                "SHRM research finds AI changes workforce skills",
                "https://www.shrm.org/topics-tools/research/ai-workforce-skills",
            ),
            "Mercer Insights": (
                "AI workforce analytics reshapes organization design",
                "https://www.mercer.com/insights/talent-and-transformation/ai-workforce/",
            ),
            "ADP Research": (
                "ADP National Employment Report shows annual pay growth",
                "https://mediacenter.adp.com/employment-report-pay-growth",
            ),
            "Workday Newsroom": (
                "Workday research finds AI eases employee burnout",
                "https://newsroom.workday.com/ai-workforce-research",
            ),
            "Microsoft WorkLab": (
                "Work Trend Index shows human agent teams reshape the workforce",
                "https://www.microsoft.com/en-us/worklab/work-trend-index/human-agent-teams",
            ),
            "Lightcast Research": (
                "AI skills employers need across the workforce",
                "https://lightcast.io/resources/research/ai-skills-employers-need",
            ),
        }
        for name, (title, link) in fixtures.items():
            kept, _stats = run_update.prefilter_entries(
                [{"title": title, "summary": "", "link": link, "published": now}],
                self.by_name[name],
                now,
            )
            self.assertEqual(len(kept), 1, name)

        for name in ("ADP Research", "Workday Newsroom"):
            kept, stats = run_update.prefilter_entries(
                [{
                    "title": "AI quarterly financial results and investor earnings",
                    "summary": "",
                    "link": "https://example.com/financial-results",
                    "published": now,
                }],
                self.by_name[name],
                now,
            )
            self.assertEqual(kept, [], name)
            self.assertEqual(stats["dropped"]["excluded"], 1, name)


if __name__ == "__main__":
    unittest.main()
