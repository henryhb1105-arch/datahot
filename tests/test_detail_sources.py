import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402


def source_item(item_id, source, link, title, published):
    return {
        "id": item_id,
        "source": source,
        "link": link,
        "title": title,
        "published": published,
    }


def detail_event(items, *, primary_item_id=None):
    event = {
        "event_id": "source-test",
        "zh_title": "来源展示测试",
        "zh_summary": "摘要",
        "reason": "",
        "full_zh": "正文",
        "category": "platform",
        "category_label": "AI 数据平台",
        "vendors": [],
        "topics": [],
        "heat": 60,
        "importance": 60,
        "signal": 0,
        "shelf": "news",
        "published": "2026-08-12T10:00:00+08:00",
        "first_seen": "2026-08-12T10:00:00+08:00",
        "items": items,
    }
    if primary_item_id:
        event["primary_item_id"] = primary_item_id
    return event


class DetailSourceRenderingTests(unittest.TestCase):
    def test_single_report_has_only_top_primary_source(self):
        item = source_item(
            "primary", "AWS Big Data Blog", "https://example.com/primary",
            "Primary report", "2026-08-12T10:00:00+08:00",
        )
        page = build_site.render_detail(detail_event([item]), [detail_event([item])], "")

        self.assertIn(
            'class="original-footer-link" href="https://example.com/primary"', page,
        )
        self.assertIn(
            'class="meta-source-link" href="https://example.com/primary"', page,
        )
        self.assertIn('<span class="meta-content-mode">历史编译稿</span>', page)
        self.assertIn('<span>查看原文</span>', page)
        self.assertNotIn('class="meta-original"', page)
        self.assertNotIn("补充来源", page)
        self.assertNotIn('class="source-section"', page)
        self.assertNotIn("家报道", page)
        self.assertNotIn("按时间排序", page)
        self.assertNotIn("首发", page)
        self.assertNotIn("（英文）", page)
        self.assertNotIn('class="card related-events"', page)

    def test_explicit_primary_controls_top_link_and_supplements(self):
        older = source_item(
            "older", "Old Source", "https://example.com/older",
            "Older report", "2026-08-10T10:00:00+08:00",
        )
        primary = source_item(
            "primary", "Primary Source", "https://example.com/primary",
            "Primary report", "2026-08-12T10:00:00+08:00",
        )
        event = detail_event([older, primary], primary_item_id="primary")
        page = build_site.render_detail(event, [event], "")

        self.assertIn(
            'class="original-footer-link" href="https://example.com/primary"', page,
        )
        toolbar = page.split('<span class="sharebtns">', 1)[1].split("    </span>", 1)[0]
        self.assertNotIn('href="https://example.com/primary"', toolbar)
        self.assertIn('data-source="Primary Source"', page)
        self.assertIn("补充来源", page)
        self.assertIn('href="https://example.com/older"', page)
        supplement = page.split('<section class="source-section"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn('href="https://example.com/primary"', supplement)

    def test_translated_detail_omits_redundant_ai_and_original_note(self):
        item = source_item(
            "primary", "Primary Source", "https://example.com/primary",
            "Primary report", "2026-08-12T10:00:00+08:00",
        )
        event = detail_event([item])
        event["content_mode"] = "translated"
        page = build_site.render_detail(event, [event], "")

        self.assertNotIn("AI 仅用于按原文顺序逐段翻译", page)
        self.assertIn('<span class="meta-content-mode">AI 逐段翻译</span>', page)
        self.assertIn('<span>查看原文</span>', page)
        self.assertIn('class="original-footer-link" href="https://example.com/primary"', page)
        self.assertNotIn('class="disclaimer"', page)

    def test_related_events_require_two_independent_relevance_signals(self):
        item = source_item(
            "primary", "Primary Source", "https://example.com/primary",
            "Primary report", "2026-08-12T10:00:00+08:00",
        )
        base = detail_event([item])
        base.update({
            "event_id": "base", "zh_title": "Databricks Agent 平台能力更新",
            "topics": ["Data Agent"], "vendors": ["Databricks"],
        })
        weak = detail_event([item])
        weak.update({
            "event_id": "weak", "zh_title": "Databricks 财务季度报告",
            "topics": ["财务经营"], "vendors": [],
        })
        strong = detail_event([item])
        strong.update({
            "event_id": "strong", "zh_title": "Databricks Agent 产品发布",
            "topics": ["Data Agent"], "vendors": ["Databricks"],
            "category_label": "AI 数据平台",
        })

        self.assertIsNone(build_site.related_event_score(base, weak))
        self.assertEqual(build_site.select_related_events(base, [base, weak, strong]), [strong])
        page = build_site.render_detail(base, [base, weak, strong], "")
        self.assertIn('class="card related-events"', page)
        self.assertIn("Databricks Agent 产品发布", page)
        related = page.split('class="card related-events"', 1)[1]
        self.assertNotIn("Databricks 财务季度报告", related)
        self.assertNotIn('<span class="count">', related)

    def test_same_source_reports_remain_individually_reachable(self):
        items = [
            source_item(
                "primary", "Primary Source", "https://example.com/primary",
                "Primary report", "2026-08-12T10:00:00+08:00",
            ),
            source_item(
                "extra-1", "Second Source", "https://example.com/extra-1",
                "Second source report one", "2026-08-12T11:00:00+08:00",
            ),
            source_item(
                "extra-2", "Second Source", "https://example.com/extra-2",
                "Second source report two", "2026-08-12T12:00:00+08:00",
            ),
        ]
        event = detail_event(items)
        page = build_site.render_detail(event, [event], "")

        self.assertIn("1 个信源 · 2 篇报道", page)
        self.assertIn("Second Source", page)
        self.assertIn("2 篇", page)
        self.assertIn('href="https://example.com/extra-1"', page)
        self.assertIn('href="https://example.com/extra-2"', page)
        self.assertNotIn("×2", page)

    def test_two_or_three_supplement_sources_are_expanded(self):
        items = [source_item(
            "primary", "Primary", "https://example.com/primary", "Primary",
            "2026-08-12T10:00:00+08:00",
        )]
        for index in range(3):
            items.append(source_item(
                f"extra-{index}", f"Source {index}", f"https://example.com/{index}",
                f"Report {index}", f"2026-08-12T1{index + 1}:00:00+08:00",
            ))
        event = detail_event(items)
        page = build_site.render_detail(event, [event], "")

        self.assertIn("3 个信源 · 3 篇报道", page)
        self.assertNotIn('<details class="source-more">', page)
        for index in range(3):
            self.assertIn(f"Report {index}", page)

    def test_more_than_three_supplement_sources_uses_disclosure(self):
        items = [source_item(
            "primary", "Primary", "https://example.com/primary", "Primary",
            "2026-08-12T10:00:00+08:00",
        )]
        for index in range(4):
            items.append(source_item(
                f"extra-{index}", f"Source {index}", f"https://example.com/{index}",
                f"Report {index}", f"2026-08-12T1{index + 1}:00:00+08:00",
            ))
        event = detail_event(items)
        page = build_site.render_detail(event, [event], "")

        self.assertIn("4 个信源 · 4 篇报道", page)
        self.assertIn('<details class="source-more">', page)
        self.assertIn("展开另外 2 个信源", page)
        for index in range(4):
            self.assertIn(f'href="https://example.com/{index}"', page)


if __name__ == "__main__":
    unittest.main()
