import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from image_derivatives import responsive_image
from case_visuals import card_image
from content_blocks import render_blocks_html
from check_links import LocalReferenceParser
import build_site
from test_cases_page import case_event


class DisplayImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = "media/abcdef123456/abcdef12345678901234.png"
        self.original = self.root / self.src
        self.original.parent.mkdir(parents=True)
        image = Image.new("RGB", (1600, 900), "white")
        image.paste("red", (800, 0, 1600, 900))
        image.save(self.original, compress_level=0)

    def test_smaller_responsive_assets_preserve_original_and_are_reused(self):
        before = self.original.read_bytes()
        result = responsive_image(self.src, self.root, (400, 800))
        first = self.root / result["src"]
        stamp = first.stat().st_mtime_ns
        self.assertLess(first.stat().st_size, len(before) // 10)
        with Image.open(first) as decoded:
            self.assertEqual(decoded.size, (400, 225))
        self.assertIn("800w", result["srcset"])
        self.assertEqual(responsive_image(self.src, self.root, (400, 800)), result)
        self.assertEqual(first.stat().st_mtime_ns, stamp)
        self.assertEqual(self.original.read_bytes(), before)

    def test_crop_is_applied_before_resize_and_not_css_cropped_again(self):
        region = {"rect": [800, 0, 800, 450]}
        result = responsive_image(self.src, self.root, (400, 800, 1200), region["rect"])
        self.assertNotIn("1200w", result["srcset"])
        with Image.open(self.root / result["src"]) as preview:
            self.assertEqual(preview.size, (400, 225))
            red, green, blue = preview.getpixel((200, 100))[:3]
        self.assertGreater(red, 240)
        self.assertLess(green + blue, 20)
        with patch("case_visuals.visual_for", return_value=region):
            markup = card_image(self.src, "test", site_root=self.root, priority=True)
        self.assertIn('fetchpriority="high"', markup)
        self.assertIn('loading="eager"', markup)
        self.assertNotIn("left:", markup)
        self.assertIn("局部预览", markup)

    def test_changed_source_invalidates_url_and_old_file_remains(self):
        before = responsive_image(self.src, self.root)
        Image.new("RGB", (1600, 900), "blue").save(self.original)
        after = responsive_image(self.src, self.root)
        self.assertNotEqual(before["src"], after["src"])
        self.assertTrue((self.root / before["src"]).is_file())

    def test_relative_urls_no_upscale_and_missing_original_fallback(self):
        result = responsive_image("../" + self.src, self.root, (2000, 2400))
        self.assertTrue(result["src"].startswith("../derived-media/"))
        self.assertEqual(len(result["srcset"].split(",")), 1)
        self.assertTrue(result["srcset"].endswith("1600w"))
        self.assertIsNone(responsive_image("media/absent/missing.png", self.root))
        self.assertIn(f'src="{self.src}"', card_image(self.src, "original"))

    def test_unsafe_paths_and_symlinks_never_write_outside_root(self):
        for src in ["../../secret.png", "media/a/../../secret.png", "https://example.org/image.png"]:
            self.assertIsNone(responsive_image(src, self.root))
        with tempfile.TemporaryDirectory() as outside:
            escaped = Path(outside) / "file.png"
            Image.new("RGB", (10, 10)).save(escaped)
            self.original.unlink()
            self.original.symlink_to(escaped)
            with self.assertRaises(ValueError):
                responsive_image(self.src, self.root)

    def test_invalid_crop_is_rejected(self):
        for crop in [[-1, 0, 20, 20], [0, 0, 9000, 20], [0, 0, float("nan"), 1]]:
            with self.assertRaises(ValueError):
                responsive_image(self.src, self.root, crop=crop)

    def test_article_keeps_original_link_and_all_figures(self):
        block = {"type": "figure", "src": "https://example.org/original.png", "cached_src": "../" + self.src,
                 "media_status": "cached", "alt": "diagram", "width": 1600, "height": 900}
        rendered = render_blocks_html([block, block], site_root=self.root)
        self.assertEqual(rendered.count('<figure class="cb-figure">'), 2)
        self.assertIn('href="https://example.org/original.png"', rendered)
        self.assertIn('src="../derived-media/', rendered)
        self.assertIn('width="1600" height="900"', rendered)

    def test_srcset_links_are_included_in_build_validation(self):
        parser = LocalReferenceParser()
        parser.feed('<img src="a.webp" srcset="a.webp 400w, missing.webp 800w">')
        self.assertIn("missing.webp", [reference for _, reference in parser.references])

    def test_detail_topbar_css_arrives_in_head_and_audio_does_not_prefetch(self):
        item = {"status": "ready", "audio_path": "audio/2026/09/abcdef123456-aaaaaaaaaaaa.mp3"}
        page = build_site.render_detail(case_event(), [case_event()], "", tts_item=item)
        head, body = page.split("</head>", 1)
        self.assertIn(".topbar.detail-context", head)
        self.assertNotIn("<style>", body)
        self.assertIn('preload="none"', body)
        self.assertNotIn('preload="metadata"', body)


if __name__ == "__main__":
    unittest.main()
