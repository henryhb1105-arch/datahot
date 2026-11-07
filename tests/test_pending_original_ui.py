import json
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402


def pending_event():
    title = 'Original <platform> & "data" story'
    summary = "Source summary <script>alert('x')</script> & details."
    return {
        "event_id": "pending-original",
        "enrichment_status": "pending",
        "zh_title": title,
        "zh_summary": summary,
        "reason": "STALE_RECOMMENDATION_MUST_NOT_APPEAR",
        "heat": 97,
        "importance": 50,
        "editorial_pick": True,
        "category": "platform",
        "category_label": "AI 数据平台",
        "topics": ["平台AI化"],
        "vendors": ["AWS"],
        "shelf": "evergreen",
        "published": "2026-11-07T03:00:00+00:00",
        "first_seen": "2026-11-07T04:00:00+00:00",
        "curated_at": "2026-11-07T05:00:00+00:00",
        "content_mode": "original",
        "source_language": "en",
        "content_parse": {"status": "ready", "quality_status": "pass", "strategy": "article"},
        "full_zh": "Available original body with <literal> markup & facts.",
        "items": [{
            "id": "original-source",
            "source": "AWS Big Data Blog",
            "title": title,
            "summary": summary,
            "link": "https://example.com/original?a=1&b=2",
            "published": "2026-11-07T03:00:00+00:00",
        }],
    }


def share_payload(page):
    return json.loads(re.search(r"var SH_EV = (.*?);\n", page).group(1))


