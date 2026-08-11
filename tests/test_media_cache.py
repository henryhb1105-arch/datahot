import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from content_blocks import parse_html_blocks, render_blocks_html, sanitize_blocks  # noqa: E402
from media_cache import (  # noqa: E402
    MediaRejected,
    cache_event_media,
    download_media,
    prune_media_cache,
    same_site_media,
    sanitize_raster,
    sanitize_svg,
)
import run_update  # noqa: E402
import build_site  # noqa: E402


def jpeg_bytes(width=800, height=400, exif=True):
    image = Image.new("RGB", (width, height), (38, 92, 140))
    output = io.BytesIO()
    options = {"format": "JPEG", "quality": 90}
    if exif:
        metadata = Image.Exif()
        metadata[0x010E] = "private camera description"
        options["exif"] = metadata
    image.save(output, **options)
    return output.getvalue()


class FigureParsingTests(unittest.TestCase):
    def test_parser_preserves_figures_captions_and_best_srcset_candidate(self):
        markup = """
        <article>
          <p>Before image.</p>
          <figure>
            <img src="/small.png" srcset="/small.png 320w, /chart.png 1280w"
                 alt="Quarterly chart" width="1280" height="720">
            <figcaption><strong>Revenue</strong> by quarter</figcaption>
          </figure>
          <img data-src="/standalone.jpg" alt="Architecture">
        </article>
        """
        blocks = parse_html_blocks(markup, "https://blog.example.com/post")
        figures = [block for block in blocks if block["type"] == "figure"]
        self.assertEqual(len(figures), 2)
        self.assertEqual(figures[0]["src"], "https://blog.example.com/chart.png")
        self.assertEqual(figures[0]["caption"], "Revenue by quarter")
        self.assertEqual(figures[0]["source_url"], "https://blog.example.com/post")
        self.assertEqual((figures[0]["width"], figures[0]["height"]), (1280, 720))
        self.assertEqual(figures[1]["src"], "https://blog.example.com/standalone.jpg")

    def test_noimageindex_is_carried_to_media_policy(self):
        markup = (
            '<meta content="index, noimageindex" name="robots"><article>'
            '<p>' + ("Article text. " * 80) + '</p>'
            '<img src="https://example.com/chart.png" alt="chart"></article>'
        )
        with patch.object(run_update, "fetch_url", return_value=markup.encode()):
            _text, _title, _date, blocks = run_update.fetch_article_content("https://example.com/post")
        figure = next(block for block in blocks if block["type"] == "figure")
        self.assertEqual(figure["media_reason"], "rights_restricted")

    def test_cached_path_is_strictly_scoped_to_site_media(self):
        figure = {
            "type": "figure",
            "src": "https://example.com/chart.png",
            "cached_src": "../../etc/passwd",
        }
        cleaned = sanitize_blocks([figure], "https://example.com/post")[0]
        self.assertNotIn("cached_src", cleaned)


