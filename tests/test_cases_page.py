import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402


def case_event():
    return {
        "event_id": "abcdef123456",
        "zh_title": "Genie One 如何让业务用户直接完成数据分析",
        "zh_summary": "从桌面入口、文件协作到创建 Agent 的完整产品流程。",
        "reason": "展示真实产品流程",
        "category": "agent",
        "topics": ["Data Agent"],
        "vendors": ["Databricks"],
        "heat": 82,
        "importance": 82,
        "shelf": "evergreen",
        "published": "2026-08-26T10:00:00+08:00",
        "first_seen": "2026-08-26T10:00:00+08:00",
        "items": [{
            "source": "Databricks",
            "link": "https://example.com/genie-one",
            "title": "Introducing Genie One",
            "published": "2026-08-26T10:00:00+08:00",
        }],
        "content_blocks": [{
            "type": "figure",
            "id": "b-hero12345678",
            "cached_src": "../media/abcdef123456/hero123456789.png",
            "media_status": "cached",
            "alt": "Genie One 桌面入口",
            "source_url": "https://example.com/genie-one",
        }],
        "full_zh": "这是原文正文。",
    }


def product_case():
    return {
        "event_id": "abcdef123456",
        "product": "Databricks Genie One",
        "product_type": "Data Agent",
        "task_type": "问数据",
        "design_questions": ["入口与提问", "可信与溯源"],
        "hero_figure_id": "b-hero12345678",
        "user_problem": "业务用户难以在多个工具间完成从问题到结果的分析。",
        "modules": ["桌面入口", "文件协作", "Agent 配置"],
        "interactions": ["上传文件后直接追问", "从对话进入配置"],
        "official_facts": ["官方演示展示了桌面应用和文件上传流程。"],
        "datahot_interpretation": ["把入口前移，减少业务用户寻找数据工具的成本。"],
        "tradeoffs": ["入口更简单，但复杂配置仍需专业用户完成。"],
        "takeaways": ["把高频任务放在用户已有工作环境中。"],
        "limitations": ["不能据此推断所有权限治理能力。"],
        "observed_at": "2026-08-26",
    }


class ProductCasesPageTests(unittest.TestCase):
    def test_navigation_promotes_cases_and_moves_topics_into_more(self):
        desktop = build_site.sidebar("cases")
        self.assertLess(desktop.index(">关注</a>"), desktop.index(">案例</a>"))
        self.assertLess(desktop.index(">案例</a>"), desktop.index(">周报</a>"))
        self.assertIn('class="mi on" href="cases.html"', desktop)

        mobile = build_site.tabbar("cases")
        primary, more = mobile.split("</nav>", 1)
        for label in ("热榜", "关注", "案例", "收藏", "更多"):
            self.assertIn(f"<span>{label}</span>", primary)
        self.assertNotIn("<span>主题</span>", primary)
        self.assertIn('href="topics.html"', more)
        self.assertIn('href="cases.html" class="on"', primary)

    def test_cases_page_leads_with_design_questions_and_supports_comparison(self):
        page = build_site.render_cases_page(
            [product_case()], [case_event()], build_site.load_css(),
        )
        self.assertIn("数据产品设计库", page)
        self.assertIn("data-case-search", page)
        self.assertIn('data-case-filter-kind="question"', page)
        self.assertIn('data-case-filter-kind="product"', page)
        self.assertIn('data-case-filter-kind="task"', page)
        self.assertIn('data-product-type="Data Agent"', page)
        self.assertIn('data-task-type="问数据"', page)
        self.assertIn('data-design-questions="入口与提问|可信与溯源"', page)
        self.assertIn('data-analytics-list="1" data-event-id="abcdef123456"', page)
        self.assertIn('src="media/abcdef123456/hero123456789.png"', page)
        self.assertIn("从设计问题开始", page)
        self.assertIn("要解决：", page)
        self.assertIn("可借鉴", page)
        self.assertIn("产品截图", page)
        self.assertNotIn("张原文图", page)
        self.assertIn("data-case-image", page)
        self.assertIn('class="case-card-title"', page)
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", page)
        self.assertIn("data-case-compare-toggle", page)
        self.assertIn("data-case-compare-dialog", page)
        self.assertIn("@media(max-width:600px)", page)
        self.assertRegex(page, r'src="cases\.js\?v=[a-f0-9]{12}"')

    def test_selected_detail_adds_design_breakdown_without_removing_reader_actions(self):
        event = case_event()
        page = build_site.render_detail(
            event, [event], build_site.load_css(), product_case=product_case(),
        )
        self.assertIn("产品设计拆解", page)
        self.assertIn("cases.html?question=", page)
        self.assertIn("官方说明", page)
        self.assertIn("DataHot 解读", page)
        self.assertIn("不能据此推断所有权限治理能力", page)
        self.assertIn('href="../cases.html"', page)
        self.assertIn('class="sbtn ghost favbtn"', page)
        self.assertIn("查看原文", page)
        self.assertIn('data-content-feedback', page)
        self.assertIn('href="../cases.html" class="on"', page)

    def test_detail_writer_enriches_only_manifest_selected_events(self):
        event = case_event()
        with tempfile.TemporaryDirectory() as directory:
            detail_dir = Path(directory) / "e"
            build_site.write_detail_pages(
                [event], "", detail_dir=detail_dir,
                tts_manifest={"items": {}}, site_root=Path(directory),
                product_cases=[product_case()],
            )
            rendered = (detail_dir / "abcdef123456.html").read_text(encoding="utf-8")
        self.assertIn("产品设计拆解", rendered)
        self.assertIn("这篇内容对你有用吗", rendered)


if __name__ == "__main__":
    unittest.main()
