import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402
from seo import (  # noqa: E402
    SITEMAP_NAMESPACE,
    absolute_public_url,
    build_sitemap,
    public_sitemap_paths,
    robots_text,
    validate_sitemap,
    write_search_discovery,
)
from site_config import DEFAULT_SITE_BASE_URL  # noqa: E402


SITE_BASE = DEFAULT_SITE_BASE_URL
NS = {"sm": SITEMAP_NAMESPACE}


class SitemapTests(unittest.TestCase):
    def test_public_allowlist_contains_only_current_content_pages(self):
        paths = public_sitemap_paths(
            ["abc123.html", "def456.html"],
            ["data-agent.html"],
            ["2026-W32.html"],
        )
        self.assertIn("", paths)
        self.assertIn("cases.html", paths)
        self.assertIn("e/abc123.html", paths)
        self.assertIn("topics/data-agent.html", paths)
        self.assertIn("weekly/2026-W32.html", paths)
        for excluded in (
            "index.html", "favorites.html", "for-me.html", "daily.html",
            "privacy.html", "feed.xml", "data/latest.json",
        ):
            self.assertNotIn(excluded, paths)

    def test_disabled_weekly_removes_current_and_archive_pages(self):
        paths = public_sitemap_paths([], [], ["2026-W32.html"], weekly_enabled=False)
        self.assertNotIn("weekly.html", paths)
        self.assertFalse(any(path.startswith("weekly/") for path in paths))

    def test_sitemap_uses_unique_absolute_https_canonical_urls(self):
        payload = build_sitemap(
            ["e/b.html", "", "e/a.html", "index.html", "e/a.html"], SITE_BASE,
        )
        self.assertTrue(payload.startswith(b"<?xml"))
        root = ET.fromstring(payload)
        locations = [item.text for item in root.findall("sm:url/sm:loc", NS)]
        self.assertEqual(locations, [f"{SITE_BASE}/", f"{SITE_BASE}/e/a.html", f"{SITE_BASE}/e/b.html"])
        self.assertEqual(validate_sitemap(payload, site_base=SITE_BASE), [])

    def test_sitemap_emits_valid_per_url_lastmod_dates(self):
        payload = build_sitemap(
            ["", "e/a.html"], SITE_BASE,
            lastmod_by_path={"": "2026-08-31", "e/a.html": "2026-08-29"},
        )
        root = ET.fromstring(payload)
        rows = {
            item.find("sm:loc", NS).text: item.find("sm:lastmod", NS).text
            for item in root.findall("sm:url", NS)
        }
        self.assertEqual(rows, {
            f"{SITE_BASE}/": "2026-08-31",
            f"{SITE_BASE}/e/a.html": "2026-08-29",
        })
        self.assertEqual(validate_sitemap(payload, site_base=SITE_BASE), [])
        with self.assertRaises(ValueError):
            build_sitemap([""], SITE_BASE, lastmod_by_path={"": "2026-08-31T12:00:00Z"})

    def test_invalid_or_missing_urls_are_rejected(self):
        with self.assertRaises(ValueError):
            absolute_public_url("../admin.html", SITE_BASE)
        foreign = build_sitemap(["e/a.html"], "https://foreign.example")
        self.assertTrue(validate_sitemap(foreign, site_base=SITE_BASE)[0].startswith("foreign_or_noncanonical:"))

        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            (site / "index.html").write_text("ok", encoding="utf-8")
            payload = build_sitemap(["", "e/missing.html"], SITE_BASE)
            self.assertEqual(
                validate_sitemap(payload, site_base=SITE_BASE, site_root=site),
                [f"missing:{SITE_BASE}/e/missing.html"],
            )

    def test_writer_emits_valid_files_and_robots_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            (site / "e").mkdir()
            (site / "index.html").write_text("home", encoding="utf-8")
            (site / "e" / "abc.html").write_text("detail", encoding="utf-8")
            count = write_search_discovery(site, ["", "e/abc.html"], site_base=SITE_BASE)
            self.assertEqual(count, 2)
            self.assertEqual(validate_sitemap(
                (site / "sitemap.xml").read_bytes(), site_base=SITE_BASE, site_root=site,
            ), [])
            self.assertEqual((site / "robots.txt").read_text(encoding="utf-8"), robots_text(SITE_BASE))
            self.assertIn(f"Sitemap: {SITE_BASE}/sitemap.xml", robots_text(SITE_BASE))


class SearchMetadataTests(unittest.TestCase):
    def test_sitemap_date_treats_naive_source_times_as_shanghai_local(self):
        self.assertEqual(build_site.sitemap_date("2026-08-31T23:30:00", "fallback"), "2026-08-31")
        self.assertEqual(build_site.sitemap_date("invalid", "2026-08-30"), "2026-08-30")

    def test_page_shell_can_emit_canonical_url_and_noindex(self):
        document = build_site.page_shell(
            "标题", "描述", "", "", "", canonical_path="topics.html",
        )
        self.assertIn(f'<link rel="canonical" href="{SITE_BASE}/topics.html">', document)
        self.assertIn(f'<meta property="og:url" content="{SITE_BASE}/topics.html">', document)
        self.assertNotIn('name="robots" content="noindex', document)

        private_document = build_site.page_shell(
            "本地页", "描述", "", "", "", indexable=False,
        )
        self.assertIn('<meta name="robots" content="noindex,follow">', private_document)


if __name__ == "__main__":
    unittest.main()
