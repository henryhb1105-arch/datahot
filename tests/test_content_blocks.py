import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from content_blocks import (  # noqa: E402
    apply_translations,
    blocks_plain_text,
    color_token,
    iter_text_nodes,
    limit_blocks,
    parse_html_blocks,
    render_blocks_html,
    sanitize_blocks,
    sanitize_url,
    translation_nodes,
)
import run_update  # noqa: E402
import build_site  # noqa: E402


SAMPLE_HTML = """
<!doctype html><html><head><title>Ignore title</title><script>alert(1)</script></head><body>
<nav>Ignore navigation</nav>
<article onclick="steal()">
  <h1>Platform <strong>Launch</strong></h1>
  <p>Read <strong>important</strong> and <em>carefully</em>.
     <a href="/docs" onclick="bad()">Safe docs</a>
     <a href="javascript:alert(1)">Bad link text</a>
     <span style="color:red;position:fixed">red fact</span></p>
  <ul><li>First <code>SELECT 1</code></li><li>Second</li></ul>
  <blockquote>Quoted <b>claim</b></blockquote>
  <pre class="language-sql">SELECT * FROM users;</pre>
  <table><tr><th>Metric</th><th>Value</th></tr><tr><td>Latency</td><td>20 ms</td></tr></table>
  <iframe src="https://evil.test">evil frame</iframe>
</article>
</body></html>
"""


class ContentBlockParsingTests(unittest.TestCase):
    def test_parser_preserves_supported_structure_and_marks(self):
        blocks = parse_html_blocks(SAMPLE_HTML, "https://example.com/post")
        kinds = [block["type"] for block in blocks]
        self.assertEqual(
            kinds,
            ["heading", "paragraph", "list", "blockquote", "code", "table"],
        )
        heading = blocks[0]
        self.assertEqual(heading["level"], 2)
        self.assertIn("strong", list(iter_text_nodes(heading))[1]["marks"])
        paragraph_nodes = list(iter_text_nodes(blocks[1]))
        safe_link = next(node for node in paragraph_nodes if "Safe docs" in node["text"])
        bad_link = next(node for node in paragraph_nodes if "Bad link" in node["text"])
        red = next(node for node in paragraph_nodes if "red fact" in node["text"])
        self.assertIn(
            {"type": "link", "href": "https://example.com/docs"},
            safe_link["marks"],
        )
        self.assertFalse(any(isinstance(mark, dict) and mark.get("type") == "link" for mark in bad_link["marks"]))
        self.assertIn({"type": "color", "token": "accent"}, red["marks"])
        self.assertEqual(blocks[4]["language"], "sql")
        self.assertNotIn("evil frame", blocks_plain_text(blocks))
        self.assertNotIn("Ignore navigation", blocks_plain_text(blocks))

    def test_ids_are_stable_and_json_serializable(self):
        first = parse_html_blocks(SAMPLE_HTML, "https://example.com/post")
        second = parse_html_blocks(SAMPLE_HTML, "https://example.com/post")
        self.assertEqual(first, second)
        self.assertTrue(all(block["id"].startswith("b-") for block in first))
        self.assertTrue(all(node["id"].startswith("t-") for node in iter_text_nodes(first)))
        json.dumps(first, ensure_ascii=False)

    def test_sanitizer_rejects_dangerous_protocols_and_unknown_shapes(self):
        raw = [
            {
                "type": "paragraph",
                "id": "not-safe",
                "onclick": "steal()",
                "children": [{
                    "type": "text",
                    "text": "click",
                    "marks": [
                        {"type": "link", "href": "javascript:alert(1)"},
                        {"type": "color", "token": "hotpink"},
                    ],
                }],
            },
            {"type": "script", "text": "evil"},
        ]
        cleaned = sanitize_blocks(raw, "https://example.com")
        self.assertEqual(len(cleaned), 1)
        node = next(iter_text_nodes(cleaned[0]))
        self.assertEqual(node["marks"], [{"type": "color", "token": "emphasis"}])
        rendered = render_blocks_html(cleaned)
        self.assertNotIn("javascript:", rendered)
        self.assertNotIn("onclick", rendered)
        self.assertNotIn("<script", rendered)
        self.assertEqual(sanitize_url("data:text/html,evil"), "")

    def test_third_party_colors_map_to_semantic_tokens(self):
        self.assertEqual(color_token("color: #fff"), "emphasis")
        self.assertEqual(color_token("rgb(0, 87, 255)"), "info")
        self.assertEqual(color_token("#0a8f44"), "positive")


