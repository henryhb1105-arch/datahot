import json
import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from lite_data import (  # noqa: E402
    FIRST_PAGE_SOURCE_CAPS, build_lite_payload, event_timestamp,
    find_forbidden_fields, is_list_eligible, rank_home_events, rank_hot_events,
    rank_timeline_events, select_home_events, select_timeline_events,
)


def event(index, *, vendor="Vendor", category="platform", importance=50, heat=45, sources=1):
    event_id = f"{index:012x}"[-12:]
    return {
        "event_id": event_id, "zh_title": f"Event {index}", "zh_summary": "Summary",
        "reason": "Why", "full_zh": "forbidden full body", "content_blocks": [{"type": "p"}],
        "category": category, "category_label": category, "vendors": [vendor], "topics": ["Topic"],
        "heat": heat, "importance": importance, "star": False, "shelf": "news", "pinned": False,
        "published": f"2026-08-{(index % 9) + 1:02d}T12:00:00+08:00",
        "first_seen": f"2026-08-{(index % 9) + 1:02d}T12:{index % 60:02d}:00+08:00",
        "items": [
            {"source": f"Source {n}", "link": "https://example.com", "article_text": "forbidden"}
            for n in range(sources)
        ],
    }


class LitePayloadTests(unittest.TestCase):
    def test_insight_category_is_list_eligible(self):
        item = event(99, category="insight")
        item["zh_title"] = "员工数据揭示组织技能缺口"
        item["zh_summary"] = "分析给出了人才配置建议。"
        self.assertTrue(is_list_eligible(item))

    def test_payload_never_contains_article_body_fields(self):
        payload = build_lite_payload([event(1)], "2026-08-11T12:00:00+08:00")
        self.assertEqual(find_forbidden_fields(payload), [])
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("forbidden full body", encoded)
        self.assertNotIn("https://example.com", encoded)

    def test_explicit_empty_home_ranking_does_not_fall_back_to_all_events(self):
        payload = build_lite_payload([event(1)], "2026-08-11T12:00:00+08:00", ranking=[])
        self.assertEqual(payload["home_event_ids"], [])

    def test_first_page_enforces_vendor_cap(self):
        events = [event(i, vendor="Dominant") for i in range(12)]
        events += [event(100 + i, vendor=f"Vendor {i}", category="bi") for i in range(20)]
        ranked = rank_home_events(events, page_size=20, vendor_cap=4)
        counts = Counter((item.get("vendors") or [""])[0] for item in ranked[:20])
        self.assertLessEqual(counts["Dominant"], 4)
        self.assertEqual(len(ranked), len(events))

    def test_sparse_mix_keeps_hard_vendor_cap_even_if_page_is_short(self):
        events = [event(i, vendor="Only Vendor") for i in range(12)]
        first = rank_home_events(events, page_size=20, vendor_cap=4, first_page_only=True)
        self.assertEqual(len(first), 4)

    def test_category_overflow_requires_quality_until_floor_relaxation(self):
        dominant = [event(i, vendor=f"P{i}", category="platform") for i in range(18)]
        balanced = [event(100 + i, vendor=f"B{i}", category="bi") for i in range(10)]
        ranked = rank_home_events(dominant + balanced, page_size=20, category_soft_cap=12)
        first = ranked[:20]
        self.assertLessEqual(Counter(item["category"] for item in first)["platform"], 12)
        self.assertEqual(len(first), 20)

    def test_high_quality_event_can_cross_soft_category_cap(self):
        events = [event(i, vendor=f"V{i}", category="platform") for i in range(16)]
        events[-1]["importance"] = 85
        ranked = rank_home_events(events, page_size=13, category_soft_cap=12, minimum_page_size=0)
        first_ids = {item["event_id"] for item in ranked[:13]}
        self.assertIn(events[-1]["event_id"], first_ids)

    def test_public_pool_rejects_unfinished_and_untranslated_items(self):
        good = event(1)
        good["zh_title"] = "数据平台发布新能力"
        good["zh_summary"] = "这是经过中文编辑处理的事件摘要。"
        empty = event(2)
        empty["zh_title"] = "数据平台更新"
        empty["zh_summary"] = ""
        untranslated = event(3)
        untranslated["zh_title"] = "Generic AI warehouse story"
        untranslated["zh_summary"] = "Raw community post without editorial review"
        raw = event(4)
        raw["zh_title"] = "数据平台未经编辑的原始文章"
        raw["zh_summary"] = "虽然有中文内容，但没有任何编辑判断。"
        raw["reason"], raw["topics"], raw["vendors"], raw["importance"] = "", [], [], 50
        selected = select_home_events([empty, untranslated, raw, good])
        self.assertEqual([item["event_id"] for item in selected], [good["event_id"]])

    def test_claude_backlog_is_bounded_in_feed_and_first_page(self):
        claude = []
        for index in range(12):
            item = event(index, vendor="Claude", category="agent")
            item["items"][0]["source"] = "Claude 官方博客"
            item["zh_title"] = f"Claude 数据代理更新 {index}"
            item["zh_summary"] = "经过中文编辑的完整摘要。"
            claude.append(item)
        others = []
        for index in range(20, 40):
            item = event(index, vendor=f"Vendor {index}", category="platform")
            item["items"][0]["source"] = f"Source {index}"
            item["zh_title"] = f"数据平台更新 {index}"
            item["zh_summary"] = "经过中文编辑的完整摘要。"
            others.append(item)
        pool = select_home_events(claude + others)
        self.assertEqual(
            sum(item["items"][0]["source"] == "Claude 官方博客" for item in pool), 6
        )
        first = rank_home_events(
            pool, page_size=20, first_page_only=True,
            source_caps=FIRST_PAGE_SOURCE_CAPS, prevent_adjacent_sources=True,
        )
        sources = [item["items"][0]["source"] for item in first]
        self.assertLessEqual(sources.count("Claude 官方博客"), 2)
        self.assertFalse(any(left == right == "Claude 官方博客" for left, right in zip(sources, sources[1:])))

    def test_timeline_retains_qualified_history_without_global_source_cap(self):
        items = []
        for index in range(12):
            item = event(index, vendor="Claude", category="agent")
            item["items"][0]["source"] = "Claude 官方博客"
            item["zh_title"] = f"Claude 数据代理更新 {index}"
            item["zh_summary"] = "经过中文编辑的完整摘要。"
            items.append(item)
        selected = select_timeline_events(items)
        self.assertEqual(len(selected), 12)

    def test_timeline_ranking_keeps_every_item_and_descending_days(self):
        items = []
        for index in range(45):
            item = event(index, vendor=f"Vendor {index % 8}", category="platform")
            item["zh_title"] = f"数据平台历史事件 {index}"
            item["zh_summary"] = "经过中文编辑的完整摘要。"
            items.append(item)
        ranked = rank_timeline_events(items, page_size=20)
        self.assertEqual(len(ranked), len(items))
        self.assertEqual(len({item["event_id"] for item in ranked}), len(items))
        days = [event_timestamp(item).date() for item in ranked]
        self.assertEqual(days, sorted(days, reverse=True))

    def test_public_sort_prefers_published_time_over_recent_ingestion(self):
        old = event(1)
        old["published"] = "2026-08-01T12:00:00+08:00"
        old["first_seen"] = "2026-08-11T12:00:00+08:00"
        current = event(2)
        current["published"] = "2026-08-10T12:00:00+08:00"
        current["first_seen"] = "2026-08-10T12:00:00+08:00"
        ranked = rank_home_events([old, current], page_size=2, minimum_page_size=0)
        self.assertEqual(ranked[0]["event_id"], current["event_id"])
        self.assertEqual(event_timestamp(old).day, 1)

    def test_hot_list_excludes_unfinished_items_and_caps_each_source(self):
        events = []
        for index in range(5):
            item = event(index, heat=90 - index)
            item["items"][0]["source"] = "One Publisher"
            item["zh_title"] = f"数据平台热点 {index}"
            item["zh_summary"] = "完整中文摘要。"
            events.append(item)
        unfinished = event(99, heat=100)
        unfinished["zh_title"] = "未完成热点"
        unfinished["zh_summary"] = ""
        other = event(100, heat=70)
        other["items"][0]["source"] = "Another Publisher"
        other["zh_title"] = "另一条数据热点"
        other["zh_summary"] = "完整中文摘要。"
        ranked = rank_hot_events(events + [unfinished, other], limit=9, source_cap=2)
        self.assertNotIn(unfinished["event_id"], {item["event_id"] for item in ranked})
        self.assertEqual(sum(item["items"][0]["source"] == "One Publisher" for item in ranked), 2)
        sources = [item["items"][0]["source"] for item in ranked]
        self.assertFalse(any(left == right for left, right in zip(sources, sources[1:])))


if __name__ == "__main__":
    unittest.main()
