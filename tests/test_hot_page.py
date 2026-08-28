import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402


def hot_event(index, *, source=None, extra_source=False):
    source = source or f"Example RSS {index}"
    items = [{"source": source}]
    if extra_source:
        items.append({"source": "Second source"})
    return {
        "event_id": f"event-{index}",
        "zh_title": f"这是一条很长的移动端热榜标题 {index} <测试>",
        "zh_summary": "用于验证完整榜单移动端布局的中文摘要。",
        "category": "agent",
        "importance": 80,
        "reason": "值得关注",
        "heat": 100 - index,
        "published": f"2026-08-{13 - index:02d}T08:00:00+08:00",
        "items": items,
    }


class HotPageTests(unittest.TestCase):
    def test_hot_page_uses_dedicated_responsive_ranking_structure(self):
        page = build_site.render_hot_page([
            hot_event(1, source="主编收录", extra_source=True),
            hot_event(2),
            hot_event(3),
            hot_event(4),
        ], "")

        self.assertIn('<main class="wrap rank-page">', page)
        self.assertIn('<div class="rank-list">', page)
        self.assertEqual(page.count('class="rank-row"'), 4)
        self.assertEqual(page.count('class="rank-no is-top"'), 3)
        self.assertNotIn('<a class="hrow"', page)
        self.assertIn("数据领域近 7 天热度 TOP 9", page)

    def test_hot_page_keeps_source_and_heat_separate_and_escapes_title(self):
        page = build_site.render_hot_page([
            hot_event(1, source="主编收录", extra_source=True),
        ], "")

        self.assertIn('<span class="rank-source">DataHot 精选 · 另有1家</span>', page)
        self.assertIn('<span class="rank-heat">', page)
        self.assertIn("&lt;测试&gt;", page)
        self.assertNotIn("<测试>", page)

    def test_mobile_ranking_has_two_line_title_touch_height_and_collapsed_note(self):
        css = build_site.SHARED_CSS
        page = build_site.render_hot_page([hot_event(1)], "")

        self.assertIn("@media(max-width:600px){\n  .rank-page{padding:18px 14px", css)
        self.assertIn(".rank-row{grid-template-columns:30px minmax(0,1fr);", css)
        self.assertIn("min-height:76px", css)
        self.assertIn("-webkit-line-clamp:2", css)
        self.assertIn(".rank-source{flex:1}", css)
        self.assertIn(".rank-row:focus-visible", css)
        self.assertIn('<details class="rank-note"><summary>热度如何计算</summary>', page)
        self.assertNotIn('<details class="rank-note" open', page)

    def test_hot_page_explains_the_current_ranking_formula(self):
        page = build_site.render_hot_page([hot_event(1)], "")

        self.assertIn("内容质量45%", page)
        self.assertIn("趋势55%（48小时半衰新鲜度、社区信号与多信源印证）", page)
        self.assertIn("按热度降序，同一信源最多 2 条", page)


if __name__ == "__main__":
    unittest.main()