class ContentBlockTranslationTests(unittest.TestCase):
    def setUp(self):
        self.blocks = parse_html_blocks(SAMPLE_HTML, "https://example.com/post")

    def test_translation_changes_only_text_and_preserves_ids_and_marks(self):
        original_block_ids = [block["id"] for block in self.blocks]
        original_marks = {
            node["id"]: node["marks"] for node in iter_text_nodes(self.blocks)
        }
        nodes = translation_nodes(self.blocks)
        translated_payload = [
            {"id": node["id"], "text": "中:" + node["text"]}
            for node in nodes
        ] + [{"id": "t-aaaaaaaaaaaa", "text": "injected"}]
        translated, stats = apply_translations(self.blocks, translated_payload)
        self.assertEqual([block["id"] for block in translated], original_block_ids)
        self.assertEqual(
            {node["id"]: node["marks"] for node in iter_text_nodes(translated)},
            original_marks,
        )
        self.assertEqual(stats["applied"], len(nodes))
        self.assertEqual(stats["ignored"], 1)
        self.assertNotIn("injected", blocks_plain_text(translated))

    def test_translated_markup_is_escaped_by_renderer(self):
        node = translation_nodes(self.blocks)[0]
        translated, _ = apply_translations(
            self.blocks,
            [{"id": node["id"], "text": '<img src=x onerror="bad()">'}],
        )
        rendered = render_blocks_html(translated)
        self.assertIn("&lt;img", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn("onerror=\"bad()\"", rendered)

    def test_limit_blocks_keeps_valid_structure(self):
        limited = limit_blocks(self.blocks, 80)
        self.assertLessEqual(len(blocks_plain_text(limited)), 100)
        self.assertTrue(all(block["type"] in {"heading", "paragraph", "list", "blockquote", "code", "table", "figure"} for block in limited))

    def test_pipeline_translation_sends_only_id_and_text_nodes(self):
        nodes = translation_nodes(limit_blocks(self.blocks, 5000))
        response = {"nodes": [{"id": node["id"], "text": "译:" + node["text"]} for node in nodes]}
        with patch.object(run_update, "llm_chat", return_value=response) as call:
            translated, stats = run_update.translate_article_blocks(
                self.blocks,
                ("key", "https://example.test", "model"),
                source="Feed", item_id="event-1", deep=True,
            )
        prompt = call.call_args.args[3]
        self.assertNotIn("<strong>", prompt)
        self.assertNotIn("onclick", prompt)
        self.assertIn('"id":"t-', prompt)
        self.assertEqual(stats["applied"], len(nodes))
        self.assertTrue(blocks_plain_text(translated).startswith("译:"))

    def test_event_body_degrades_when_no_translation_node_is_applied(self):
        primary = {
            "article_text": blocks_plain_text(self.blocks),
            "article_blocks": self.blocks,
            "source": "Feed",
            "link": "https://example.com/post",
        }
        event = {
            "event_id": "event-1",
            "zh_title": "结构化正文",
            "zh_summary": "可用摘要",
            "importance": 60,
        }
        with patch.object(
            run_update,
            "translate_article_blocks",
            return_value=(self.blocks, {"applied": 0, "ignored": 0, "missing": 1}),
        ):
            body = run_update.generate_event_body(
                event, primary,
                ("key", "https://example.test", "model"),
                {"deep_used": 0, "max_deep": 2},
            )
        self.assertEqual(body, "可用摘要")
        self.assertEqual(event["content_level"], "summary")
        self.assertNotIn("content_blocks", event)


class ContentBlockRenderingTests(unittest.TestCase):
    def base_event(self):
        return {
            "event_id": "event-1",
            "zh_title": "结构化正文测试",
            "zh_summary": "摘要",
            "reason": "推荐理由",
            "full_zh": "",
            "category": "platform",
            "category_label": "AI 数据平台",
            "vendors": [],
            "topics": [],
            "heat": 60,
            "importance": 60,
            "signal": 0,
            "shelf": "news",
            "published": "2026-08-11T12:00:00+08:00",
            "first_seen": "2026-08-11T12:00:00+08:00",
            "items": [{
                "id": "source-1",
                "source": "Databricks Blog",
                "link": "https://example.com/post",
                "published": "2026-08-11T12:00:00+08:00",
                "title": "Source title",
            }],
        }

    def test_detail_page_renders_safe_structured_blocks(self):
        article = self.base_event()
        article["content_blocks"] = parse_html_blocks(SAMPLE_HTML, "https://example.com/post")
        page = build_site.render_detail(article, [article], "")
        self.assertIn("<strong>", page)
        self.assertIn("<blockquote>", page)
        self.assertIn("<table>", page)
        self.assertIn("tone-accent", page)
        self.assertNotIn("javascript:alert", page)
        self.assertNotIn("onclick=\"steal", page)
        self.assertIn(".tone-accent", page)
        self.assertIn("prefers-color-scheme: dark", page)

    def test_legacy_fulltext_still_renders_when_blocks_are_missing(self):
        article = self.base_event()
        article["full_zh"] = "## 关键事实\n\n旧版正文仍然可见。"
        page = build_site.render_detail(article, [article], "")
        self.assertIn('<h5 class="fh">关键事实</h5>', page)
        self.assertIn("旧版正文仍然可见。", page)


if __name__ == "__main__":
    unittest.main()