class PendingOriginalRenderingTests(unittest.TestCase):
    def test_pending_card_retains_raw_copy_without_score_recommendation_or_featured_style(self):
        event = pending_event()
        card = build_site.render_card(event, top_rank=1)
        self.assertIn('>原文待处理</span>', card)
        self.assertIn('title="中文标题、摘要和推荐理由待处理"', card)
        self.assertIn('Original &lt;platform&gt; &amp; &quot;data&quot; story', card)
        self.assertIn("Source summary &lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; &amp; details.", card)
        self.assertIn('href="e/pending-original.html"', card)
        self.assertIn('data-editorial="false"', card)
        self.assertNotIn("STALE_RECOMMENDATION", card)
        self.assertNotIn("is-featured", card)
        self.assertNotIn("热度分", card)
        self.assertNotIn('class="top-rank"', card)
        self.assertNotIn("97", card)
        self.assertNotIn("<script>", card)
        # A pending record does not need a numeric heat claim at all.
        event.pop("heat")
        self.assertIn('>原文待处理</span>', build_site.render_card(event))

    def test_pending_detail_explains_editorial_status_and_keeps_original_body_and_links(self):
        event = pending_event()
        page = build_site.render_detail(event, [event], "")
        self.assertIn('<strong>原文待处理</strong>', page)
        self.assertIn("中文标题、摘要和推荐理由仍待 AI 处理", page)
        self.assertIn('<summary>来源摘要</summary>', page)
        self.assertIn("Available original body with &lt;literal&gt; markup &amp; facts.", page)
        self.assertIn('class="meta-source-link" href="https://example.com/original?a=1&amp;b=2"', page)
        self.assertIn('class="original-footer-link" href="https://example.com/original?a=1&amp;b=2"', page)
        self.assertNotIn('<strong>正文待核验</strong>', page)
        self.assertNotIn('<summary>DataHot 速览</summary>', page)
        self.assertNotIn('class="editorial-pick"', page)
        self.assertNotIn("STALE_RECOMMENDATION", page)
        self.assertNotIn("<script>alert('x')</script>", page)
        jsonld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page).group(1))
        self.assertEqual(jsonld["inLanguage"], "en")
        payload = share_payload(page)
        self.assertEqual(payload["status"], "原文待处理")
        self.assertEqual(payload["reason"], "")
        self.assertIsNone(payload["heat"])
        self.assertEqual(payload["summary"], event["zh_summary"])

    def test_body_completeness_notice_is_independent_of_pending_editorial_notice(self):
        event = pending_event()
        event["content_parse"]["quality_status"] = "warning"
        page = build_site.render_detail(event, [event], "")
        self.assertIn('aria-label="AI 处理状态"', page)
        self.assertIn('<strong>原文待处理</strong>', page)
        self.assertIn('aria-label="正文状态"', page)
        self.assertIn('<strong>正文待核验</strong>', page)
        self.assertIn("Available original body", page)

    def test_pending_detail_without_summary_does_not_invent_one(self):
        event = pending_event()
        event["zh_summary"] = ""
        event["full_zh"] = ""
        page = build_site.render_detail(event, [event], "")
        self.assertIn('<strong>原文待处理</strong>', page)
        self.assertNotIn('<details class="article-brief"', page)
        self.assertIn('class="meta-source-link" href="https://example.com/original?a=1&amp;b=2"', page)
        self.assertEqual(share_payload(page)["summary"], "")

    def test_legacy_provider_failure_uses_the_same_pending_notice(self):
        event = pending_event()
        event.pop("enrichment_status")
        event["reason"] = ""
        event["content_parse"]["metadata_translation"] = {"status": "provider_error"}
        self.assertIn('>原文待处理</span>', build_site.render_card(event))
        self.assertIn('<strong>原文待处理</strong>', build_site.render_detail(event, [event], ""))

    def test_pending_detail_does_not_offer_stale_ai_audio(self):
        event = pending_event()
        tts_item = {"status": "ready", "audio_path": "audio/2026/11/abcdef123456-abcdef123456.mp3"}
        page = build_site.render_detail(event, [event], "", tts_item=tts_item)
        self.assertNotIn("data-tts-open", page)
        self.assertNotIn(tts_item["audio_path"], page)
        normal = dict(event, enrichment_status="complete")
        self.assertIn(tts_item["audio_path"], build_site.render_detail(normal, [normal], "", tts_item=tts_item))

    def test_pending_structured_original_and_unsafe_source_link_stay_sanitized(self):
        event = pending_event()
        event["items"][0]["link"] = "javascript:alert(42)"
        event["content_blocks"] = [{
            "type": "paragraph",
            "children": [{"type": "text", "text": "Structured <original> body.",
                          "marks": [{"type": "link", "href": "javascript:alert(43)"}]}],
        }]
        page = build_site.render_detail(event, [event], "")
        self.assertIn("Structured &lt;original&gt; body.", page)
        self.assertNotIn("javascript:alert", page)
        self.assertNotIn('class="meta-source-link"', page)
        self.assertIn('<strong>原文待处理</strong>', page)

    def test_complete_record_keeps_normal_summary_reason_heat_and_featured_state(self):
        event = pending_event()
        event.update({"enrichment_status": "complete", "reason": "已完成的推荐理由"})
        card = build_site.render_card(event, top_rank=1)
        self.assertNotIn("原文待处理", card)
        self.assertIn('class="heatnum is-featured"', card)
        self.assertIn("编辑精选 97", card)
        self.assertIn("已完成的推荐理由", card)
        self.assertIn('class="top-rank"', card)
        page = build_site.render_detail(event, [event], "")
        self.assertNotIn('<strong>原文待处理</strong>', page)
        self.assertIn('<summary>DataHot 速览</summary>', page)
        self.assertIn('<b>为什么值得关注：</b>已完成的推荐理由', page)
        self.assertIn('class="editorial-pick"', page)
        self.assertEqual(share_payload(page)["heat"], 97)
        self.assertEqual(share_payload(page)["reason"], "已完成的推荐理由")

    def test_topic_updates_label_pending_and_do_not_promote_as_intro_reading(self):
        event = pending_event()
        topic = next(topic for topic in build_site.TOPICS_META if topic["name"] == "平台AI化")
        page = build_site.render_topic_page(
            topic, [event], "", reference_time=datetime(2026, 11, 7, 6, tzinfo=timezone.utc),
        )
        self.assertEqual(page.count(" · 原文待处理"), 2)
        self.assertNotIn('id="topicReading"', page)
        normal = dict(event, enrichment_status="complete")
        normal_page = build_site.render_topic_page(topic, [normal], "")
        self.assertIn('id="topicReading"', normal_page)
        self.assertNotIn("原文待处理", normal_page)

    def test_pending_and_rejected_originals_are_not_promoted_as_related_reading(self):
        pending = pending_event()
        normal = dict(pending, event_id="complete-original", enrichment_status="complete")
        rejected = dict(pending, event_id="rejected-original", enrichment_status="rejected")
        complete = dict(normal, event_id="other-complete-original")
        self.assertIsNotNone(build_site.related_event_score(normal, pending))
        self.assertEqual(build_site.select_related_events(normal, [normal, pending, rejected, complete]), [complete])


if __name__ == "__main__":
    unittest.main()
