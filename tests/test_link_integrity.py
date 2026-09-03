import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
    def test_fixture_covers_root_topic_detail_and_assets(self):
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
                '<a href="topics.html">Topics</a>',
                encoding="utf-8",
            )
            (site / "topics.html").write_text('<a href="topics/data.html">Data</a>', encoding="utf-8")
            (site / "topics" / "data.html").write_text(
                '<a href="../index.html">Home</a><a href="../e/old-event.html">Old</a>',
                encoding="utf-8",
            )
            (site / "e" / "old-event.html").write_text(
                '<link href="../favicon.ico"><a href="../topics/data.html">Back</a>'
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

    def test_checker_validates_local_poster_qr_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            (site / "e").mkdir()
            (site / "qr").mkdir()
            detail = site / "e" / "event.html"
            detail.write_text(
                '<button data-poster-qr-src="../qr/event.png">海报</button>',
                encoding="utf-8",
            )
            self.assertEqual(len(check_site_links(site)), 1)
            (site / "qr" / "event.png").write_bytes(b"png")
            self.assertEqual(check_site_links(site), [])


class BuildPathRegressionTests(unittest.TestCase):
    def test_retired_classics_page_is_removed_without_touching_other_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            (site / "classics.html").write_text("retired", encoding="utf-8")
            (site / "index.html").write_text("home", encoding="utf-8")

            build_site.remove_retired_public_pages(site)

            self.assertFalse((site / "classics.html").exists())
            self.assertTrue((site / "index.html").exists())

    def test_source_public_url_only_allows_web_links(self):
        self.assertEqual(
            build_site.source_public_url({"url": "https://example.com/feed.xml"}),
            "https://example.com/feed.xml",
        )
        self.assertEqual(build_site.source_public_url({"url": "javascript:alert(1)"}), "")

    def test_source_public_url_hides_sitemap_path(self):
        source = {
            "kind": "sitemap",
            "urls": ["https://example.com/private/sitemap.xml"],
        }
        self.assertEqual(build_site.source_public_url(source), "https://example.com/")

    def test_source_public_url_supports_community_sources(self):
        self.assertEqual(
            build_site.source_public_url({"kind": "hn_algolia"}),
            "https://news.ycombinator.com/",
        )

    def test_mobile_navigation_has_five_primary_slots_and_more_sheet(self):
        with patch.dict(build_site.os.environ, {"WEEKLY_BRIEF_ENABLED": "true"}, clear=False):
            markup = build_site.tabbar("home")
        primary = markup.split("</nav>", 1)[0]
        self.assertEqual(primary.count("<a "), 4)
        self.assertEqual(primary.count("<button "), 1)
        self.assertIn("<span>热榜</span>", primary)
        self.assertIn("<span>关注</span>", primary)
        self.assertIn("<span>案例</span>", primary)
        self.assertIn("<span>收藏</span>", primary)
        self.assertIn("<span>更多</span>", primary)
        self.assertNotIn("<span>主题</span>", primary)
        for label in ("每周简报", "主题", "完整榜单", "信源", "接入 Agent", "隐私说明"):
            self.assertIn(label, markup)
        self.assertNotIn("典藏", markup)
        self.assertNotIn("classics.html", markup)

    def test_more_pages_highlight_more_tab(self):
        sources = build_site.tabbar("sources")
        self.assertIn('class="tabbar-more on"', sources)
        self.assertIn('class="more-link on" href="sources.html"', sources)
        favorites = build_site.tabbar("favorites")
        self.assertNotIn('class="tabbar-more on"', favorites)
        self.assertIn('href="favorites.html" class="on"', favorites)
        self.assertNotIn('class="tabbar-more on"', build_site.tabbar("home"))

    def test_agent_page_is_available_in_desktop_and_mobile_navigation(self):
        sidebar = build_site.sidebar("agent")
        tabbar = build_site.tabbar("agent")
        self.assertIn('class="sidebar-tools" aria-label="工具"', sidebar)
        self.assertIn('class="mi on" href="agent.html"', sidebar)
        self.assertIn('class="tabbar-more on"', tabbar)
        self.assertIn('class="more-link on" href="agent.html"', tabbar)

    def test_desktop_navigation_uses_compact_reader_labels_and_separates_tools(self):
        with patch.dict(build_site.os.environ, {"WEEKLY_BRIEF_ENABLED": "true"}, clear=False):
            sidebar = build_site.sidebar("hot")
        primary = sidebar.split('<nav class="sidebar-nav" aria-label="主导航">', 1)[1].split("</nav>", 1)[0]
        tools = sidebar.split('<nav class="sidebar-tools" aria-label="工具">', 1)[1].split("</nav>", 1)[0]

        labels = ("热榜", "关注", "案例", "周报", "主题", "收藏", "信源")
        self.assertEqual(primary.count('<a class="mi'), len(labels))
        positions = [primary.index(f">{label}</a>") for label in labels]
        self.assertEqual(positions, sorted(positions))
        for old_label in ("For Me", "每周简报", "我的收藏", "完整榜单", "典藏", "接入 Agent"):
            self.assertNotIn(old_label, primary)
        self.assertNotIn("classics.html", primary)

        self.assertIn('class="mi on" href="index.html"', primary)
        self.assertIn('href="agent.html"', tools)
        self.assertIn("接入 Agent", tools)
        self.assertIn(".sidebar .sidebar-tools{margin-top:auto", build_site.SHARED_CSS)
        builder = (ROOT / "pipeline" / "build_site.py").read_text(encoding="utf-8")
        self.assertIn('class="today-hot-more" href="hot.html"', builder)
        self.assertIn("完整榜单 →</a>", builder)

    def test_section_and_detail_use_shared_navigation_shells(self):
        section = build_site.page_shell(
            "Topic", "Desc", "", "<main></main>",
            build_site.tabbar("topics"), active="topics",
        )
        self.assertIn('class="has-sb mobile-section"', section)
        self.assertIn('class="section-brand-header"', section)

        detail = build_site.render_detail(event("detail-event"), [event("detail-event")], "")
        self.assertIn('class="has-sb mobile-detail"', detail)
        self.assertIn('class="detail-brand-header"', detail)
        self.assertIn('class="topbar detail-context"', detail)
        self.assertIn('class="article-content"', detail)
        self.assertIn(".article{max-width:1040px", detail)
        self.assertIn(".article-content{max-width:840px;margin:0 auto}", detail)
        self.assertIn(
            ".topbar.detail-context{position:sticky;top:0;z-index:55",
            detail,
        )
        self.assertIn(
            ".topbar.detail-context .back{display:inline-flex;"
            "align-items:center;justify-content:center;align-self:center;"
            "min-width:88px;min-height:44px",
            detail,
        )
        self.assertNotIn(
            "@media(max-width:1199px){\n.topbar.detail-context{position:sticky",
            detail,
        )
        self.assertEqual(detail.count('<aside class="sidebar">'), 1)
        self.assertIn('class="mi on" href="../index.html"', detail)
        self.assertIn('class="mi" href="../topics.html"', detail)
        self.assertGreaterEqual(detail.count("data-smart-home-return"), 3)
        self.assertIn('href="../index.html" class="on" data-home-top', detail)
        self.assertIn('data-poster-qr-src="../qr/detail-event.png"', detail)
        self.assertNotIn("api.qrserver.com", detail)

    def test_build_generates_one_same_origin_qr_per_detail_and_removes_stale_files(self):
        with tempfile.TemporaryDirectory() as directory:
            qr_dir = Path(directory) / "qr"
            qr_dir.mkdir()
            (qr_dir / "stale.png").write_bytes(b"stale")
            generated = build_site.write_qr_assets(
                [event("detail-event")], qr_dir=qr_dir,
                site_base="https://example.com/datahot",
            )
            self.assertEqual(generated, {"detail-event.png"})
            payload = (qr_dir / "detail-event.png").read_bytes()
            self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertGreater(len(payload), 100)
            self.assertFalse((qr_dir / "stale.png").exists())

    def test_share_copy_and_poster_fail_closed(self):
        detail = build_site.render_detail(event("share-event"), [event("share-event")], "")
        self.assertIn("then(function(){return true},function(){return fallbackCopy(SH_EV.url)})", detail)
        self.assertIn("ok?'链接已复制，去粘贴吧':'复制失败，请手动复制链接'", detail)
        self.assertIn("qr.src=SH_EV.qr", detail)
        self.assertIn("海报生成失败，请稍后重试", detail)
        self.assertNotIn("drawPoster(null", detail)
        self.assertNotIn("api.qrserver.com", detail)

    def test_nested_page_sidebar_uses_page_prefix(self):
        page = build_site.page_shell(
            "Topic", "Desc", "", "<main></main>",
            build_site.tabbar("topics", "../"), prefix="../", active="topics",
        )
        self.assertIn('class="slogo"><a href="../index.html"', page)
        self.assertNotIn("classics.html", page)
        self.assertNotIn("典藏", page)
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
