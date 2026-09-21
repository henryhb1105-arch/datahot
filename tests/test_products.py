import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from products import load_products, match_products, load_paths, render_paths_body
from design_studies import load_studies, library_records, study_path
from product_cases import load_product_cases
from case_readings import reading_path
from lite_data import lite_event, build_lite_payload
from products import recent_product_events, render_product_index, source_publication_time


class ProductIdentityTests(unittest.TestCase):
    def test_merged_reporting_and_x_share_date_cannot_refresh_an_old_article(self):
        merged = {"event_id": "old", "published": "2026-09-20", "items": [
            {"published": "2026-01-28"}, {"published": "2026-09-20"}]}
        unknown = {"event_id": "unknown", "published": "2026-09-20",
                   "source_date_label": "2026-05-13（X 分享日；原文日期未注明）"}
        curated = {"event_id": "curated", "published": "2026-09-20",
                   "source_date_label": "原文 2026-05-01（6 月 16 日更新）"}
        self.assertEqual(recent_product_events([merged, unknown, curated], reference_time="2026-09-21"), [])
        self.assertEqual(source_publication_time(merged).date().isoformat(), "2026-01-28")
        self.assertIsNone(source_publication_time(unknown))

    def test_recent_window_uses_original_date_and_excludes_future_or_unknown(self):
        rows = [
            {"event_id": "a", "published": "2026-09-20", "first_seen": "2026-09-21"},
            {"event_id": "b", "published": "2026-01-20", "first_seen": "2026-09-21"},
            {"event_id": "c", "first_seen": "2026-09-21"},
            {"event_id": "d", "published": "2026-09-22"},
            {"event_id": "e", "published": "bad"},
            {"event_id": "f", "published": "2026-08-22"},
        ]
        recent = recent_product_events(rows, reference_time="2026-09-21T00:00:00Z")
        self.assertEqual({e["event_id"] for e in recent}, {"a", "f"})

    def test_radar_shows_at_most_three_and_separates_original_from_collection(self):
        rows = [{"event_id": f"{i:012x}", "zh_title": f"Genie 执行评测 {i}",
                 "published": "2026-09-14T10:00:00+08:00", "first_seen": "2026-09-20T10:00:00+08:00"}
                for i in range(5)]
        rows.append({"event_id": "old", "zh_title": "Genie 旧文补录", "published": "2026-01-01", "first_seen": "2026-09-21"})
        page = render_product_index(rows, reference_time="2026-09-21T00:00:00Z")
        card = page.split('data-radar-product="databricks-genie"')[1].split('</article>')[0]
        self.assertEqual(card.count('<li>'), 3)
        self.assertIn("近 30 天 5 条", card)
        self.assertIn("全部 6 条资料", card)
        self.assertIn("原文 2026-09-14 · 收录 2026-09-20", card)
        self.assertNotIn("旧文补录", card)
        self.assertIn("只看已关注", page)

    def test_company_news_and_article_body_do_not_imply_product_update(self):
        event = {"event_id":"a"*12, "zh_title":"Snowflake 财报", "vendors":["Snowflake"],
                 "full_zh":"Cortex Agents", "items":[{"link":"https://www.snowflake.com/blog/earnings"}]}
        self.assertNotIn("snowflake-cortex", match_products(event))
        event["zh_title"] = "Cortex Agents 的执行评估"
        self.assertIn("snowflake-cortex", match_products(event))

    def test_domain_matching_is_exact_and_short_names_have_word_boundaries(self):
        self.assertNotIn("hex", match_products({"zh_title":"hexadecimal identifiers"}))
        self.assertNotIn("hex", match_products({"items":[{"link":"https://hex.tech.example.com/news"}]}))
        self.assertIn("hex", match_products({"items":[{"link":"https://learn.hex.tech/changelog/2026-05-12"}]}))

    def test_explicit_curated_identity_and_light_payload_survive_translation(self):
        event = {"event_id":"e12a2952d00e", "zh_title":"多源数据路由"}
        self.assertIn("fabric-data-agent", lite_event(event)["product_ids"])
        payload = build_lite_payload([], "2026-09-19", ranking=[])
        self.assertEqual(len(payload["products"]), 10)
        self.assertEqual(len({p["id"] for p in payload["products"]}), 10)

    def test_malformed_source_url_does_not_drop_other_product_evidence(self):
        event = {"items": [{"link": "https://[bad"}, {"link": "https://hex.tech/blog/"}]}
        self.assertEqual(match_products(event), ["hex"])
        self.assertEqual(match_products({"items": [{"link": "https://[bad"}]}), [])

    def test_reference_paths_resolve_to_existing_articles_and_cases(self):
        events = json.loads((ROOT / "site/data/latest.json").read_text())["events"]
        records, _ = library_records(load_product_cases(events=events), events, load_studies(events))
        cases = {}
        for case in records:
            study = case.get("study")
            key = study["slug"] if study else "case-" + case["event_id"]
            cases[key] = {"product":case["product"], "href":study_path(study) if study else reading_path(case)}
        payload = load_paths(events, cases)
        self.assertEqual(len(payload["paths"]), 5)
        self.assertEqual(sum(len(p["steps"]) for p in payload["paths"]), 15)
        page = render_paths_body(payload, events, cases)
        self.assertIn("实施建议，不是厂商功能承诺", page)
        self.assertIn("cases/metabase-metabot.html", page)
        for product in load_products():
            self.assertTrue(any(product["id"] in match_products(e) for e in events), product["id"])
