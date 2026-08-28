import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from analytics_metrics import compute_metrics, read_export_lines  # noqa: E402
from analytics_schema import ALLOWED_FIELDS, validate_event  # noqa: E402
import build_site  # noqa: E402


def uuid(number):
    return f"00000000-0000-4000-8000-{number:012x}"


def event(number, name, *, ts="2026-08-01T00:00:00+00:00", session=1, device=1,
          event_id="", **extra):
    payload = {
        "schema_version": 1, "event_uuid": uuid(number), "name": name, "ts": ts,
        "environment": "production", "site_id": "datahot", "page": "home",
        "event_id": event_id, "category": "platform", "source": "Databricks Blog",
        "session_id": uuid(100 + session), "device_id": uuid(200 + device),
        "sequence": number, "viewport": "medium", "referrer": "direct",
    }
    payload.update(extra)
    return payload


class AnalyticsSchemaTests(unittest.TestCase):
    def test_schema_accepts_minimal_event_and_rejects_private_unknown_fields(self):
        valid = event(1, "search", query_bucket="4-8", result_count=12)
        self.assertEqual(validate_event(valid), [])
        for private_field in ("body", "search_text", "api_key", "email", "latitude", "longitude", "user_agent"):
            unsafe = dict(valid)
            unsafe[private_field] = "private"
            self.assertIn("unknown_fields", validate_event(unsafe))
            self.assertNotIn(private_field, ALLOWED_FIELDS)

    def test_event_specific_requirements_are_enforced(self):
        self.assertIn("event_id_required", validate_event(event(2, "detail_click")))
        self.assertIn("action_required", validate_event(event(3, "favorite_toggle", event_id="aaaaaaaaaaaa")))
        self.assertIn("query_bucket_required", validate_event(event(4, "search")))
        self.assertIn("environment", validate_event(event(5, "session_start", environment="development")))
        self.assertEqual(validate_event(event(
            6, "content_feedback", event_id="aaaaaaaaaaaa",
            action="not_useful", feedback_reason="marketing", page="detail",
        )), [])
        self.assertIn("feedback_reason", validate_event(event(
            7, "content_feedback", event_id="aaaaaaaaaaaa",
            action="useful", feedback_reason="free text", page="detail",
        )))

    def test_insight_category_is_valid(self):
        self.assertEqual(validate_event(event(6, "session_start", category="insight")), [])


class AnalyticsMetricTests(unittest.TestCase):
    def sample(self):
        events = [
            event(1, "session_start", session=1, device=1),
            event(2, "list_exposure", session=1, device=1, event_id="aaaaaaaaaaaa"),
            event(3, "detail_click", session=1, device=1, event_id="aaaaaaaaaaaa"),
            event(4, "outbound_click", session=1, device=1, event_id="aaaaaaaaaaaa"),
            event(5, "favorite_toggle", session=1, device=1, event_id="aaaaaaaaaaaa", action="add"),
            event(6, "search", session=1, device=1, query_bucket="4-8", result_count=3),
            event(7, "filter", session=1, device=1, filter="data-agent"),
            event(8, "session_start", session=2, device=2),
            event(9, "list_exposure", session=2, device=2, event_id="bbbbbbbbbbbb"),
            event(10, "session_start", ts="2026-08-05T00:00:00+00:00", session=3, device=1),
            event(11, "session_start", ts="2026-08-10T00:00:00+00:00", session=4, device=3),
            event(12, "content_feedback", session=1, device=1, event_id="aaaaaaaaaaaa",
                  action="useful", feedback_reason="solid", page="detail"),
        ]
        return events

    def test_metrics_and_seven_day_return_use_valid_deduplicated_events(self):
        events = self.sample()
        events.append(dict(events[1]))  # same event_uuid: transport duplicate
        unsafe = dict(events[0])
        unsafe["event_uuid"] = uuid(99)
        unsafe["body"] = "must reject"
        events.append(unsafe)
        report = compute_metrics(events)
        quality, metrics = report["quality"], report["metrics"]
        self.assertEqual(quality["duplicate_events"], 1)
        self.assertEqual(quality["invalid_events"], 1)
        self.assertEqual(quality["invalid_reasons"], {"unknown_fields": 1})
        self.assertEqual(quality["orphan_session_events"], 0)
        self.assertEqual(metrics["list_exposures"], 2)
        self.assertEqual(metrics["detail_click_through_rate"], 0.5)
        self.assertEqual(metrics["outbound_click_rate"], 1.0)
        self.assertEqual(metrics["favorite_rate"], 0.5)
        self.assertEqual(metrics["content_feedback_count"], 1)
        self.assertEqual(metrics["useful_feedback_rate"], 1.0)
        self.assertEqual(metrics["content_feedback_reasons"], {"solid": 1})
        self.assertEqual(metrics["search_usage_rate"], 0.25)
        self.assertEqual(metrics["filter_usage_rate"], 0.25)
        self.assertEqual(metrics["seven_day_return_cohort"], 2)
        self.assertEqual(metrics["seven_day_return_rate"], 0.5)

    def test_reader_accepts_batches_and_reports_malformed_lines(self):
        lines = [json.dumps({"events": self.sample()[:2]}), "not-json"]
        events, parse_errors = read_export_lines(lines)
        self.assertEqual(len(events), 2)
        self.assertEqual(parse_errors, 1)


class AnalyticsBuildIntegrationTests(unittest.TestCase):
    def base_event(self):
        return {
            "event_id": "aaaaaaaaaaaa", "zh_title": "Analytics", "zh_summary": "Summary",
            "reason": "", "full_zh": "Body", "category": "platform",
            "category_label": "AI 数据平台", "vendors": [], "topics": [], "heat": 50,
            "importance": 50, "signal": 0, "shelf": "news",
            "published": "2026-08-11T12:00:00+08:00", "first_seen": "2026-08-11T12:00:00+08:00",
            "items": [{
                "id": "source-1", "source": "Databricks Blog", "link": "https://example.com/post",
                "published": "2026-08-11T12:00:00+08:00", "title": "Source",
            }],
        }

    def test_disabled_by_default_and_https_endpoint_required(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIn('data-enabled="false"', build_site.analytics_head())
        with patch.dict(os.environ, {"ANALYTICS_ENABLED": "true", "ANALYTICS_ENDPOINT": "http://unsafe.test"}, clear=True):
            head = build_site.analytics_head()
            self.assertIn('data-enabled="false"', head)
            self.assertIn('data-endpoint=""', head)
        with patch.dict(os.environ, {"ANALYTICS_ENABLED": "true", "ANALYTICS_ENDPOINT": "https://metrics.example/collect"}, clear=True):
            self.assertIn('data-enabled="true"', build_site.analytics_head("../"))

    def test_cards_and_detail_have_event_context_at_trigger_points(self):
        item = self.base_event()
        card = build_site.render_card(item)
        self.assertIn('data-analytics-list="1"', card)
        self.assertIn('data-event-id="aaaaaaaaaaaa"', card)
        detail = build_site.render_detail(item, [item], "")
        self.assertIn('data-page="detail" data-event-id="aaaaaaaaaaaa"', detail)
        self.assertIn('data-analytics="outbound"', detail)
        self.assertIn('src="../analytics.js"', detail)

    def test_client_source_does_not_access_fingerprinting_or_location_apis(self):
        source = (ROOT / "pipeline" / "assets" / "analytics.js").read_text(encoding="utf-8")
        for forbidden in ("navigator.userAgent", "document.cookie", "geolocation", "canvas.toDataURL", "innerText"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
