import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402


def event():
    return {
        "event_id": "aaaaaaaaaaaa", "zh_title": "数据平台深度文章",
        "zh_summary": "文章包含可核验数据和实现方法。", "reason": "值得关注。",
        "full_zh": "正文", "category": "platform", "category_label": "AI 数据平台",
        "vendors": ["Snowflake"], "topics": ["语义层"], "heat": 70,
        "importance": 80, "quality_score": 80, "trend_score": 62,
        "signal": 0, "shelf": "news", "published": "2026-08-28T08:00:00+08:00",
        "first_seen": "2026-08-28T09:00:00+08:00",
        "items": [{
            "id": "source-1", "source": "Engineering Blog",
            "link": "https://example.com/post", "published": "2026-08-28T08:00:00+08:00",
            "title": "Original title",
        }],
    }


class ContentFeedbackBuildTests(unittest.TestCase):
    def test_detail_exposes_compact_feedback_after_article(self):
        page = build_site.render_detail(event(), [event()], "")
        self.assertIn("这篇内容对你有用吗？", page)
        self.assertIn('data-feedback-value="useful"', page)
        self.assertIn('data-feedback-reason="marketing"', page)
        self.assertIn('src="../content-feedback.js"', page)
        self.assertIn('&quot;topics&quot;:[&quot;语义层&quot;]', page)

    def test_privacy_copy_separates_local_fit_from_optional_aggregate(self):
        page = build_site.render_privacy_page("")
        self.assertIn("文章反馈默认保存在本机", page)
        self.assertIn("有用/没用", page)
        self.assertIn("不发送评价文字或正文", page)


if __name__ == "__main__":
    unittest.main()
