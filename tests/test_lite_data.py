import json
import sys
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
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

    def test_payload_carries_a_safe_primary_source_badge_for_dynamic_cards(self):
        payload = build_lite_payload(
            [event(1)], "2026-08-11T12:00:00+08:00",
            source_badge_resolver=lambda _source: "官网",
        )
        self.assertEqual(payload["events"][0]["source_badge"], "官网")
        fallback = build_lite_payload(
            [event(2)], "2026-08-11T12:00:00+08:00",
            source_badge_resolver=lambda _source: "unexpected",
        )
        self.assertEqual(fallback["events"][0]["source_badge"], "RSS")

    def test_payload_carries_editorial_selection_metadata_without_discovery_url(self):
        item = event(1)
        item.update({
            "editorial_pick": True,
            "curated_at": "2026-09-04T09:55:00+08:00",
            "discovery_source": "X·@JasonSCui",
            "discovery_url": "https://x.com/JasonSCui/status/2031371431129526446",
        })
        payload = build_lite_payload([item], "2026-09-04T10:00:00+08:00")
        projected = payload["events"][0]
        self.assertTrue(projected["editorial_pick"])
        self.assertEqual(projected["curated_at"], "2026-09-04T09:55:00+08:00")
        self.assertEqual(projected["discovery_source"], "X·@JasonSCui")
        self.assertNotIn("discovery_url", projected)

    def test_payload_separates_quality_and_trend_with_legacy_fallbacks(self):
        scored = event(9, importance=72, heat=61)
        scored["quality_score"] = 84
        scored["trend_score"] = 47
        legacy = event(10, importance=63, heat=58)
        payload = build_lite_payload(
            [scored, legacy], "2026-08-11T12:00:00+08:00",
        )
        by_id = {row["event_id"]: row for row in payload["events"]}
        self.assertEqual(by_id[scored["event_id"]]["quality_score"], 84)
        self.assertEqual(by_id[scored["event_id"]]["trend_score"], 47)
        self.assertEqual(by_id[legacy["event_id"]]["quality_score"], 63)
        self.assertEqual(by_id[legacy["event_id"]]["trend_score"], 58)

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

    def test_public_pool_rejects_explicit_low_importance_but_keeps_legacy_unscored(self):
        low = event(5, importance=10, heat=24)
        low["zh_title"] = "Snowflake 预览发布说明暂无更新"
        low["zh_summary"] = "本次没有需要宣布的重大功能、更新或增强。"
        legacy = event(6)
        legacy["importance"] = None
        legacy["zh_title"] = "历史数据平台更新"
        legacy["zh_summary"] = "这是一条在重要性评分上线前完成编辑的历史事件。"
        selected = select_timeline_events([low, legacy])
        self.assertEqual([item["event_id"] for item in selected], [legacy["event_id"]])
        payload = build_lite_payload([low, legacy], "2026-08-11T12:00:00+08:00", ranking=selected)
        self.assertIsNone(payload["events"][1]["importance"])

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
        heats = [item["heat"] for item in ranked]
        self.assertEqual(heats, sorted(heats, reverse=True))

    def test_hot_list_keeps_heat_order_for_same_source_events(self):
        """issue #82：相邻同源的高分事件不得被低分事件反超。"""
        top = event(1, heat=67)
        top["items"][0]["source"] = "主编收录"
        runner_up = event(2, heat=65)
        runner_up["items"][0]["source"] = "主编收录"
        lower = event(3, heat=59)
        lower["items"][0]["source"] = "Databricks Blog"
        for item in (top, runner_up, lower):
            item["zh_title"] = f"数据热点 {item['event_id']}"
            item["zh_summary"] = "完整中文摘要。"
        ranked = rank_hot_events([lower, runner_up, top], limit=3, source_cap=2)
        self.assertEqual(
            [item["event_id"] for item in ranked],
            [top["event_id"], runner_up["event_id"], lower["event_id"]],
        )

    def test_hot_list_uses_a_true_seven_day_publication_window(self):
        reference = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
        fresh = event(201, heat=60)
        fresh["published"] = (reference - timedelta(days=1)).isoformat()
        boundary = event(202, heat=59)
        boundary["published"] = (reference - timedelta(days=7)).isoformat()
        historical_backfill = event(203, heat=99)
        historical_backfill["published"] = (reference - timedelta(days=100)).isoformat()
        historical_backfill["first_seen"] = reference.isoformat()
        historical_backfill["shelf"] = "evergreen"
        future = event(204, heat=100)
        future["published"] = (reference + timedelta(hours=1)).isoformat()
        for item in (fresh, boundary, historical_backfill, future):
            item["zh_title"] = f"数据平台热榜事件 {item['event_id']}"
            item["zh_summary"] = "经过中文编辑的完整摘要。"

        ranked = rank_hot_events(
            [historical_backfill, future, boundary, fresh],
            reference_time=reference,
        )

        self.assertEqual(
            [item["event_id"] for item in ranked],
            [fresh["event_id"], boundary["event_id"]],
        )


if __name__ == "__main__":
    unittest.main()
