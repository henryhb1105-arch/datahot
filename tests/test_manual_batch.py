import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from import_manual_batch import import_batch, iso_timestamp, norm_url, validate_batch  # noqa: E402


class ManualBatchTests(unittest.TestCase):
    def _write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_z_timestamp_is_normalized_for_site_builder(self):
        self.assertEqual(iso_timestamp("2026-03-31T00:00:00Z"), "2026-03-31T00:00:00+00:00")

    def test_insight_category_is_accepted(self):
        record = {
            "zh_title": "人才洞察",
            "zh_summary": "员工数据揭示技能缺口。",
            "reason": "支持人才规划决策。",
            "full_zh": "正文",
            "source_title": "People analytics insight",
            "source_url": "https://example.com/insight",
            "discovery_url": "https://x.com/example/status/55",
            "discovery_account": "example",
            "published": "2026-08-12T00:00:00+08:00",
            "category": "insight",
        }
        rows = validate_batch({
            "schema_version": 1,
            "ingested_at": "2026-08-12T08:00:00+08:00",
            "items": [record],
        })
        self.assertEqual(rows[0]["category"], "insight")

    def test_import_is_idempotent_and_enriches_existing_canonical_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            latest_path = tmp / "latest.json"
            batch_path = tmp / "batch.json"
            existing_url = "https://example.com/existing"
            self._write_json(latest_path, {
                "generated_at": "2026-08-11T00:00:00+08:00",
                "top": [],
                "events": [{
                    "event_id": "existing0001",
                    "zh_title": "已有事件",
                    "zh_summary": "已有中文摘要",
                    "reason": "已有推荐理由",
                    "category": "platform",
                    "importance": 70,
                    "heat": 55,
                    "published": "2026-08-11T00:00:00+08:00",
                    "first_seen": "2026-08-11T01:00:00+08:00",
                    "items": [{"link": existing_url, "source": "Official"}],
                }],
            })
            base_record = {
                "zh_title": "新的人工精选事件",
                "zh_summary": "这是一段新的中文摘要。",
                "reason": "这是一段推荐理由。",
                "full_zh": "## 关键事实\n正文",
                "source_title": "New event",
                "source_url": "https://example.com/new",
                "discovery_url": "https://x.com/example/status/2",
                "discovery_account": "example",
                "published": "2026-08-12T00:00:00+08:00",
                "category": "agent",
                "vendors": ["Example"],
                "topics": ["Data Agent"],
                "importance": 80,
            }
            existing_record = dict(base_record)
            existing_record.update({
                "source_url": existing_url,
                "discovery_url": "https://x.com/example/status/1",
            })
            self._write_json(batch_path, {
                "schema_version": 1,
                "batch_id": "test",
                "ingested_at": "2026-08-12T08:00:00+08:00",
                "items": [existing_record, base_record],
            })

            first = import_batch(batch_path, latest_path)
            second = import_batch(batch_path, latest_path)
            result = json.loads(latest_path.read_text(encoding="utf-8"))

            self.assertEqual(first, {
                "batch_id": "test", "records": 2, "added": 1,
                "enriched": 1, "unchanged": 0,
            })
            self.assertEqual(second["added"], 0)
            self.assertEqual(second["enriched"], 0)
            self.assertEqual(second["unchanged"], 2)
            self.assertEqual(len(result["events"]), 2)
            all_links = [
                norm_url(item["link"])
                for event in result["events"] for item in event["items"]
            ]
            self.assertEqual(len(all_links), len(set(all_links)))

    def test_duplicate_discovery_url_is_rejected(self):
        record = {
            "zh_title": "标题",
            "zh_summary": "摘要",
            "reason": "理由",
            "full_zh": "正文",
            "source_title": "Title",
            "source_url": "https://example.com/a",
            "discovery_url": "https://x.com/example/status/1",
            "discovery_account": "example",
            "published": "2026-08-12T00:00:00+08:00",
            "category": "agent",
        }
        duplicate = dict(record, source_url="https://example.com/b")
        with self.assertRaisesRegex(ValueError, "duplicate discovery URL"):
            validate_batch({
                "schema_version": 1,
                "ingested_at": "2026-08-12T08:00:00+08:00",
                "items": [record, duplicate],
            })

    def test_canonical_only_evergreen_item_has_no_fake_x_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            latest_path = tmp / "latest.json"
            batch_path = tmp / "batch.json"
            self._write_json(latest_path, {
                "generated_at": "2026-08-11T00:00:00+08:00",
                "top": [],
                "events": [],
            })
            record = {
                "zh_title": "HR AI研究",
                "zh_summary": "基于HR从业者调查的研究。",
                "reason": "帮助HR团队评估AI应用。",
                "full_zh": "## 关键发现\n正文",
                "source_name": "SHRM",
                "source_title": "The State of AI in HR 2026",
                "source_url": "https://example.com/hr-ai",
                "published": "2026-03-31T00:00:00Z",
                "category": "insight",
                "topics": ["组织人才"],
                "shelf": "evergreen",
            }
            self._write_json(batch_path, {
                "schema_version": 1,
                "batch_id": "canonical-only",
                "ingested_at": "2026-08-12T18:58:00+08:00",
                "items": [record],
            })

            first = import_batch(batch_path, latest_path)
            second = import_batch(batch_path, latest_path)
            event = json.loads(latest_path.read_text(encoding="utf-8"))["events"][0]

            self.assertEqual(first["added"], 1)
            self.assertEqual(second["unchanged"], 1)
            self.assertEqual(event["shelf"], "evergreen")
            self.assertEqual(event["category_label"], "AI分析")
            self.assertEqual(event["published"], "2026-03-31T00:00:00+00:00")
            self.assertEqual(event["items"][0]["source"], "SHRM")
            self.assertNotIn("discovery_url", event)
            self.assertNotIn("discovery_source", event)

    def test_discovery_fields_must_be_provided_together(self):
        record = {
            "zh_title": "标题",
            "zh_summary": "摘要",
            "reason": "理由",
            "full_zh": "正文",
            "source_title": "Title",
            "source_url": "https://example.com/a",
            "discovery_url": "https://x.com/example/status/1",
            "published": "2026-08-12T00:00:00+08:00",
            "category": "insight",
        }
        with self.assertRaisesRegex(ValueError, "must be provided together"):
            validate_batch({
                "schema_version": 1,
                "ingested_at": "2026-08-12T08:00:00+08:00",
                "items": [record],
            })

    def test_production_batch_contains_ten_unique_x_posts(self):
        batch = json.loads((
            ROOT / "pipeline" / "manual_batches" / "2026-08-12-x-first.json"
        ).read_text(encoding="utf-8"))
        records = validate_batch(batch)
        self.assertEqual(len(records), 10)
        self.assertEqual(len({norm_url(row["discovery_url"]) for row in records}), 10)
        self.assertEqual(batch["issue"], 42)

    def test_hr_ai_batch_contains_six_reviewed_people_insights(self):
        batch = json.loads((
            ROOT / "pipeline" / "manual_batches" / "2026-08-12-hr-ai-insights.json"
        ).read_text(encoding="utf-8"))
        records = validate_batch(batch)

        self.assertEqual(batch["issue"], 63)
        self.assertEqual(len(records), 6)
        self.assertTrue(all(row["category"] == "insight" for row in records))
        self.assertTrue(all(row["topics"] == ["组织人才"] for row in records))
        self.assertTrue(all(row["shelf"] == "evergreen" for row in records))
        self.assertEqual(len({norm_url(row["source_url"]) for row in records}), 6)

    def test_hr_ai_reports_batch_contains_eight_reviewed_people_insights(self):
        batch = json.loads((
            ROOT / "pipeline" / "manual_batches" / "2026-08-12-hr-ai-reports.json"
        ).read_text(encoding="utf-8"))
        records = validate_batch(batch)

        self.assertEqual(batch["issue"], 87)
        self.assertEqual(len(records), 8)
        self.assertTrue(all(row["category"] == "insight" for row in records))
        self.assertTrue(all(row["topics"] == ["组织人才"] for row in records))
        self.assertTrue(all(row["shelf"] == "evergreen" for row in records))
        self.assertEqual(len({norm_url(row["source_url"]) for row in records}), 8)

    def test_production_latest_contains_each_batch_link_once(self):
        batch = json.loads((
            ROOT / "pipeline" / "manual_batches" / "2026-08-12-x-first.json"
        ).read_text(encoding="utf-8"))
        latest = json.loads((
            ROOT / "site" / "data" / "latest.json"
        ).read_text(encoding="utf-8"))
        links = [
            norm_url(item["link"])
            for event in latest["events"]
            for item in event.get("items", [])
        ]

        for record in validate_batch(batch):
            with self.subTest(title=record["zh_title"]):
                self.assertEqual(links.count(norm_url(record["source_url"])), 1)
                self.assertEqual(links.count(norm_url(record["discovery_url"])), 1)

    def test_production_latest_contains_each_hr_ai_source_once(self):
        batch = json.loads((
            ROOT / "pipeline" / "manual_batches" / "2026-08-12-hr-ai-insights.json"
        ).read_text(encoding="utf-8"))
        latest = json.loads((
            ROOT / "site" / "data" / "latest.json"
        ).read_text(encoding="utf-8"))
        links = [
            norm_url(item["link"])
            for event in latest["events"]
            for item in event.get("items", [])
        ]

        for record in validate_batch(batch):
            with self.subTest(title=record["zh_title"]):
                self.assertEqual(links.count(norm_url(record["source_url"])), 1)

    def test_production_latest_contains_each_hr_ai_report_once(self):
        batch = json.loads((
            ROOT / "pipeline" / "manual_batches" / "2026-08-12-hr-ai-reports.json"
        ).read_text(encoding="utf-8"))
        latest = json.loads((
            ROOT / "site" / "data" / "latest.json"
        ).read_text(encoding="utf-8"))
        links = [
            norm_url(item["link"])
            for event in latest["events"]
            for item in event.get("items", [])
        ]

        for record in validate_batch(batch):
            with self.subTest(title=record["zh_title"]):
                self.assertEqual(links.count(norm_url(record["source_url"])), 1)


if __name__ == "__main__":
    unittest.main()
