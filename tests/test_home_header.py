import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402


class HomeHeaderTests(unittest.TestCase):
    def test_brand_is_a_refresh_link_and_update_explanation_is_accessible(self):
        generated = datetime(2026, 8, 12, 8, 20, tzinfo=timezone.utc)
        header = build_site.render_home_brand_update(generated)
        self.assertIn('href="index.html"', header)
        self.assertIn("data-home-refresh", header)
        self.assertIn('aria-label="刷新 DataHot 首页"', header)
        self.assertIn("data-update-info", header)
        self.assertIn('aria-describedby="updateMechanism"', header)
        self.assertIn("02:17、08:17、14:17、20:17", header)
        self.assertIn("筛选去重、AI 整理和静态发布", header)

    def test_update_explanation_supports_hover_focus_click_outside_and_escape(self):
        css = build_site.load_css()
        script = build_site.home_update_info_script()
        self.assertIn(".update-info:not(.is-dismissed):hover .update-popover", css)
        self.assertIn(".update-info:not(.is-dismissed):focus-within .update-popover", css)
        self.assertIn("info.removeAttribute('open')", script)
        self.assertIn("event.key!=='Escape'", script)
        self.assertIn("info.contains(event.target)", script)

    def test_home_build_uses_compact_timeline_copy_and_insight_chip(self):
        source = (ROOT / "pipeline" / "build_site.py").read_text(encoding="utf-8")
        self.assertNotIn("不限时间 · 每批 {DEFAULT_PAGE_SIZE} 条", source)
        self.assertIn('data-category="insight">AI分析</span>', source)
        self.assertIn('placeholder="搜索"', source)

    def test_completed_progressive_timeline_hides_load_more_button(self):
        self.assertIn(".load-more[hidden]{display:none}", build_site.SHARED_CSS)

    def test_home_filter_chips_use_short_labels_and_stable_order(self):
        events = [{"topics": [
            "ChatBI", "Data Agent", "语义层", "平台AI化", "BI变局",
            "湖仓", "实时分析", "数据人", "组织人才", "财务经营",
        ]}]
        chips = build_site.render_home_filter_chips(events)
        ordered_markup = [
            'data-topic="Data Agent">Agent</span>',
            'data-category="insight">AI分析</span>',
            'data-topic="平台AI化">AI平台</span>',
            'data-topic="语义层">语义层</span>',
            'data-topic="实时分析">实时</span>',
            'data-topic="ChatBI">ChatBI</span>',
            'data-topic="湖仓">湖仓</span>',
            'data-topic="BI变局">BI变局</span>',
            'data-topic="数据人">数据人</span>',
            'data-topic="组织人才">组织人才</span>',
            'data-topic="财务经营">财务经营</span>',
        ]
        positions = [chips.index(markup) for markup in ordered_markup]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("AI 分析与洞察", chips)

    def test_insight_chip_stays_available_when_agent_topic_is_inactive(self):
        chips = build_site.render_home_filter_chips([{"topics": ["语义层"]}])
        self.assertTrue(chips.startswith(
            '<span class="fchip" data-category="insight">AI分析</span>'
        ))

    def test_home_filter_chips_keep_canonical_topic_values_for_urls(self):
        chips = build_site.render_home_filter_chips([
            {"topics": ["Data Agent", "平台AI化", "实时分析"]},
        ])
        self.assertIn('data-topic="Data Agent">Agent</span>', chips)
        self.assertIn('data-topic="平台AI化">AI平台</span>', chips)
        self.assertIn('data-topic="实时分析">实时</span>', chips)

    def test_mobile_filter_chips_use_compact_readable_spacing(self):
        self.assertIn("@media(max-width:600px){\n  .chiprow{gap:6px}", build_site.SHARED_CSS)
        self.assertIn(
            ".chiprow .fchip{font-size:12px;padding:4px 12px;min-height:32px",
            build_site.SHARED_CSS,
        )

    def test_mobile_timeline_toolbar_stays_on_one_compact_line(self):
        toolbar = build_site.render_timeline_toolbar(126)
        css = build_site.load_css()
        self.assertIn('class="section-title timeline-toolbar"', toolbar)
        self.assertNotIn('class="timeline-meta"', toolbar)
        self.assertIn('class="timeline-searchbox"', toolbar)
        self.assertIn('class="timeline-count"', toolbar)
        self.assertIn('placeholder="搜索"', toolbar)
        self.assertNotIn("不限时间", toolbar)
        self.assertNotIn('style="align-items:center"', toolbar)
        self.assertIn(
            ".timeline-toolbar h2,.timeline-toolbar .timeline-count{white-space:nowrap}",
            css,
        )
        self.assertIn(
            ".timeline-toolbar{align-items:center;flex-wrap:nowrap}",
            css,
        )
        self.assertIn(".timeline-searchbox{width:min(120px,34vw)}", css)
        self.assertIn(
            ".timeline-searchbox .tlsearch,.timeline-searchbox .tlsearch:focus{width:100%}",
            css,
        )
        self.assertIn(
            ".timeline-searchbox .tlsearch{margin-left:0;min-width:0;flex:1 1 0}",
            css,
        )


if __name__ == "__main__":
    unittest.main()
