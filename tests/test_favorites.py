import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402


def event(event_id="aaaaaaaaaaaa"):
    return {
        "event_id": event_id,
        "zh_title": "收藏测试标题",
        "zh_summary": "收藏测试摘要",
        "reason": "值得稍后阅读",
        "category": "agent",
        "topics": ["Data Agent"],
        "vendors": [],
        "heat": 60,
        "importance": 60,
        "shelf": "news",
        "published": "2026-08-23T10:00:00+08:00",
        "first_seen": "2026-08-23T10:00:00+08:00",
        "items": [{
            "source": "测试信源",
            "link": "https://example.com/article",
            "title": "原文标题",
            "published": "2026-08-23T10:00:00+08:00",
        }],
        "full_zh": "不应进入收藏快照的全文",
    }


class FavoritesTests(unittest.TestCase):
    def test_button_embeds_metadata_snapshot_without_article_body(self):
        button = build_site.favorite_button(event())
        self.assertIn('data-fav="aaaaaaaaaaaa"', button)
        self.assertIn('data-fav-record="', button)
        self.assertIn("收藏测试标题", button)
        self.assertIn("收藏测试摘要", button)
        self.assertIn("https://example.com/article", button)
        self.assertNotIn("不应进入收藏快照的全文", button)
        self.assertIn('aria-pressed="false"', button)

    def test_favorites_page_is_snapshot_first_and_progressively_searchable(self):
        page = build_site.render_favorites_page("", "data/latest-lite.json")
        self.assertIn('data-favorites-page', page)
        self.assertIn('data-favorites-data-url="data/latest-lite.json"', page)
        self.assertIn('id="favoritesSearch"', page)
        self.assertIn("仅保存在当前浏览器", page)
        self.assertIn('<script defer src="favorites.js"></script>', page)
        self.assertNotIn("收藏的内容已过期", page)
        self.assertNotIn("localStorage.getItem('dh_favs')", page)

    def test_detail_and_topic_cards_use_the_shared_favorite_client(self):
        item = event()
        detail = build_site.render_detail(item, [item], "")
        self.assertIn('<script defer src="../favorites.js"></script>', detail)
        self.assertIn('class="sbtn ghost favbtn"', detail)
        self.assertNotIn("function dhFavs()", detail)

        topic = {"name": "Data Agent", "slug": "data-agent", "desc": "主题说明"}
        topic_page = build_site.render_topic_page(
            topic, [item], "", reference_time=build_site.datetime.fromisoformat("2026-08-23T12:00:00+08:00")
        )
        self.assertIn('class="topic-recent-wrap"', topic_page)
        self.assertIn('class="favbtn topic-recent-fav"', topic_page)
        self.assertIn('<script defer src="../favorites.js"></script>', topic_page)

    def test_timeline_snapshot_and_hot_cards_offer_the_same_action(self):
        item = event()
        timeline_card = build_site.render_card(item)
        self.assertIn('data-fav-record="', timeline_card)
        self.assertIn('&quot;event_id&quot;:&quot;aaaaaaaaaaaa&quot;', timeline_card)
        self.assertIn('type="button"', timeline_card)

        source = (ROOT / "pipeline" / "build_site.py").read_text(encoding="utf-8")
        self.assertIn("<span class=\"htime\">{card_time(e)}</span>{favorite_button(e)}", source)


if __name__ == "__main__":
    unittest.main()
