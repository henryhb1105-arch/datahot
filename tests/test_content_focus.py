import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from content_focus import content_focus
from lite_data import lite_event, rank_timeline_events


class ContentFocusTests(unittest.TestCase):
    def test_five_directions_and_generic_database_news(self):
        cases = [
            ("数据 Agent 的权限验证与执行轨迹", "data-agent"),
            ("AI数据平台的上下文管理", "ai-platform"),
            ("统一语义层与指标口径", "semantic-layer"),
            ("AI数据分析如何接手编辑计算", "ai-analysis"),
            ("AI看板如何处理空数据状态", "ai-dashboard"),
            ("BigQuery自增列自动生成整数", "other"),
            ("Snowflake数据库新增CDC连接器", "other"),
            ("通用AI模型融资发布", "other"),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(content_focus({"zh_title": title})["id"], expected)

    def test_vendor_category_reason_and_full_body_cannot_fake_relevance(self):
        generic = {"zh_title": "数据库整数序列", "category": "platform",
                   "vendors": ["Snowflake"], "reason": "适合数据 Agent",
                   "full_zh": "AI 数据平台、语义层、Data Agent"}
        self.assertEqual(content_focus(generic)["priority"], 5)
        generic["zh_summary"] = "新增语义视图支持指标口径检查"
        self.assertEqual(content_focus(generic)["id"], "semantic-layer")
        self.assertTrue(lite_event(generic)["focus"]["practical"])

    def test_passing_product_mentions_and_general_coding_agents_are_not_data_agents(self):
        mobile = {"zh_title": "Databricks 个人设备移动安全实践",
                  "zh_summary": "员工通过 Genie 和 Claude Code 保持上下文，采用设备管理与零信任保护公司数据。",
                  "topics": ["平台AI化"]}
        coding = {"zh_title": "LinkedIn 的组织级上下文层与 AI Agent",
                  "zh_summary": "通过代码搜索和运行手册为编码 Agent 定位下游 PR 的事故。",
                  "topics": ["Data Agent"]}
        for item in (mobile, coding):
            self.assertEqual(content_focus(item)["id"], "other")

    def test_within_day_focus_wins_without_losing_history_or_reordering_dates(self):
        def event(i, title, date):
            return {"event_id": f"{i:012x}", "zh_title": title, "zh_summary": "官方资料已说明这项具体更新。",
                    "reason": "参考", "category": "platform", "importance": 70,
                    "published": date, "first_seen": date, "items": [{"source": f"Source {i}"}]}
        items = [event(1, "数据库自增整数", "2026-09-21T12:00:00+08:00"),
                 event(2, "数据 Agent 权限验证", "2026-09-21T09:00:00+08:00"),
                 event(3, "数据 Agent 评测方法", "2026-09-20T18:00:00+08:00")]
        ranked = rank_timeline_events(items)
        self.assertEqual([e["event_id"] for e in ranked], [items[i]["event_id"] for i in (1, 0, 2)])
