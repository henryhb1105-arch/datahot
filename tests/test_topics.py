import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402


REFERENCE_TIME = datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc)


def event(
    index, *, topics, published, evergreen=False, pinned=False,
    vendors=None, importance=60,
):
    event_id = f"{index:012x}"
    return {
        "event_id": event_id,
        "zh_title": f"主题事件 {index}",
        "zh_summary": f"这是主题事件 {index} 的事实摘要，用于验证主题页的信息层级。",
        "category": "agent",
        "topics": topics,
        "vendors": vendors or [],
        "importance": importance,
        "heat": importance,
        "shelf": "evergreen" if evergreen else "news",
        "pinned": pinned,
        "published": published,
        "first_seen": published,
        "items": [{"source": f"Source {index}"}],
    }


class TopicExperienceTests(unittest.TestCase):
    def test_topic_map_separates_stable_mainlines_from_business_scenes(self):
        events = [
            event(1, topics=["Data Agent"], published="2026-08-21T00:00:00+00:00"),
            event(2, topics=["Data Agent", "ChatBI"], published="2026-08-20T00:00:00+00:00"),
            event(3, topics=["Data Agent"], published="2026-07-01T00:00:00+00:00"),
            event(4, topics=["组织人才"], published="2026-08-19T00:00:00+00:00"),
            event(5, topics=["财务经营"], published="2022-12-07T00:00:00+00:00"),
        ]

        page = build_site.render_topics_map(
            events, build_site.load_css(), reference_time=REFERENCE_TIME,
        )

        self.assertLess(page.index("技术主线"), page.index("业务场景"))
        self.assertIn("稳定的长期议题，不按短期热度排名", page)
        self.assertIn("近 7 天新增 2", page)
        self.assertIn("累计 3", page)
        self.assertIn('class="tchild-link" href="topics/chatbi.html">ChatBI</a>', page)
        self.assertIn("近 7 天 +1 · 累计 1", page)
        self.assertIn("观察中 · 累计 1", page)
        self.assertNotIn("主题事件 1", page)

    def test_topic_page_uses_accurate_counts_and_progressive_disclosure(self):
        events = []
        for index in range(1, 13):
            recent = index <= 4
            events.append(event(
                index,
                topics=["Data Agent"],
                published=(
                    f"2026-08-{22 - index:02d}T00:00:00+00:00"
                    if recent else f"2026-07-{20 - index:02d}T00:00:00+00:00"
                ),
                evergreen=index <= 8,
                pinned=index <= 5,
                vendors=[f"Vendor {index % 4}"],
                importance=80 - index,
            ))
        topic = next(t for t in build_site.TOPICS_META if t["name"] == "Data Agent")

        page = build_site.render_topic_page(
            topic, events, build_site.load_css(), reference_time=REFERENCE_TIME,
        )

        self.assertIn("近 7 天新增 4", page)
        self.assertIn("累计 12", page)
        self.assertEqual(page.count('class="topic-recent-card"'), 3)
        self.assertEqual(page.count('class="crow"'), build_site.TOPIC_READING_LIMIT)
        self.assertIn(f"精选长期内容，最多 {build_site.TOPIC_READING_LIMIT} 篇", page)
        self.assertNotIn("classics.html", page)
        self.assertNotIn("典藏", page)
        self.assertEqual(page.count('<a class="topic-update-row'), 12)
        self.assertEqual(page.count("topic-update-row is-extra"), 2)
        self.assertIn("加载更多（10/12）", page)
        self.assertIn("涉及 4 个厂商", page)
        self.assertNotIn("本主题必读", page)
        self.assertNotIn('class="item"', page)

    def test_chatbi_page_exposes_data_agent_parent(self):
        topic = next(t for t in build_site.TOPICS_META if t["name"] == "ChatBI")
        page = build_site.render_topic_page(
            topic,
            [event(1, topics=["ChatBI", "Data Agent"], published="2026-08-21T00:00:00+00:00")],
            build_site.load_css(),
            reference_time=REFERENCE_TIME,
        )
        self.assertIn('所属主线：<a href="data-agent.html">Data Agent</a>', page)

    def test_topic_without_recent_events_says_so_without_misstating_scope(self):
        topic = next(t for t in build_site.TOPICS_META if t["name"] == "财务经营")
        page = build_site.render_topic_page(
            topic,
            [event(1, topics=["财务经营"], published="2022-12-07T00:00:00+00:00")],
            build_site.load_css(),
            reference_time=REFERENCE_TIME,
        )
        self.assertIn("近 7 天新增 0", page)
        self.assertIn("近 7 天暂无新增，以下保留该主题的历史脉络。", page)
        self.assertNotIn("近 7 天收录 1", page)


if __name__ == "__main__":
    unittest.main()
