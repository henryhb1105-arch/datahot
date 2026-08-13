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
        self.assertIn('data-category="insight">AI分析</button>', source)
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
            'data-topic="Data Agent">Agent</button>',
            'data-category="insight">AI分析</button>',
            'data-topic="平台AI化">AI平台</button>',
            'data-topic="语义层">语义层</button>',
            'data-topic="实时分析">实时</button>',
            'data-topic="ChatBI">ChatBI</button>',
            'data-topic="湖仓">湖仓</button>',
            'data-topic="BI变局">BI变局</button>',
            'data-topic="数据人">数据人</button>',
            'data-topic="组织人才">组织人才</button>',
            'data-topic="财务经营">财务经营</button>',
        ]
        positions = [chips.index(markup) for markup in ordered_markup]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("AI 分析与洞察", chips)

    def test_insight_chip_stays_available_when_agent_topic_is_inactive(self):
        chips = build_site.render_home_filter_chips([{"topics": ["语义层"]}])
        self.assertTrue(chips.startswith(
            '<button class="fchip" type="button" aria-pressed="false" '
            'data-category="insight">AI分析</button>'
        ))

    def test_home_filter_chips_keep_canonical_topic_values_for_urls(self):
        chips = build_site.render_home_filter_chips([
            {"topics": ["Data Agent", "平台AI化", "实时分析"]},
        ])
        self.assertIn('data-topic="Data Agent">Agent</button>', chips)
        self.assertIn('data-topic="平台AI化">AI平台</button>', chips)
        self.assertIn('data-topic="实时分析">实时</button>', chips)

    def test_filter_chips_wrap_on_desktop_and_scroll_with_affordance_on_mobile(self):
        self.assertIn(
            ".chiprow{display:flex;flex-wrap:wrap;gap:8px;overflow:visible",
            build_site.SHARED_CSS,
        )
        self.assertIn("@media(max-width:600px){\n  .chiprow{flex-wrap:nowrap;gap:6px;overflow-x:auto", build_site.SHARED_CSS)
        self.assertIn(".chiprow::after{display:block}", build_site.SHARED_CSS)
        self.assertIn(
            ".chiprow .fchip{font-size:12px;padding:4px 12px;min-height:44px",
            build_site.SHARED_CSS,
        )

    def test_filter_chips_are_semantic_toggle_buttons(self):
        chips = build_site.render_home_filter_chips([{"topics": ["Data Agent"]}])
        self.assertIn('<button class="fchip" type="button" aria-pressed="false"', chips)
        source = (ROOT / "pipeline" / "build_site.py").read_text(encoding="utf-8")
        self.assertIn('role="group" aria-label="筛选时间轴"', source)
        self.assertIn('aria-pressed="true" data-topic="all"', source)
        home_js = (ROOT / "pipeline" / "assets" / "home.js").read_text(encoding="utf-8")
        self.assertIn('chip.setAttribute("aria-pressed", selected ? "true" : "false")', home_js)

    def test_responsive_shell_avoids_mid_width_three_column_squeeze(self):
        css = build_site.load_css()
        self.assertIn("@media(max-width:1199px){.layout{grid-template-columns:1fr}}", css)
        self.assertIn("@media(max-width:600px){.hotlist{grid-template-columns:1fr;gap:10px}}", css)
        self.assertIn(
            "@media(max-width:1399px) and (min-width:601px){.hotlist{grid-template-columns:repeat(2,minmax(0,1fr))}}",
            css,
        )
        self.assertIn("@media(min-width:1200px){", build_site.SHARED_CSS)
        self.assertIn("@media(max-width:1199px){\n  body{padding-bottom:64px}", build_site.SHARED_CSS)

    def test_more_navigation_is_a_focus_trapped_modal(self):
        markup = build_site.tabbar("home")
        self.assertIn('role="dialog" aria-modal="true"', markup)
        self.assertIn('aria-labelledby="mobileMoreTitle"', markup)
        self.assertIn("node.setAttribute('inert','')", markup)
        self.assertIn("node.removeAttribute('inert')", markup)
        self.assertIn("event.key!=='Tab'", markup)
        self.assertIn("event.preventDefault();last.focus()", markup)
        self.assertIn("event.preventDefault();first.focus()", markup)

    def test_core_controls_have_touch_targets_focus_and_reduced_motion(self):
        toolbar = build_site.render_timeline_toolbar(12)
        self.assertIn('<button id="qClear"', toolbar)
        self.assertIn('aria-label="清除搜索"', toolbar)
        self.assertIn(".more-close{appearance:none;border:0", build_site.SHARED_CSS)
        self.assertIn("width:44px;height:44px", build_site.SHARED_CSS)
        self.assertIn("@media(prefers-reduced-motion:reduce)", build_site.SHARED_CSS)
        self.assertIn(".agent-copy{appearance:none;min-height:44px", build_site.AGENT_PAGE_CSS)

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

    def test_card_feedback_uses_hover_only_for_fine_pointers(self):
        css = build_site.load_css()
        self.assertIn("@media(hover:hover) and (pointer:fine){", css)
        self.assertIn(
            ".hot:hover,.item:hover{border-color:#d1d5db;"
            "box-shadow:0 4px 16px rgba(0,0,0,.05)}",
            css,
        )
        self.assertIn(".hot a:hover,.item a:hover{color:var(--accent)}", css)
        self.assertIn("@media(hover:none) and (pointer:coarse){", css)
        self.assertIn(
            ".hot:active,.item:active{border-color:#d1d5db;"
            "box-shadow:0 2px 8px rgba(0,0,0,.04)}",
            css,
        )
        self.assertNotIn("\n  .hot:hover{", css)
        self.assertNotIn("\n  .item:hover{", css)

        builder = (ROOT / "pipeline" / "build_site.py").read_text(encoding="utf-8")
        self.assertNotIn(".item a:hover{{", builder)
        self.assertNotIn(".hot a:hover{{", builder)

    def test_all_visual_hover_feedback_is_scoped_by_input_capability(self):
        css = build_site.load_css()
        shared = build_site.SHARED_CSS
        agent_css = (ROOT / "pipeline" / "agent_page.py").read_text(encoding="utf-8")
        builder = (ROOT / "pipeline" / "build_site.py").read_text(encoding="utf-8")

        self.assertIn(
            "@media(hover:hover) and (pointer:fine){\n"
            "    .update-info:hover .upd-time,.tab:hover",
            css,
        )
        self.assertIn(
            "@media(hover:hover) and (pointer:fine){\n"
            "  .chip:hover{background:#dbe4ff}",
            shared,
        )
        for selector in (
            "a.source-name:hover", ".crow:hover .ctitle", ".fav-entry:hover",
            ".weekly-evidence-row:hover", ".hrow:hover .ht", ".source-cta:hover",
            ".load-more:hover", ".weekly-waiting:hover", ".weekly-archive a:hover",
            ".weekly-teaser:hover", ".sidebar a.mi:hover", ".tcard:hover",
        ):
            self.assertIn(selector, shared)
        self.assertIn(
            "@media(hover:hover) and (pointer:fine){.agent-copy:hover",
            agent_css,
        )
        self.assertIn(
            "@media(hover:hover) and (pointer:fine){{\n"
            "  .article .back:hover,.source-report:hover",
            builder,
        )

        for unscoped_rule in (
            "\n.chip:hover{", "\na.source-name:hover{", "\n.source-cta:hover{",
            "\n.crow:hover", "\n.fav-entry:hover{", "\n.load-more:hover{",
            "\n.weekly-teaser:hover{", "\n.weekly-waiting:hover{",
            "\n.weekly-evidence-row:hover", "\n.hrow:hover", "\n.tcard:hover{",
            "\n.agent-copy:hover{", "\n.article .back:hover{{",
            "\n.source-report:hover", "\n.cta:hover{{",
        ):
            self.assertNotIn(unscoped_rule, builder + agent_css)


if __name__ == "__main__":
    unittest.main()
