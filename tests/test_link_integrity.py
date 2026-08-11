import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from check_links import check_site_links, format_broken_links  # noqa: E402
import build_site  # noqa: E402


def event(event_id, *, evergreen=False, published="2026-08-11T12:00:00+08:00"):
    return {
        "event_id": event_id, "zh_title": f"Event {event_id}", "zh_summary": "Summary",
        "reason": "", "full_zh": "Body", "category": "platform",
        "category_label": "AI 数据平台", "vendors": [], "topics": [],
        "heat": 50, "importance": 50, "signal": 0,
        "shelf": "evergreen" if evergreen else "news", "pinned": evergreen,
        "published": published, "first_seen": published,
        "items": [{
            "id": "source-" + event_id, "source": "Databricks Blog",
            "link": "https://example.com/" + event_id,
            "published": published, "title": "Source",
        }],
    }


class LinkCheckerTests(unittest.TestCase):
    def test_fixture_covers_root_topic_classics_detail_and_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            (site / "topics").mkdir()
            (site / "e").mkdir()
            (site / "media" / "old-event").mkdir(parents=True)
            (site / "icons").mkdir()
            (site / "favicon.ico").write_bytes(b"ico")
            (site / "icons" / "apple-touch-icon.png").write_bytes(b"png")
            (site / "media" / "old-event" / "chart.png").write_bytes(b"png")
            (site / "index.html").write_text(
                '<a href="topics.html">Topics</a><a href="classics.html">Classics</a>',
                encoding="utf-8",
            )
            (site / "topics.html").write_text('<a href="topics/data.html">Data</a>', encoding="utf-8")
            (site / "classics.html").write_text('<a href="e/old-event.html">Old</a>', encoding="utf-8")
            (site / "topics" / "data.html").write_text(
                '<a href="../index.html">Home</a><a href="../e/old-event.html">Old</a>',
                encoding="utf-8",
            )
            (site / "e" / "old-event.html").write_text(
                '<link href="../favicon.ico"><a href="../classics.html#old">Back</a>'
                '<img src="../media/old-event/chart.png"><a href="https://example.com">External</a>',
                encoding="utf-8",
            )
            self.assertEqual(check_site_links(site), [])

    def test_broken_report_names_source_line_and_target(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            (site / "index.html").write_text('\n<a href="e/missing.html">Missing</a>', encoding="utf-8")
            broken = check_site_links(site)
            self.assertEqual(len(broken), 1)
            report = format_broken_links(broken, site)
            self.assertIn("index.html:2", report)
            self.assertIn("e/missing.html", report)

    def test_checker_is_case_sensitive_even_on_case_insensitive_filesystems(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            (site / "Target.html").write_text("ok", encoding="utf-8")
            (site / "index.html").write_text('<a href="target.html">Wrong case</a>', encoding="utf-8")
            self.assertEqual(len(check_site_links(site)), 1)


class BuildPathRegressionTests(unittest.TestCase):
    def test_nested_page_sidebar_uses_page_prefix(self):
        page = build_site.page_shell(
            "Topic", "Desc", "", "<main></main>",
            build_site.tabbar("topics", "../"), prefix="../", active="topics",
        )
        self.assertIn('class="slogo"><a href="../index.html"', page)
        self.assertIn('class="mi" href="../classics.html"', page)
        self.assertIn('class="mi on" href="../topics.html"', page)

    def test_old_evergreen_keeps_detail_while_orphan_is_removed(self):
        old = event("old-evergreen", evergreen=True, published="2025-01-01T12:00:00+08:00")
        fresh = event("fresh-news")
        with tempfile.TemporaryDirectory() as directory:
            detail_dir = Path(directory) / "e"
            detail_dir.mkdir()
            (detail_dir / "orphan.html").write_text("stale", encoding="utf-8")
            valid = build_site.write_detail_pages([fresh, old], "", detail_dir)
            self.assertEqual(valid, {"fresh-news.html", "old-evergreen.html"})
            self.assertTrue((detail_dir / "old-evergreen.html").exists())
            self.assertFalse((detail_dir / "orphan.html").exists())


if __name__ == "__main__":
    unittest.main()
