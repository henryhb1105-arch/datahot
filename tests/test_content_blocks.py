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
    strip_article_ui_chrome,
    trim_article_blocks,
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

    def test_parser_excludes_audio_elements_and_semantic_player_widgets(self):
        body = "Measured database facts, constraints, and benchmark results. " * 35
        markup = f"""
        <article>
          <div class="articleAudioPlayer">
            <div><p>Listen to this article - 0:00</p></div>
            <p>Audio is ready to play</p>
            <audio controls><source src="story.mp3">Your browser does not support the audio element.</audio>
            <p>0:00</p><p>0:00</p><a href="/showbookmarks.action">Reading list</a>
          </div>
          <p>{body}</p>
        </article>
        """
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        plain = blocks_plain_text(blocks)
        self.assertEqual(report["strategy"], "article")
        self.assertIn("Measured database facts", plain)
        self.assertNotIn("Listen to this article", plain)
        self.assertNotIn("browser does not support", plain)
        self.assertNotIn("Reading list", plain)

    def test_parser_excludes_nested_recirculation_components_without_visible_labels(self):
        body = "Verified article facts, constraints, and measured results. " * 35
        markup = f"""
        <article>
          <p>{body}</p>
          <div class="related-content">
            <h2>A neighboring article title</h2>
            <p>This card is not part of the article body.</p>
          </div>
          <section data-component="newsletter-signup">
            <p>Weekly product updates</p>
          </section>
        </article>
        """
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        plain = blocks_plain_text(blocks)
        self.assertEqual(report["strategy"], "article")
        self.assertIn("Verified article facts", plain)
        self.assertNotIn("neighboring article", plain)
        self.assertNotIn("Weekly product updates", plain)

    def test_flattened_player_cluster_is_removed_without_keyword_deletion(self):
        def paragraph(text, href=""):
            marks = [{"type": "link", "href": href}] if href else []
            return {
                "type": "paragraph",
                "children": [{"type": "text", "text": text, "marks": marks}],
            }

        polluted = [
            paragraph("收听本文 - 0:00"),
            paragraph("音频已准备好播放"),
            paragraph(" 您的浏览器不支持音频元素。 "),
            paragraph("0:00"),
            paragraph("0:00"),
            {"type": "list", "ordered": False, "items": [{"children": [{
                "type": "text", "text": "阅读列表", "marks": [{
                    "type": "link", "href": "https://example.com/showbookmarks.action",
                }],
            }]}]},
            paragraph("Amazon DynamoDB 的向量搜索正文事实。" * 45),
            paragraph("本文讨论音频播放器的可访问性，但这是真实正文。"),
        ]
        cleaned, report = strip_article_ui_chrome(polluted)
        plain = blocks_plain_text(cleaned)
        self.assertEqual(report["trimmed_embedded_ui_blocks"], 6)
        self.assertEqual(report["embedded_ui_components"], 1)
        self.assertTrue(plain.startswith("Amazon DynamoDB"))
        self.assertIn("音频播放器的可访问性", plain)
        self.assertNotIn("浏览器不支持音频元素", plain)
        self.assertNotIn("阅读列表", plain)

    def test_isolated_audio_phrase_in_article_is_not_removed(self):
        blocks = sanitize_blocks([{
            "type": "paragraph",
            "children": [{
                "type": "text",
                "text": "The accessibility test checks whether your browser does not support the audio element.",
                "marks": [],
            }],
        }, {
            "type": "paragraph",
            "children": [{
                "type": "text", "text": "This is explanatory article prose. " * 30, "marks": [],
            }],
        }])
        cleaned, report = strip_article_ui_chrome(blocks)
        self.assertEqual(report["trimmed_embedded_ui_blocks"], 0)
        self.assertIn("accessibility test", blocks_plain_text(cleaned))

    def test_sanitizer_drops_whitespace_only_blocks_but_keeps_inline_spaces(self):
        cleaned = sanitize_blocks([{
            "type": "paragraph",
            "children": [{"type": "text", "text": "   ", "marks": []}],
        }, {
            "type": "paragraph",
            "children": [
                {"type": "text", "text": "Fact", "marks": ["strong"]},
                {"type": "text", "text": " ", "marks": []},
                {"type": "text", "text": "continues", "marks": ["em"]},
            ],
        }])
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(blocks_plain_text(cleaned), "Fact continues")

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

    def test_focused_semantic_body_beats_broad_main_with_source_site_chrome(self):
        article_text = "Financial workflow facts and concrete benchmark results. " * 45
        related = "Related card copy, pricing, newsletter and navigation. " * 90
        markup = f"""
        <main class="page_main">
          <section class="hero"><h1>Story title</h1><p>Story deck</p></section>
          <div class="u-rich-text-blog"><h2>Actual article</h2><p>{article_text}</p></div>
          <section class="related"><h2>Related posts</h2><p>{related}</p></section>
        </main>
        """
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        plain = blocks_plain_text(blocks)
        self.assertEqual(report["strategy"], "semantic_container")
        self.assertEqual(report["quality_status"], "pass")
        self.assertGreaterEqual(report["candidate_count"], 2)
        self.assertIn("Financial workflow facts", plain)
        self.assertNotIn("Related card copy", plain)

    def test_nested_prose_core_beats_a_broad_main_without_semantic_classes(self):
        intro = "Authoritative agent facts, operating constraints, and measured results. " * 18
        section = "Trusted data, governed context, and bounded autonomy are required. " * 18
        promo = (
            '<p>The data leader primer: <a href="/resources/agent-guide">'
            'Download the guide and start building agents.</a></p>'
        )
        markup = f"""
        <main class="relative flex min-h-screen flex-col">
          <p><a href="/blog">Blog</a></p><p> / <a href="/insights">Insights</a></p>
          <p> / Why agent projects fail</p><h1>Why agent projects fail</h1>
          <figure><img src="/authors/daniel.jpg" width="512" height="512" alt=""></figure>
          <p><a href="/authors/daniel">Daniel Poppy</a> Last edited on Aug 14, 2026</p>
          <div class="star-mb-6 star-last-mb-0">
            <p>{intro}</p>{promo}<h2>Why trusted data matters</h2>
            <p>{section}</p>{promo}<h2>Build an agent you can trust</h2>
            <p>{section}</p>{promo}<p>Use staged autonomy and explicit approval boundaries.</p>
          </div>
          <div class="right-rail"><h3>Get started in dbt</h3><p>Join the analytics engineers.</p>
            <h3>Install dbt Wizard CLI</h3><p>Install the product.</p><h4>Share this article</h4></div>
          <section><h3>Latest posts</h3><p>Product 11 min</p><h3>Another article</h3>
            <p>Daniel Poppy</p><p>on Aug 14, 2026</p></section>
        </main>
        """
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        plain = blocks_plain_text(blocks)
        self.assertEqual(report["strategy"], "nested_content")
        self.assertEqual(report["quality_status"], "pass")
        self.assertGreaterEqual(report["candidate_count"], 1)
        self.assertGreaterEqual(report["candidate_count_raw"], 2)
        self.assertGreaterEqual(report["candidate_duplicates"], 1)
        self.assertIn("nested_focus", report["selection_evidence"])
        self.assertEqual(report["trimmed_promotional_blocks"], 3)
        self.assertTrue(plain.startswith("Authoritative agent facts"))
        self.assertIn("Use staged autonomy", plain)
        for pollution in (
            "Blog", "Why agent projects fail", "Daniel Poppy", "Download the guide",
            "Get started in dbt", "Share this article", "Latest posts", "Another article",
        ):
            self.assertNotIn(pollution, plain)
        self.assertEqual(report["figures_selected"], 0)

    def test_first_class_token_is_recognized_as_semantic_article_content(self):
        body = "Trusted source facts, chronology, and measured results. " * 40
        markup = f'<div class="article-content"><p>{body}</p></div>'
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        self.assertEqual(report["strategy"], "semantic_container")
        self.assertIn("Trusted source facts", blocks_plain_text(blocks))

    def test_noisy_article_list_class_cannot_outrank_a_real_article(self):
        noise = "Related card headline and marketing description. " * 120
        body = "Actual source facts, chronology, and measured results. " * 35
        markup = (
            f'<div class="article-list"><p>{noise}</p></div>'
            f'<article><p>{body}</p></article>'
        )
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        plain = blocks_plain_text(blocks)
        self.assertEqual(report["strategy"], "article")
        self.assertIn("Actual source facts", plain)
        self.assertNotIn("Related card headline", plain)

    def test_pass_candidate_wins_and_suspect_candidate_is_audited(self):
        noise = "Pricing links and marketing navigation. " * 120
        body = "Audited article facts and measured evidence. " * 28
        markup = (
            f'<div class="article-content"><p>View pricing</p><p>{noise}</p></div>'
            f'<article><p>{body}</p></article>'
        )
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        self.assertEqual(report["strategy"], "article")
        self.assertEqual(report["quality_status"], "pass")
        self.assertGreaterEqual(report["candidate_quality_rejected"], 1)
        self.assertNotIn("View pricing", blocks_plain_text(blocks))

    def test_block_cleanup_handles_breadcrumb_byline_repeated_promos_and_tail_cluster(self):
        def paragraph(text, href=""):
            marks = [{"type": "link", "href": href}] if href else []
            return {"type": "paragraph", "children": [{"type": "text", "text": text, "marks": marks}]}

        promo_href = "https://example.com/resources/agent-guide"
        blocks = sanitize_blocks([
            paragraph("博客", "https://example.com/blog"),
            paragraph(" / 洞察", "https://example.com/insights"),
            paragraph(" / 为什么智能体项目失败"),
            {"type": "heading", "level": 2, "children": [{"type": "text", "text": "为什么智能体项目失败", "marks": []}]},
            {"type": "figure", "src": "https://example.com/daniel.jpg", "alt": "", "caption": "", "width": 512, "height": 512},
            paragraph("Daniel Poppy 最后编辑于2026年8月14日", "https://example.com/authors/daniel"),
            paragraph("可信正文第一段。" * 70),
            paragraph("下载指南，开始构建智能体。", promo_href),
            {"type": "heading", "level": 2, "children": [{"type": "text", "text": "可信数据为何重要", "marks": []}]},
            paragraph("可信正文第二段。" * 70),
            paragraph("下载指南，开始构建智能体。", promo_href),
            {"type": "heading", "level": 3, "children": [{"type": "text", "text": "在 dbt 中开始", "marks": []}]},
            paragraph("安装产品。", "https://example.com/install"),
            {"type": "heading", "level": 4, "children": [{"type": "text", "text": "分享本文", "marks": []}]},
            {"type": "heading", "level": 3, "children": [{"type": "text", "text": "最新文章", "marks": []}]},
        ])
        trimmed, quality = trim_article_blocks(blocks)
        plain = blocks_plain_text(trimmed)
        self.assertTrue(plain.startswith("可信正文第一段"))
        self.assertIn("可信正文第二段", plain)
        self.assertNotIn("下载指南", plain)
        self.assertNotIn("在 dbt 中开始", plain)
        self.assertEqual(quality["trimmed_head_blocks"], 6)
        self.assertEqual(quality["trimmed_promotional_blocks"], 2)
        self.assertGreaterEqual(quality["trimmed_tail_blocks"], 4)
        self.assertEqual(quality["quality_status"], "pass")

    def test_flat_page_header_and_article_component_tail_are_cut_as_boundaries(self):
        def paragraph(text, href=""):
            marks = [{"type": "link", "href": href}] if href else []
            return {
                "type": "paragraph",
                "children": [{"type": "text", "text": text, "marks": marks}],
            }

        title = "通用 Agent 进了企业，Data Agent 还要不要单独买？"
        blocks = sanitize_blocks([
            paragraph("产品 解决方案 客户案例 资源中心", "https://example.com/nav"),
            paragraph("首页 > NoETL 博客 > " + title, "https://example.com/blog"),
            {"type": "heading", "level": 2, "children": [
                {"type": "text", "text": title, "marks": []},
            ]},
            paragraph("作者：周卫林 2026-08-19 | NoETL 博客"),
            paragraph("可信正文事实、推理过程与结论。" * 90),
            paragraph("下一篇"),
            paragraph("另一个文章标题", "https://example.com/next"),
            paragraph("相关博客"),
            paragraph("相关文章卡片", "https://example.com/related"),
        ])

        trimmed, quality = trim_article_blocks(blocks)
        second, second_quality = trim_article_blocks(trimmed)
        plain = blocks_plain_text(trimmed)

        self.assertTrue(plain.startswith("可信正文事实"))
        self.assertNotIn("下一篇", plain)
        self.assertNotIn("相关博客", plain)
        self.assertEqual(quality["trimmed_head_blocks"], 4)
        self.assertEqual(quality["trimmed_tail_blocks"], 4)
        self.assertEqual(quality["boundary_marker"], "下一篇")
        self.assertEqual(second, trimmed)
        self.assertEqual(second_quality["trimmed_head_blocks"], 0)
        self.assertEqual(second_quality["trimmed_tail_blocks"], 0)

    def test_focused_article_title_and_byline_are_not_rendered_as_body(self):
        def paragraph(text, href=""):
            marks = [{"type": "link", "href": href}] if href else []
            return {
                "type": "paragraph",
                "children": [{"type": "text", "text": text, "marks": marks}],
            }

        blocks = sanitize_blocks([
            {"type": "heading", "level": 2, "children": [{
                "type": "text",
                "text": "通用 Agent 进了企业，Data Agent 还要不要单独买？",
                "marks": [],
            }]},
            paragraph("作者：周卫林2026-08-19|NoETL 博客", "https://example.com/blog"),
            paragraph("今年春节前后，OpenClaw 爆火，我们围绕它做了两次实验。" * 20),
        ])

        trimmed, quality = trim_article_blocks(blocks)
        second, second_quality = trim_article_blocks(trimmed)

        self.assertTrue(blocks_plain_text(trimmed).startswith("今年春节前后"))
        self.assertNotIn("作者：周卫林", blocks_plain_text(trimmed))
        self.assertNotIn("NoETL 博客", blocks_plain_text(trimmed))
        self.assertEqual(quality["trimmed_head_blocks"], 2)
        self.assertEqual(second, trimmed)
        self.assertEqual(second_quality["trimmed_head_blocks"], 0)

    def test_opening_heading_is_kept_without_an_explicit_byline(self):
        blocks = sanitize_blocks([
            {"type": "heading", "level": 2, "children": [{
                "type": "text", "text": "作者如何建立可信分析流程", "marks": [],
            }]},
            {"type": "paragraph", "children": [{
                "type": "text",
                "text": "作者认为分析过程必须透明，这段话属于正文。" * 30,
                "marks": [],
            }]},
        ])

        trimmed, quality = trim_article_blocks(blocks)

        self.assertTrue(blocks_plain_text(trimmed).startswith("作者如何建立可信分析流程"))
        self.assertEqual(quality["trimmed_head_blocks"], 0)

    def test_split_byline_dateline_and_subscribe_control_are_removed_together(self):
        def paragraph(text):
            return {
                "type": "paragraph",
                "children": [{"type": "text", "text": text, "marks": []}],
            }

        blocks = sanitize_blocks([
            {"type": "heading", "level": 2, "children": [{
                "type": "text", "text": "SQL 形态的意图", "marks": [],
            }]},
            paragraph("作者：Dushyant Bansal，ThoughtSpot 工程总监"),
            paragraph("发布于"),
            paragraph("订阅"),
            {"type": "figure", "src": "https://example.com/hero.png", "alt": "架构图"},
            paragraph("我们的团队花了近一年时间构建新的查询能力。" * 30),
        ])

        trimmed, quality = trim_article_blocks(blocks)
        plain = blocks_plain_text(trimmed)

        self.assertNotIn("作者：", plain)
        self.assertNotIn("发布于", plain)
        self.assertNotIn("订阅", plain)
        self.assertEqual(trimmed[0]["type"], "figure")
        self.assertEqual(quality["trimmed_head_blocks"], 4)

    def test_head_share_controls_end_before_body_but_publish_word_in_prose_is_kept(self):
        def paragraph(text):
            return {
                "type": "paragraph",
                "children": [{"type": "text", "text": text, "marks": []}],
            }

        blocks = sanitize_blocks([
            paragraph("所有帖子"),
            paragraph("2026年8月12日，在新闻"),
            {"type": "heading", "level": 2, "children": [
                {"type": "text", "text": "安全版本发布公告", "marks": []},
            ]},
            {"type": "heading", "level": 3, "children": [
                {"type": "text", "text": "作者姓名", "marks": []},
            ]},
            {"type": "heading", "level": 3, "children": [
                {"type": "text", "text": "分享本文", "marks": []},
            ]},
            paragraph("已复制到剪贴板"),
            paragraph("产品发布于 2023 年，随后持续完善治理能力。" * 30),
        ])

        trimmed, quality = trim_article_blocks(blocks)
        second, _second_quality = trim_article_blocks(trimmed)
        plain = blocks_plain_text(trimmed)

        self.assertEqual(quality["trimmed_head_blocks"], 6)
        self.assertTrue(plain.startswith("产品发布于 2023 年"))
        self.assertEqual(second, trimmed)

    def test_non_component_sentence_containing_next_article_words_is_preserved(self):
        blocks = sanitize_blocks([
            {"type": "paragraph", "children": [{
                "type": "text", "text": "可信正文事实。" * 90, "marks": [],
            }]},
            {"type": "paragraph", "children": [{
                "type": "text", "text": "下一篇分析会继续解释这一机制。", "marks": [],
            }]},
        ])
        trimmed, quality = trim_article_blocks(blocks)
        self.assertIn("下一篇分析会继续解释", blocks_plain_text(trimmed))
        self.assertEqual(quality["trimmed_tail_blocks"], 0)

    def test_head_metadata_deep_after_a_hero_carousel_starts_the_real_body(self):
        def paragraph(text):
            return {"type": "paragraph", "children": [{"type": "text", "text": text, "marks": []}]}

        blocks = [
            paragraph("客户案例：Example"),
            {"type": "figure", "src": "https://example.com/hero.jpg", "alt": "", "caption": ""},
            paragraph("94%"), paragraph("了解更多"), paragraph("了解更多"),
            paragraph("下一页"), paragraph("客户案例：Example"), paragraph("70%"),
            paragraph("了解更多"), paragraph("下一页"),
            {"type": "heading", "level": 2, "children": [{"type": "text", "text": "Example 如何提升生产力", "marks": []}]},
            paragraph("文章导语。"),
            {"type": "list", "ordered": False, "items": [
                {"children": [{"type": "text", "text": value, "marks": []}]}
                for value in ("类别：企业AI", "产品：Example", "日期：2026年8月16日", "阅读时间：5分钟", "分享复制链接")
            ]},
            paragraph("可信正文事实、方法与结果。" * 80),
        ]
        trimmed, quality = trim_article_blocks(blocks)
        self.assertTrue(blocks_plain_text(trimmed).startswith("可信正文事实"))
        self.assertEqual(quality["trimmed_head_blocks"], 13)

    def test_get_started_heading_inside_article_is_not_a_tail_without_ui_evidence(self):
        blocks = sanitize_blocks([
            {"type": "paragraph", "children": [{"type": "text", "text": "API 设计正文。" * 80, "marks": []}]},
            {"type": "heading", "level": 2, "children": [{"type": "text", "text": "Get started with the API", "marks": []}]},
            {"type": "paragraph", "children": [{"type": "text", "text": "Create a token, call the endpoint, and verify the response. " * 20, "marks": []}]},
        ])
        trimmed, quality = trim_article_blocks(blocks)
        self.assertIn("Get started with the API", blocks_plain_text(trimmed))
        self.assertEqual(quality["trimmed_tail_blocks"], 0)

    def test_linked_terminal_conversion_cta_is_removed_without_matching_body_copy(self):
        blocks = sanitize_blocks([
            {"type": "paragraph", "children": [{"type": "text", "text": "可信正文事实。" * 90, "marks": []}]},
            {"type": "paragraph", "children": [
                {"type": "text", "text": "Get started with ", "marks": ["em"]},
                {"type": "text", "text": "Example Cloud", "marks": [
                    {"type": "link", "href": "https://example.com/product"}, "em",
                ]},
                {"type": "text", "text": " today.", "marks": ["em"]},
            ]},
        ])
        trimmed, quality = trim_article_blocks(blocks)
        self.assertNotIn("Get started", blocks_plain_text(trimmed))
        self.assertEqual(quality["trimmed_promotional_blocks"], 1)
        self.assertIn("terminal_promotion_removed", quality["quality_evidence"])

    def test_unlinked_terminal_get_started_sentence_is_preserved(self):
        blocks = sanitize_blocks([
            {"type": "paragraph", "children": [{"type": "text", "text": "可信正文事实。" * 90, "marks": []}]},
            {"type": "paragraph", "children": [{"type": "text", "text": "Get started with the API today.", "marks": []}]},
        ])
        trimmed, quality = trim_article_blocks(blocks)
        self.assertIn("Get started with the API today.", blocks_plain_text(trimmed))
        self.assertEqual(quality["trimmed_promotional_blocks"], 0)

    def test_tail_boundary_trims_related_ui_after_meaningful_article(self):
        article_text = "正文事实、方法和结果。" * 70
        markup = (
            f'<article><h1>标题</h1><p>{article_text}</p>'
            '<p>未找到项目。</p><p>上一页</p><p>0/5</p>'
            '<h2>相关文章</h2><p>推荐卡片</p></article>'
        )
        blocks, report = parse_html_blocks_with_report(markup, "https://example.com/post")
        plain = blocks_plain_text(blocks)
        self.assertEqual(report["strategy"], "article")
        self.assertEqual(report["quality_status"], "pass")
        self.assertEqual(report["boundary_marker"], "未找到项目。")
        self.assertEqual(report["trimmed_tail_blocks"], 5)
        self.assertNotIn("未找到项目", plain)
        self.assertNotIn("推荐卡片", plain)

    def test_persisted_translated_blocks_use_the_same_tail_boundary(self):
        blocks = sanitize_blocks([
            {"type": "paragraph", "children": [{"type": "text", "text": "可信正文。" * 90, "marks": []}]},
            {"type": "paragraph", "children": [{"type": "text", "text": "未找到项目。", "marks": []}]},
            {"type": "heading", "level": 2, "children": [{"type": "text", "text": "相关文章", "marks": []}]},
        ])
        trimmed, quality = trim_article_blocks(blocks)
        self.assertEqual(len(trimmed), 1)
        self.assertEqual(quality["trimmed_tail_blocks"], 2)
        self.assertEqual(quality["quality_status"], "pass")

    def test_article_title_deck_and_metadata_are_removed_before_body(self):
        blocks = sanitize_blocks([
            {"type": "heading", "level": 1, "children": [{"type": "text", "text": "重复标题", "marks": []}]},
            {"type": "paragraph", "children": [{"type": "text", "text": "重复导语", "marks": []}]},
            {"type": "list", "ordered": False, "items": [
                {"children": [{"type": "text", "text": value, "marks": []}]}
                for value in ("类别：企业 AI", "产品：Claude", "日期：2026 年 5 月 22 日", "阅读时间：5 分钟", "分享复制链接")
            ]},
            {"type": "paragraph", "children": [{"type": "text", "text": "正文第一段。" * 90, "marks": []}]},
        ])
        trimmed, quality = trim_article_blocks(blocks)
        self.assertEqual(len(trimmed), 1)
        self.assertTrue(blocks_plain_text(trimmed).startswith("正文第一段"))
        self.assertEqual(quality["trimmed_head_blocks"], 3)

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

    def test_media_selection_uses_author_context_for_blank_square_portraits(self):
        blocks = sanitize_blocks([
            {"type": "figure", "src": "https://example.com/person.jpg", "alt": "", "caption": "", "width": 512, "height": 512},
            {"type": "paragraph", "children": [{"type": "text", "text": "Daniel Poppy Last edited on Aug 14, 2026", "marks": []}]},
            {"type": "paragraph", "children": [{"type": "text", "text": "Measured article facts. " * 40, "marks": []}]},
            {"type": "figure", "src": "https://example.com/results.png", "alt": "Latency benchmark chart", "caption": "Measured results", "width": 960, "height": 540},
        ])
        selected, report = select_article_media(blocks)
        urls = [block["src"] for block in selected if block["type"] == "figure"]
        self.assertEqual(urls, ["https://example.com/results.png"])
        self.assertEqual(report["figures_rejected_author"], 1)

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

    def test_translation_completeness_ignores_blank_source_nodes(self):
        blocks = sanitize_blocks([
            {
                "type": "paragraph",
                "children": [
                    {"type": "text", "text": "English fact", "marks": []},
                    {"type": "text", "text": "   ", "marks": [{"type": "strong"}]},
                ],
            },
        ])
        nodes = translation_nodes(blocks)
        self.assertEqual(len(nodes), 1)
        _translated, stats = apply_translations(
            blocks, [{"id": nodes[0]["id"], "text": "英文事实"}],
        )
        self.assertEqual(stats, {"applied": 1, "ignored": 0, "missing": 0})

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

    def test_fetch_article_content_blocks_a_suspect_body(self):
        markup = (
            '<html><body><article><p>View pricing</p><p>'
            + "Long source copy with facts and benchmark numbers. " * 30
            + '</p></article></body></html>'
        ).encode()
        with patch.object(run_update, "fetch_url", return_value=markup):
            text, _title, _published, blocks, report = run_update.fetch_article_content(
                "https://example.com/post", include_report=True,
            )
        self.assertEqual(text, "")
        self.assertEqual(blocks, [])
        self.assertEqual(report["quality_status"], "suspect")
        self.assertEqual(report["fallback_reason"], "content_quality_suspect")

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
        self.assertIn(" 原文</h2>", page)
        self.assertIn('class="content-section"', page)
        self.assertNotIn('class="card content-card"', page)
        self.assertIn('<details class="article-brief" open>', page)
        self.assertIn('<summary>DataHot 速览</summary>', page)
        self.assertIn("max-width:700px", page)
        self.assertIn("font-size:16px;line-height:1.86", page)
        self.assertNotIn("原文正文", page)
        self.assertNotIn("未经 AI 改写", page)
        self.assertNotIn('class="content-origin-badge"></span>', page)
        self.assertIn('data-smart-back aria-label="返回"', page)
        self.assertIn('<span class="back-label">返回</span>', page)
        self.assertIn('href="../index.html" data-smart-back', page)
        self.assertIn('src="../detail.js"', page)
        self.assertNotIn("返回热榜", page)
        self.assertNotIn("全文编译", page)

    def test_detail_page_labels_translation_without_claiming_ai_compilation(self):
        article = self.base_event()
        article["content_blocks"] = parse_html_blocks(SAMPLE_HTML, "https://example.com/post")
        article["content_mode"] = "translated"
        article["source_language"] = "other"
        page = build_site.render_detail(article, [article], "")
        self.assertIn(" 译文</h2>", page)
        self.assertIn('<span class="content-origin-badge">AI 逐段翻译</span>', page)
        self.assertIn("AI 逐段翻译", page)
        self.assertNotIn('忠实译文 <span class="content-origin-badge">', page)
        self.assertNotIn("AI 仅逐段翻译 · 未总结重组", page)
        self.assertNotIn("全文编译", page)

    def test_untranslated_original_uses_the_same_compact_original_heading(self):
        article = self.base_event()
        article["content_blocks"] = parse_html_blocks(SAMPLE_HTML, "https://example.com/post")
        article["content_mode"] = "original"
        article["source_language"] = "other"
        page = build_site.render_detail(article, [article], "")
        self.assertIn(" 原文</h2>", page)
        self.assertNotIn("原文正文（未翻译）", page)
        self.assertNotIn("翻译暂不可用 · 保留原文", page)
        self.assertNotIn('class="content-origin-badge"></span>', page)

    def test_legacy_fulltext_still_renders_when_blocks_are_missing(self):
        article = self.base_event()
        article["full_zh"] = "## 关键事实\n\n旧版正文仍然可见。"
        page = build_site.render_detail(article, [article], "")
        self.assertIn('<h5 class="fh">关键事实</h5>', page)
        self.assertIn("旧版正文仍然可见。", page)

    def test_detail_rendering_trims_persisted_source_site_tail(self):
        article = self.base_event()
        article["content_mode"] = "translated"
        article["source_language"] = "other"
        article["content_blocks"] = sanitize_blocks([
            {
                "type": "paragraph",
                "children": [{"type": "text", "text": "可信译文。" * 100, "marks": []}],
            },
            {
                "type": "paragraph",
                "children": [{"type": "text", "text": "未找到项目。", "marks": []}],
            },
            {
                "type": "heading", "level": 2,
                "children": [{"type": "text", "text": "相关文章", "marks": []}],
            },
        ])
        page = build_site.render_detail(article, [article], "")
        self.assertIn("可信译文", page)
        self.assertNotIn("未找到项目", page)
        self.assertNotIn("相关文章", page)
        meta = page.split('<div class="meta">', 1)[1].split("</div>", 1)[0]
        self.assertNotIn("heatnum", meta)


if __name__ == "__main__":
    unittest.main()
