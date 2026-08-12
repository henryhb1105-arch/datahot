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

    def test_home_build_declares_unbounded_progressive_timeline_and_insight_chip(self):
        source = (ROOT / "pipeline" / "build_site.py").read_text(encoding="utf-8")
        self.assertIn("不限时间 · 每批 {DEFAULT_PAGE_SIZE} 条", source)
        semantic = source.index('topic["name"] == "语义层"')
        insight = source.index('data-category="insight"', semantic)
        self.assertGreater(insight, semantic)
        self.assertIn('placeholder="搜索全部在站事件"', source)

    def test_completed_progressive_timeline_hides_load_more_button(self):
        self.assertIn(".load-more[hidden]{display:none}", build_site.SHARED_CSS)


if __name__ == "__main__":
    unittest.main()
