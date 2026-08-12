import base64
import hashlib
import html
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402
from content_blocks import sanitize_url  # noqa: E402


def event(**overrides):
    value = {
        "event_id": "abc123def456",
        "zh_title": "安全测试事件",
        "zh_summary": "用于安全回归测试。",
        "reason": "验证不可信内容不会变成脚本。",
        "category": "agent",
        "published": "2026-08-12T00:00:00+00:00",
        "first_seen": "2026-08-12T00:00:00+00:00",
        "heat": 80,
        "topics": [],
        "vendors": [],
        "items": [{
            "id": "source-1",
            "source": "测试信源",
            "title": "测试报道",
            "link": "https://example.com/article",
            "published": "2026-08-12T00:00:00+00:00",
        }],
        "full_zh": "正文",
        "content_blocks": [],
    }
    value.update(overrides)
    return value


def csp_from(document):
    match = re.search(
        r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">',
        document,
    )
    if not match:
        return ""
    return html.unescape(match.group(1))


class SecurityHardeningTests(unittest.TestCase):
    def assert_csp_allows_only_hashed_inline_scripts(self, document):
        csp = csp_from(document)
        self.assertTrue(csp)
        self.assertIn("base-uri 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("script-src-attr 'none'", csp)
        self.assertIn("upgrade-insecure-requests", csp)
        script_directive = next(
            directive.strip() for directive in csp.split(";")
            if directive.strip().startswith("script-src ")
        )
        self.assertNotIn("'unsafe-inline'", script_directive)
        for script in build_site.INLINE_SCRIPT_RE.findall(document):
            digest = base64.b64encode(
                hashlib.sha256(script.encode("utf-8")).digest()
            ).decode("ascii")
            self.assertIn(f"'sha256-{digest}'", script_directive)

    def test_page_shell_adds_csp_and_referrer_policy(self):
        document = build_site.page_shell(
            "标题", "描述", "body{}", "<main>正文</main>", "",
        )
        self.assert_csp_allows_only_hashed_inline_scripts(document)
        self.assertIn(
            '<meta name="referrer" content="strict-origin-when-cross-origin">',
            document,
        )

    def test_csp_allows_only_configured_analytics_origin(self):
        with patch.dict(build_site.os.environ, {
            "ANALYTICS_ENDPOINT": "https://metrics.example.com/v1/events",
            "ANALYTICS_ENABLED": "true",
            "ANALYTICS_ENV": "production",
        }, clear=False):
            document = build_site.page_shell("标题", "描述", "", "", "")
        csp = csp_from(document)
        self.assertIn("connect-src 'self' https://metrics.example.com", csp)
        self.assertNotIn("https://metrics.example.com/v1/events", csp)

    def test_inline_event_handlers_fail_the_build_closed(self):
        with self.assertRaisesRegex(ValueError, "inline event handlers"):
            build_site.finalize_html_security(
                '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
                '<body><button onclick="alert(1)">危险</button></body></html>'
            )

    def test_detail_escapes_script_breakout_and_drops_dangerous_primary_url(self):
        payload = event(
            zh_title='</script><script>alert("xss")</script>',
            items=[{
                "id": "source-1",
                "source": "恶意测试",
                "title": "测试报道",
                "link": "java\nscript:alert(1)",
                "published": "2026-08-12T00:00:00+00:00",
            }],
        )
        document = build_site.render_detail(payload, [payload], "")
        self.assert_csp_allows_only_hashed_inline_scripts(document)
        self.assertNotIn('<script>alert("xss")</script>', document)
        self.assertNotIn('href="javascript:', document.lower())
        self.assertIn("原文链接不可用", document)
        self.assertIn("\\u003c/script\\u003e", document)

    def test_external_blank_links_are_isolated(self):
        payload = event()
        document = build_site.render_detail(payload, [payload], "")
        for tag in re.findall(r'<a\b[^>]*target="_blank"[^>]*>', document, re.I):
            rel_match = re.search(r'rel="([^"]+)"', tag, re.I)
            self.assertIsNotNone(rel_match, tag)
            rel = set(rel_match.group(1).lower().split())
            self.assertTrue({"noopener", "noreferrer"}.issubset(rel), tag)

    def test_dangerous_and_ambiguous_urls_are_rejected(self):
        for value in (
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "https://user:pass@example.com/private",
            r"https://example.com\@evil.example/path",
            "https://example.com:bad/path",
        ):
            with self.subTest(value=value):
                self.assertEqual(sanitize_url(value), "")
        self.assertEqual(
            sanitize_url("/article", "https://example.com/news/"),
            "https://example.com/article",
        )

    def test_invalid_event_id_cannot_escape_detail_directory(self):
        payload = event(event_id="../../outside")
        with tempfile.TemporaryDirectory() as tmpdir:
            detail_dir = Path(tmpdir) / "e"
            with self.assertRaisesRegex(ValueError, "unsafe event_id"):
                build_site.write_detail_pages([payload], "", detail_dir=detail_dir)
            self.assertFalse((Path(tmpdir) / "outside.html").exists())

    def test_generated_html_tree_has_security_baseline(self):
        pages = sorted((ROOT / "site").rglob("*.html"))
        self.assertGreater(len(pages), 300)
        for page in pages:
            with self.subTest(page=page.relative_to(ROOT)):
                document = page.read_text(encoding="utf-8")
                self.assert_csp_allows_only_hashed_inline_scripts(document)
                self.assertIsNone(build_site.INLINE_EVENT_HANDLER_RE.search(document))
                for tag in re.findall(r'<a\b[^>]*target="_blank"[^>]*>', document, re.I):
                    rel_match = re.search(r'rel="([^"]+)"', tag, re.I)
                    self.assertIsNotNone(rel_match, tag)
                    rel = set(rel_match.group(1).lower().split())
                    self.assertTrue({"noopener", "noreferrer"}.issubset(rel), tag)
                for tag in re.findall(r'<(?:a|img|script|link|audio|source)\b[^>]*>', document, re.I):
                    for raw_value in re.findall(r'(?:href|src)="([^"]*)"', tag, re.I):
                        normalized = re.sub(r"[\x00-\x20]+", "", html.unescape(raw_value)).lower()
                        self.assertFalse(
                            normalized.startswith(("javascript:", "vbscript:", "file:")),
                            f"{page}: {tag}",
                        )


if __name__ == "__main__":
    unittest.main()
