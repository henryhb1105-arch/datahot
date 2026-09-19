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


class ProductIdentityTests(unittest.TestCase):
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
