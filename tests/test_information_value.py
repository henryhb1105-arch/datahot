import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from information_value import information_value, promotion_review_required, suppress_from_lists
from lite_data import is_list_eligible, lite_event, select_timeline_events
from agent_feed import build_agent_feed, recommended_push
from feed import build_atom_feed
from weekly_brief import select_weekly_evidence
from lite_data import rank_hot_events
import xml.etree.ElementTree as ET
from build_site import select_related_events, render_detail, render_card


def event(body, title="产品版本预览", **kwargs):
    return dict(event_id="abc123", zh_title=title, zh_summary="产品更新摘要",
                full_zh=body, content_parse={"status": "ready", "quality_status": "pass", "strategy": "article"},
                category="platform", category_label="数据平台", importance=85, heat=50, star=False, vendors=[], topics=[], shelf="news", signal=0, reason="测试",
                published="2026-10-27T00:00:00+00:00", items=[{"source": "测试官网"}], **kwargs)


class InformationValueTests(unittest.TestCase):
    def test_detail_keeps_list_review_status_without_replacing_original_body(self):
        e = event("原文仍保留：运行SQL并检查结果。", content_mode="translated")
        e["content_parse"]["quality_status"] = "unknown"
        e["items"][0]["link"] = "https://example.com/source"
        before = copy.deepcopy(e)
        html = render_detail(e, [e], "")
        self.assertIn('aria-label="正文状态"', html)
        self.assertIn("正文待核验</strong>", html)
        self.assertIn("原收录理由（待核验）：", html)
        self.assertIn("对照原文 →", html)
        self.assertIn("原文仍保留：运行SQL并检查结果。", html)
        self.assertEqual(e, before)
        e["content_parse"]["quality_status"] = "pass"
        self.assertNotIn('aria-label="正文状态"', render_detail(e, [e], ""))
        e["content_mode"] = "editorial_excerpt"
        e["content_parse"] = {}
        self.assertNotIn('aria-label="正文状态"', render_detail(e, [e], ""))

    def test_bilingual_empty_and_marketing_announcements(self):
        bodies = [
            "我们很高兴宣布全新平台。革命性创新将释放数据潜力，赋能企业。敬请期待。",
            "We are pleased to announce Product 2.0. Revolutionary innovation will unlock your potential. Stay tuned for more information.",
            "社区欣然宣布版本发布。此次合并750个PR，来自53位贡献者。查看完整变更日志。",
            "The community is pleased to announce version 2.0. This release merges 750 PRs from 53 contributors. See the full changelog for details.",
        ]
        for body in bodies:
            with self.subTest(body=body):
                e = event(body)
                self.assertTrue(suppress_from_lists(e))
                self.assertFalse(is_list_eligible(e))

    def test_substance_overrides_title_and_marketing(self):
        bodies = [
            "我们很高兴宣布版本更新。现在支持增量扫描，只扫描两个快照之间新增的数据文件。",
            "我们宣布支持 JSON 格式。",
            "We announce support for JSON input.",
            "We are pleased to announce a preview. It now supports incremental scans between two snapshots.",
            "新增IPADDRESS。IPv6以128位数值存储，按数值排序，可使用BETWEEN联接子网。",
            "The schema validates IPv6 addresses before insertion and stores normalized values.",
            "打开连接器菜单，在目录中启用经济指数连接器。",
            "Open the connector menu and select the Economic Index connector.",
            "此功能仅限管理员账户，每次请求上限100条。",
            "The feature requires an admin role and is limited to 100 requests.",
            "实测延迟从120毫秒降到80毫秒。",
            "Measured latency dropped from 120 ms to 80 ms.",
            "行为变更包默认禁用，管理员可以启用测试。",
            "The bundle is disabled by default; admins can enable it for testing.",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(information_value(event(body))["status"], "substantive")
                self.assertTrue(is_list_eligible(event(body)))

    def test_cached_assessment_tracks_evidence_and_returns_independent_results(self):
        e = event("我们很高兴宣布发布。敬请期待。")
        first = information_value(e)
        first["status"] = "tampered"
        self.assertEqual(information_value(e)["status"], "low_information")
        e["full_zh"] = "现在支持JSON格式。"
        self.assertEqual(information_value(e)["status"], "substantive")
        e["content_parse"]["strategy"] = "rss_document_fallback"
        self.assertEqual(information_value(e)["status"], "insufficient_body")

    def test_missing_or_failed_capture_is_never_a_low_quality_verdict(self):
        for report in [{}, {"status": "failed"}, {"status": "ready", "quality_status": "fail"},
                       {"status": "ready", "quality_status": "pass", "strategy": "rss_document_fallback"}]:
            e = event("我们很高兴宣布发布。敬请期待。")
            e["content_parse"] = report
            self.assertEqual(information_value(e)["status"], "insufficient_body")
            self.assertTrue(is_list_eligible(e))
        self.assertEqual(information_value(event(""))["status"], "insufficient_body")

    def test_unseen_capability_is_not_treated_as_boilerplate(self):
        for body in ["We announce multivariate forecasting with exogenous covariates.", "我们宣布引入差分隐私聚合机制。"]:
            self.assertFalse(suppress_from_lists(event(body)))

    def test_unrecognised_prose_and_editorial_excerpts_stay_visible(self):
        self.assertFalse(suppress_from_lists(event("这段文字需要编辑理解，不应凭标题判断其信息价值。")))
        e = event("敬请期待。", content_mode="editorial_excerpt")
        self.assertEqual(information_value(e)["status"], "reviewed_excerpt")

    def test_guide_teaser_but_not_guide_steps(self):
        body = "Inside the guide, we share a maturity model and adoption roadmap. Check it out here."
        self.assertTrue(suppress_from_lists(event(body)))
        self.assertFalse(suppress_from_lists(event(body + " Open the settings menu and enable the connector.")))

    def test_roll_back_and_no_mutation_or_summary_laundering(self):
        e = event("我们很高兴宣布发布。敬请期待。")
        e["zh_summary"] = "现在支持行级权限，实测延迟降低90%，运行SQL即可配置。"
        before = copy.deepcopy(e)
        self.assertTrue(suppress_from_lists(e))
        self.assertEqual(e, before)
        with patch.dict(os.environ, {"LOW_INFORMATION_FILTER_ENABLED": "false"}):
            self.assertTrue(is_list_eligible(e))
        self.assertEqual(e, before)

    def test_shared_surfaces_and_metadata(self):
        e = event("我们很高兴宣布发布。敬请期待。")
        self.assertEqual(select_timeline_events([e]), [])
        self.assertEqual(build_agent_feed([e], "2026-10-27T00:00:00+00:00", site_base="https://datahot.xiahongbin.com")["events"], [])
        self.assertEqual(lite_event(e)["information_value"]["status"], "low_information")
        self.assertTrue(lite_event(e)["promotion_suppressed"])
        origin = event("真实正文", title="相邻文章")
        origin["event_id"] = "origin"
        self.assertEqual(select_related_events(origin, [e]), [])
        self.assertIn("我们很高兴宣布发布", render_detail(e, [e], ""))

    def test_unknown_title_and_technical_nouns_do_not_bypass_hype_filter(self):
        for body in ["革命性SQL平台，释放API与AI的潜力。敬请期待。", "Revolutionary SQL and API innovation unlocks your AI potential. Stay tuned for more.", "现在支持更智能的SQL洞察，赋能企业。敬请期待。"]:
            self.assertTrue(suppress_from_lists(event(body, title="下一章")))

    def test_promised_technical_topics_are_not_body_evidence(self):
        for body in ["在指南中，我们分享如何运行SQL与修复数据问题。阅读指南，查看全文。", "Inside the guide, we share how to run SQL and fix issues. Read the full guide here."]:
            self.assertTrue(suppress_from_lists(event(body)))
        body = "Inside the guide, we share query examples. SELECT id FROM users; Read the full guide here."
        self.assertFalse(suppress_from_lists(event(body)))

    def test_short_limits_and_migration_are_preserved(self):
        for body in ["v2不再支持SHA-1签名，旧客户端须在6月前迁移到SHA-256。", "Only admin users can rotate keys. Old clients must migrate to SHA-256.", "预览仅限AWS美东区域，不提供生产SLA。"]:
            self.assertFalse(suppress_from_lists(event(body)))

    def test_unverified_body_is_visible_but_cannot_trigger_high_confidence_push(self):
        e = event("站内仅有RSS摘要")
        e["content_parse"]["strategy"] = "rss_document_fallback"
        self.assertTrue(is_list_eligible(e))
        self.assertTrue(lite_event(e)["body_review_required"])
        self.assertEqual(recommended_push(e), (False, "body_unverified"))
        self.assertIn("正文待核验", render_card(e))
        self.assertEqual(rank_hot_events([e], reference_time="2026-10-27T00:00:00+00:00"), [])
        self.assertEqual(select_weekly_evidence([e], "2026-10-26", "2026-11-01"), [])
        atom = build_atom_feed([e], "2026-10-27T00:00:00+00:00", site_base="https://datahot.xiahongbin.com")
        self.assertEqual(ET.fromstring(atom).findall("{http://www.w3.org/2005/Atom}entry"), [])
        with patch.dict(os.environ, {"LOW_INFORMATION_FILTER_ENABLED": "false"}):
            self.assertFalse(lite_event(e)["body_review_required"])
            self.assertEqual(recommended_push(e), (True, "importance_80"))

    def test_live_snapshot_false_positive_controls(self):
        fixtures = json.loads((ROOT / "tests/fixtures/information_value.json").read_text())["events"]
        expected = {**dict.fromkeys(["06ffc5e72f47", "670aa1988526", "b8c871673575"], "low_information"), **dict.fromkeys(["eb2c204086f2", "7b6deb18642c", "566f6790c35c", "886b990fc1eb", "3172d33f443d", "c9238a06cab8", "9dcdafb3737f", "fde18bebfbc0", "3bb9e34e59c3"], "insufficient_body")}
        for e in fixtures:
            with self.subTest(id=e["event_id"]):
                self.assertEqual(information_value(e)["status"], expected.get(e["event_id"], "substantive"))
                self.assertEqual(suppress_from_lists(e), expected.get(e["event_id"]) == "low_information")


if __name__ == "__main__":
    unittest.main()
