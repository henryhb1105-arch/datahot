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
    parse_html_blocks_with_report,
    render_blocks_html,
    sanitize_blocks,
    sanitize_url,
    select_article_media,
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

    def test_void_input_does_not_swallow_article_media_or_table(self):
        body = "这是经过验证的正文内容。" * 45
        markup = f"""
        <header><input type="search" placeholder="Search"></header>
        <article><p>{body}</p>
          <figure><img src="/chart.png" alt="性能趋势图" width="960" height="540">
            <figcaption>吞吐量变化</figcaption></figure>
          <table><tr><th rowspan="2">指标</th><th colspan="2">结果</th></tr>
            <tr><td>延迟</td><td>20 ms</td></tr></table>
        </article>
        """
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        self.assertEqual(report["strategy"], "article")
        self.assertIn("figure", [block["type"] for block in blocks])
        self.assertIn("table", [block["type"] for block in blocks])
        table = next(block for block in blocks if block["type"] == "table")
        self.assertEqual(table["rows"][0]["cells"][0]["rowspan"], 2)
        self.assertEqual(table["rows"][0]["cells"][1]["colspan"], 2)
        rendered = render_blocks_html(blocks)
        self.assertIn('rowspan="2"', rendered)
        self.assertIn('colspan="2"', rendered)

    def test_article_root_wins_over_unrelated_page_copy(self):
        article_text = "正文机制说明和结果数据。" * 45
        unrelated = "相关推荐和页脚噪声。" * 80
        markup = (
            f'<div class="related">{unrelated}</div>'
            f'<article><h1>真正标题</h1><p>{article_text}</p></article>'
        )
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        plain = blocks_plain_text(blocks)
        self.assertEqual(report["strategy"], "article")
        self.assertIn("正文机制说明", plain)
        self.assertNotIn("相关推荐", plain)

    def test_jsonld_article_body_is_used_when_dom_has_no_body_root(self):
        article_body = "JSON-LD 中的可信文章正文。" * 45
        markup = (
            '<html><head><script type="application/ld+json">'
            + json.dumps({"@type": "Article", "articleBody": article_body}, ensure_ascii=False)
            + '</script></head><body><span>短页面</span></body></html>'
        )
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        self.assertEqual(report["strategy"], "jsonld_article_body")
        self.assertIn("可信文章正文", blocks_plain_text(blocks))

    def test_largest_content_container_is_auditable_fallback(self):
        markup = (
            '<div class="promo">很短</div>'
            + '<section class="content-shell"><p>'
            + "主要内容容器中的机制、数字与结论。" * 40
            + '</p></section>'
        )
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        self.assertEqual(report["strategy"], "largest_content")
        self.assertIn("主要内容容器", blocks_plain_text(blocks))

    def test_media_selection_drops_decorations_and_keeps_best_three_in_flow(self):
        blocks = sanitize_blocks([
            {"type": "figure", "src": "https://example.com/logo.svg", "alt": "Company logo"},
            {"type": "figure", "src": "https://example.com/first-chart.png", "alt": "latency chart", "width": 960, "height": 540},
            {"type": "paragraph", "children": [{"type": "text", "text": "正文", "marks": []}]},
            {"type": "figure", "src": "https://example.com/avatar.png", "alt": "author avatar", "width": 500, "height": 500},
            {"type": "figure", "src": "https://example.com/second-diagram.png", "caption": "architecture diagram", "width": 1200, "height": 700},
            {"type": "figure", "src": "https://example.com/third-graph.png", "alt": "cost graph", "width": 800, "height": 450},
            {"type": "figure", "src": "https://example.com/fourth.png", "alt": "plain screenshot", "width": 300, "height": 200},
        ])
        selected, report = select_article_media(blocks, maximum=3)
        urls = [block["src"] for block in selected if block["type"] == "figure"]
        self.assertEqual(urls, [
            "https://example.com/first-chart.png",
            "https://example.com/second-diagram.png",
            "https://example.com/third-graph.png",
        ])
        self.assertEqual(report["figures_selected"], 3)
        self.assertEqual(report["figures_rejected"], 3)

    def test_article_parser_keeps_all_explanatory_figures_by_default(self):
        figures = "".join(
            f'<figure><img src="https://example.com/chart-{index}.png" alt="chart {index}" '
            'width="900" height="500"><figcaption>Result chart</figcaption></figure>'
            for index in range(1, 6)
        )
        markup = '<article><p>' + "完整正文。" * 100 + '</p>' + figures + '</article>'
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        self.assertEqual(sum(block["type"] == "figure" for block in blocks), 5)
        self.assertEqual(report["figures_selected"], 5)
        self.assertEqual(report["figures_rejected"], 0)


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

    def test_figure_copy_is_translated_without_changing_media_address(self):
        figure_blocks = parse_html_blocks(
            '<article><p>' + "足够长的正文。" * 70 + '</p>'
            '<figure><img src="https://example.com/chart.png" alt="Latency chart" '
            'width="960" height="540"><figcaption>Benchmark result</figcaption></figure></article>',
            "https://example.com/post",
        )
        nodes = translation_nodes(figure_blocks)
        translated, stats = apply_translations(
            figure_blocks,
            [{"id": node["id"], "text": "中译：" + node["text"]} for node in nodes],
        )
        figure = next(block for block in translated if block["type"] == "figure")
        self.assertEqual(figure["src"], "https://example.com/chart.png")
        self.assertTrue(figure["caption"].startswith("中译："))
        self.assertTrue(figure["alt"].startswith("中译："))
        self.assertEqual(stats["applied"], len(nodes))

    def test_limit_blocks_can_preserve_figures_and_tables_after_text_budget(self):
        markup = (
            '<article><p>' + "正文很长。" * 120 + '</p>'
            '<figure><img src="https://example.com/chart.png" alt="chart" width="900" height="500"></figure>'
            '<table><tr><th>Metric</th><td>20 ms</td></tr></table></article>'
        )
        blocks = parse_html_blocks(markup, "https://example.com/post")
        limited = limit_blocks(blocks, 30, preserve_types={"figure", "table"})
        self.assertEqual(
            [block["type"] for block in limited if block["type"] in {"figure", "table"}],
            ["figure", "table"],
        )

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
        self.assertTrue(call.call_args.kwargs["strict_object"])
        self.assertEqual(call.call_args.kwargs["max_tokens"], 8000)
        self.assertEqual(stats["applied"], len(nodes))
        self.assertTrue(blocks_plain_text(translated).startswith("译:"))

    def test_pipeline_translation_retries_only_nodes_omitted_by_provider(self):
        nodes = translation_nodes(self.blocks)
        first_response = {
            "nodes": [
                {"id": node["id"], "text": "译:" + node["text"]}
                for node in nodes[:-1]
            ],
        }
        retry_response = {
            "nodes": [{"id": nodes[-1]["id"], "text": "译:" + nodes[-1]["text"]}],
        }
        with patch.object(
            run_update, "llm_chat", side_effect=[first_response, retry_response],
        ) as call:
            translated, stats = run_update.translate_article_blocks(
                self.blocks, ("key", "https://example.test", "model"),
                source="Feed", item_id="event-1",
            )
        self.assertEqual(call.call_count, 2)
        retry_prompt = call.call_args_list[1].args[3]
        self.assertIn(nodes[-1]["id"], retry_prompt)
        self.assertNotIn(nodes[0]["id"], retry_prompt)
        self.assertEqual(stats["retried_nodes"], 1)
        self.assertEqual(stats["retry_batches"], 1)
        self.assertEqual(stats["missing"], 0)
        self.assertTrue(stats["complete"])
        self.assertTrue(blocks_plain_text(translated).startswith("译:"))

    def test_block_translation_budget_includes_one_complete_retry_pass(self):
        nodes = translation_nodes(self.blocks)
        batches = run_update._translation_batches(nodes)
        initial = sum(
            run_update._estimated_llm_tokens(
                run_update._block_translation_prompt(batch, index, len(batches)), 8000,
            )
            for index, batch in enumerate(batches, start=1)
        )
        self.assertGreater(run_update.translation_budget_estimate(self.blocks), initial)

    def test_fetch_article_content_returns_parser_diagnostics_on_request(self):
        markup = (
            '<html><head><title>Example</title></head><body><header><input></header>'
            '<article><p>' + "已校验的文章正文。" * 55 + '</p>'
            '<figure><img src="https://example.com/chart.png" alt="chart" '
            'width="900" height="500"></figure></article></body></html>'
        ).encode()
        with patch.object(run_update, "fetch_url", return_value=markup):
            text, title, _published, blocks, report = run_update.fetch_article_content(
                "https://example.com/post", include_report=True,
            )
        self.assertEqual(title, "Example")
        self.assertGreater(len(text), 400)
        self.assertEqual(report["strategy"], "article")
        self.assertEqual(report["figures"], 1)
        self.assertTrue(any(block["type"] == "figure" for block in blocks))

    def test_event_body_keeps_original_when_translation_is_incomplete(self):
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
        self.assertEqual(body, blocks_plain_text(self.blocks))
        self.assertEqual(event["content_mode"], "original")
        self.assertEqual(event["translation_status"], "failed")
        self.assertIn("content_blocks", event)


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
        article["content_mode"] = "original"
        article["source_language"] = "zh"
        page = build_site.render_detail(article, [article], "")
        self.assertIn("<strong>", page)
        self.assertIn("<blockquote>", page)
        self.assertIn("<table>", page)
        self.assertIn("tone-accent", page)
        self.assertNotIn("javascript:alert", page)
        self.assertNotIn("onclick=\"steal", page)
        self.assertIn(".tone-accent", page)
        self.assertIn("prefers-color-scheme: dark", page)
        self.assertIn('aria-label="原文表格"', page)
        self.assertIn("overscroll-behavior-inline:contain", page)
        self.assertIn("原文正文", page)
        self.assertIn("未经 AI 改写", page)
        self.assertNotIn("全文编译", page)

    def test_detail_page_labels_translation_without_claiming_ai_compilation(self):
        article = self.base_event()
        article["content_blocks"] = parse_html_blocks(SAMPLE_HTML, "https://example.com/post")
        article["content_mode"] = "translated"
        article["source_language"] = "other"
        page = build_site.render_detail(article, [article], "")
        self.assertIn("忠实译文", page)
        self.assertIn("AI 仅逐段翻译", page)
        self.assertNotIn("全文编译", page)

    def test_legacy_fulltext_still_renders_when_blocks_are_missing(self):
        article = self.base_event()
        article["full_zh"] = "## 关键事实\n\n旧版正文仍然可见。"
        page = build_site.render_detail(article, [article], "")
        self.assertIn('<h5 class="fh">关键事实</h5>', page)
        self.assertIn("旧版正文仍然可见。", page)


if __name__ == "__main__":
    unittest.main()