class MediaSanitizerTests(unittest.TestCase):
    def test_raster_is_reencoded_without_exif(self):
        original = jpeg_bytes(exif=True)
        cleaned, mime, extension, width, height = sanitize_raster(
            original, "image/jpeg",
            min_width=240, min_height=120, max_pixels=24_000_000,
            max_bytes=5_000_000, max_dimension=2400,
        )
        self.assertEqual((mime, extension, width, height), ("image/jpeg", "jpg", 800, 400))
        image = Image.open(io.BytesIO(cleaned))
        self.assertEqual(len(image.getexif()), 0)
        self.assertNotIn(b"private camera description", cleaned)

    def test_mime_dimensions_and_size_are_enforced(self):
        with self.assertRaisesRegex(MediaRejected, "mime_mismatch"):
            sanitize_raster(
                jpeg_bytes(), "image/png",
                min_width=240, min_height=120, max_pixels=24_000_000,
                max_bytes=5_000_000, max_dimension=2400,
            )
        with self.assertRaisesRegex(MediaRejected, "dimensions_too_small"):
            sanitize_raster(
                jpeg_bytes(80, 40), "image/jpeg",
                min_width=240, min_height=120, max_pixels=24_000_000,
                max_bytes=5_000_000, max_dimension=2400,
            )

    def test_svg_removes_scripts_external_refs_and_event_attributes(self):
        unsafe = b'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400" viewBox="0 0 800 400">
          <script>alert(1)</script>
          <foreignObject><div>HTML</div></foreignObject>
          <image href="https://evil.example/x.png" width="100" height="100" />
          <rect width="800" height="400" fill="url(https://evil.example/a)" onclick="bad()" />
          <path d="M0 0 L20 20" stroke="#355b78" />
        </svg>'''
        cleaned, mime, extension, width, height = sanitize_svg(unsafe)
        self.assertEqual((mime, extension, width, height), ("image/svg+xml", "svg", 800, 400))
        lowered = cleaned.lower()
        for forbidden in (b"script", b"foreignobject", b"<image", b"onclick", b"https://", b"url("):
            self.assertNotIn(forbidden, lowered)
        self.assertIn(b"path", lowered)


class MediaCacheTests(unittest.TestCase):
    def figure(self, src="https://blog.example.com/chart.jpg"):
        return [{
            "type": "figure", "src": src, "alt": "Chart",
            "caption": "Quarterly chart", "source_url": "https://blog.example.com/post",
        }]

    def test_same_site_policy_rejects_unrelated_hosts(self):
        self.assertTrue(same_site_media("https://cdn.example.com/a.png", "https://blog.example.com/post"))
        self.assertFalse(same_site_media("https://tracker.invalid/a.png", "https://blog.example.com/post"))

    def test_private_network_urls_are_rejected_before_download(self):
        with self.assertRaisesRegex(MediaRejected, "private_host"):
            download_media("http://127.0.0.1/internal.png", 1000)

    def test_safe_media_is_cached_in_event_directory(self):
        def fetcher(url, maximum):
            self.assertLess(len(jpeg_bytes()), maximum)
            return jpeg_bytes(), "image/jpeg", url

        with tempfile.TemporaryDirectory() as directory:
            blocks, report = cache_event_media(
                self.figure(), "event-1", "https://blog.example.com/post", directory,
                fetcher=fetcher, enabled=True,
            )
            figure = blocks[0]
            self.assertEqual(report["cached"], 1)
            self.assertEqual(figure["media_status"], "cached")
            self.assertRegex(figure["cached_src"], r"^\.\./media/event-1/[a-f0-9]{24}\.jpg$")
            cached = Path(directory) / figure["cached_src"].removeprefix("../")
            self.assertTrue(cached.exists())
            self.assertLessEqual(cached.stat().st_size, 5_000_000)

    def test_cross_site_rights_and_disabled_modes_stay_link_only(self):
        fetcher = unittest.mock.Mock(side_effect=AssertionError("must not download"))
        cases = [
            (self.figure("https://unrelated.invalid/chart.jpg"), True, "cross_site_host"),
            (self.figure(), False, "disabled"),
        ]
        rights = self.figure()
        rights[0]["media_reason"] = "rights_restricted"
        cases.append((rights, True, "rights_restricted"))
        with tempfile.TemporaryDirectory() as directory:
            for blocks, enabled, reason in cases:
                cached, report = cache_event_media(
                    blocks, "event-1", "https://blog.example.com/post", directory,
                    fetcher=fetcher, enabled=enabled,
                )
                self.assertEqual(report["link_only"], 1)
                self.assertEqual(cached[0]["media_reason"], reason)
                self.assertNotIn("cached_src", cached[0])
        fetcher.assert_not_called()

    def test_total_cache_limit_and_pruning_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            stale = Path(directory) / "media" / "stale-event"
            active = Path(directory) / "media" / "active-event"
            stale.mkdir(parents=True)
            active.mkdir(parents=True)
            (stale / "old.jpg").write_bytes(b"old")
            (active / "keep.jpg").write_bytes(b"keep")
            result = prune_media_cache(["active-event"], directory)
            self.assertEqual(result["removed_dirs"], 1)
            self.assertFalse(stale.exists())
            self.assertTrue(active.exists())

            with patch.dict("os.environ", {"MEDIA_CACHE_MAX_BYTES": "1"}):
                blocks, report = cache_event_media(
                    self.figure(), "event-1", "https://blog.example.com/post", directory,
                    fetcher=lambda url, maximum: (jpeg_bytes(), "image/jpeg", url),
                    enabled=True,
                )
            self.assertEqual(report["reasons"], {"cache_total_limit": 1})
            self.assertNotIn("cached_src", blocks[0])

    def test_responsive_renderer_uses_local_media_and_traceable_links(self):
        figure = self.figure()[0]
        figure.update({
            "cached_src": "../media/event-1/0123456789abcdef01234567.jpg",
            "width": 800, "height": 400, "mime": "image/jpeg",
            "size_bytes": 1234, "media_status": "cached",
        })
        rendered = render_blocks_html([figure])
        self.assertIn('loading="lazy"', rendered)
        self.assertIn('decoding="async"', rendered)
        self.assertIn("../media/event-1/0123456789abcdef01234567.jpg", rendered)
        self.assertIn("来源：", rendered)
        self.assertIn("查看原图", rendered)
        self.assertNotIn("onclick", rendered)
        without_media = render_blocks_html([figure], render_media=False)
        self.assertNotIn("<img", without_media)
        self.assertIn("查看原图", without_media)

    def test_detail_page_contains_responsive_media_container_and_fallback(self):
        event = {
            "event_id": "event-1", "zh_title": "图表集成", "zh_summary": "摘要",
            "reason": "", "full_zh": "", "category": "bi", "category_label": "BI 与可视化",
            "vendors": [], "topics": [], "heat": 60, "importance": 60, "signal": 0,
            "shelf": "news", "published": "2026-08-11T12:00:00+08:00",
            "first_seen": "2026-08-11T12:00:00+08:00",
            "items": [{
                "id": "source-1", "source": "Databricks Blog",
                "link": "https://blog.example.com/post",
                "published": "2026-08-11T12:00:00+08:00", "title": "Source",
            }],
            "content_blocks": self.figure(),
        }
        page = build_site.render_detail(event, [event], "")
        self.assertIn("cb-media-placeholder", page)
        self.assertIn(".cb-figure img{display:block;width:100%;height:auto", page)
        self.assertIn("@media(max-width:600px)", page)
        self.assertIn(".cb-table{overflow-x:auto", page)
        self.assertIn("body{overflow-x:clip}", page)


if __name__ == "__main__":
    unittest.main()
