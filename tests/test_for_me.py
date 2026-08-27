import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402


class ForMeBuildTests(unittest.TestCase):
    def test_for_me_is_second_desktop_and_mobile_entry(self):
        sidebar = build_site.sidebar("for-me")
        self.assertLess(sidebar.index(">热榜</a>"), sidebar.index(">关注</a>"))
        self.assertLess(sidebar.index(">关注</a>"), sidebar.index(">周报</a>"))
        self.assertIn('class="mi on" href="for-me.html"', sidebar)

        primary = build_site.tabbar("for-me").split("</nav>", 1)[0]
        self.assertEqual(primary.count("<a "), 4)
        self.assertEqual(primary.count("<button "), 1)
        self.assertLess(primary.index("<span>热榜</span>"), primary.index("<span>关注</span>"))
        self.assertLess(primary.index("<span>关注</span>"), primary.index("<span>主题</span>"))
        self.assertIn('href="for-me.html" class="on"', primary)

    def test_page_exposes_non_empty_preview_and_transparent_personalization(self):
        page = build_site.render_for_me_page("", "data/latest-lite.json")
        self.assertIn("只看与你相关的重要变化", page)
        script = (ROOT / "pipeline" / "assets" / "for-me.js").read_text(encoding="utf-8")
        self.assertIn("先感受一下", script)
        self.assertIn("至少选择 3 个", page)
        self.assertIn("为什么重要", script)
        self.assertIn("因为你关注了", script)
        self.assertIn('src="for-me.js"', page)
        self.assertIn('data-lite-url="data/latest-lite.json"', page)
        self.assertIn('data-nav-active="for-me"', page)

    def test_topic_page_can_seed_a_local_follow(self):
        topic = {"name": "Data Agent", "slug": "data-agent", "desc": "desc"}
        page = build_site.render_topic_page(topic, [], "")
        self.assertIn('../for-me.html?follow=topic:Data%20Agent', page)
        self.assertIn("＋ 关注此主题，在 For Me 查看", page)

    def test_mobile_navigation_uses_five_slots_without_overflow_prone_labels(self):
        self.assertIn("grid-template-columns:repeat(5,minmax(0,1fr))", build_site.SHARED_CSS)
        primary = build_site.tabbar("home").split("</nav>", 1)[0]
        for label in ("热榜", "关注", "主题", "收藏", "更多"):
            self.assertIn(f"<span>{label}</span>", primary)

    def test_privacy_page_discloses_local_for_me_state(self):
        page = build_site.render_privacy_page("")
        self.assertIn("For Me 与收藏", page)
        self.assertIn("只保存在本机浏览器，不会上传", page)


if __name__ == "__main__":
    unittest.main()
