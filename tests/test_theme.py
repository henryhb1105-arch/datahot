"""Public theme delivery and legibility contracts, independent of page content."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import build_site


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    values = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(values, (.2126, .7152, .0722)))


class ThemeTests(unittest.TestCase):
    def test_root_and_nested_pages_load_theme_after_component_styles(self):
        for prefix in ('', '../', '../../'):
            with self.subTest(prefix=prefix):
                document = build_site.page_shell('Title', 'Description', '', '<h1>Title</h1>', '', prefix=prefix)
                self.assertRegex(document, rf'href="{re.escape(prefix)}theme.css\?v=[a-f0-9]{{12}}"')
                self.assertGreater(document.index('id="datahot-theme"'), document.rindex('</style>'))
                self.assertLess(document.index('id="datahot-theme"'), document.index('</head>'))
                self.assertEqual(build_site.apply_site_theme(document), document)
                self.assertIn('media="(prefers-color-scheme: dark)"', document)

    def test_reading_and_action_colors_meet_normal_text_contrast(self):
        css = build_site.THEME_ASSET.read_text()
        palettes = re.findall(r':root\s*\{([^}]+)\}', css)
        self.assertEqual(len(palettes), 2)
        for palette in palettes:
            colors = dict(re.findall(r'--([\w-]+):\s*(#[a-f0-9]{6})', palette))
            pairs = [(text, surface) for text in ('ink', 'sub', 'txt2', 'txt3', 'accent', 'heat')
                     for surface in ('bg', 'card')]
            pairs += [(text, surface) for text in ('sub', 'txt2', 'accent') for surface in ('soft', 'accent-soft')]
            pairs += [('on-action', 'action')]
            for text, surface in pairs:
                with self.subTest(text=text, surface=surface, bg=colors['bg']):
                    hi, lo = sorted((luminance(colors[text]), luminance(colors[surface])), reverse=True)
                    self.assertGreaterEqual((hi + .05) / (lo + .05), 4.5)


if __name__ == '__main__':
    unittest.main()
