import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import site_config  # noqa: E402


class SiteConfigTests(unittest.TestCase):
    def test_canonical_origin_defaults_to_custom_domain(self):
        self.assertEqual(site_config.DEFAULT_SITE_BASE_URL, "https://datahot.xiahongbin.com")
        self.assertEqual(site_config.resolve_site_base_url("https://DATAHOT.xiahongbin.com/"), "https://datahot.xiahongbin.com")

    def test_invalid_or_path_based_origin_is_rejected(self):
        invalid_values = (
            "http://datahot.xiahongbin.com",
            "https://datahot.xiahongbin.com/datahot",
            "https://user@example.com",
            "https://datahot.xiahongbin.com/?preview=1",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                site_config.resolve_site_base_url(value)

    def test_environment_override_is_supported(self):
        with patch.dict(os.environ, {"SITE_BASE_URL": "https://preview.example.com/"}, clear=False):
            self.assertEqual(site_config.resolve_site_base_url(), "https://preview.example.com")

    def test_public_source_files_do_not_reference_legacy_origin(self):
        legacy = site_config.LEGACY_SITE_BASE_URL
        paths = (
            ROOT / "pipeline" / "build_site.py",
            ROOT / "pipeline" / "agent_page.py",
            ROOT / "pipeline" / "assets" / "analytics.js",
            ROOT / "skills" / "datahot-news" / "SKILL.md",
            ROOT / "README.md",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertNotIn(legacy, path.read_text(encoding="utf-8"))

    def test_public_site_builder_uses_the_verified_bluesky_domain_handle(self):
        source = (ROOT / "pipeline" / "build_site.py").read_text(encoding="utf-8")
        self.assertIn('BLUESKY_HANDLE = "datahot.xiahongbin.com"', source)
        self.assertNotIn("bsky.app/profile/henryhb1105.bsky.social", source)


if __name__ == "__main__":
    unittest.main()
