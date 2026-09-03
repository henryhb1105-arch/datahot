import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import product_cases  # noqa: E402


MANIFEST_PATH = ROOT / "pipeline" / "product_cases.json"
LATEST_PATH = ROOT / "site" / "data" / "latest.json"


class ProductCaseManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
        cls.events = {
            event["event_id"]: event for event in cls.payload["events"]
        }
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_curated_manifest_loads_and_covers_the_promised_scope(self):
        cases = product_cases.load_product_cases(
            MANIFEST_PATH, events=self.payload,
        )

        self.assertGreaterEqual(len(cases), product_cases.MIN_CASES)
        self.assertLessEqual(len(cases), product_cases.MAX_CASES)
        self.assertEqual(
            {case["product_type"] for case in cases},
            set(product_cases.PRODUCT_TYPES),
        )
        self.assertGreaterEqual(len({case["task_type"] for case in cases}), 4)
        self.assertEqual(
            product_cases.product_case_event_ids(MANIFEST_PATH),
            frozenset(case["event_id"] for case in cases),
        )

    def test_every_case_references_an_existing_locally_cached_figure(self):
        cases = product_cases.load_product_cases(
            MANIFEST_PATH, events=self.payload,
        )

        for case in cases:
            with self.subTest(event_id=case["event_id"]):
                event = self.events.get(case["event_id"])
                self.assertIsNotNone(event)
                hero = product_cases.find_case_hero(event, case)
                self.assertIsNotNone(hero)
                cached_src = hero["cached_src"]
                self.assertTrue(
                    cached_src.startswith(f"../media/{case['event_id']}/")
                )
                cached_path = ROOT / "site" / cached_src.removeprefix("../")
                self.assertTrue(cached_path.is_file(), cached_path)
                self.assertGreater(cached_path.stat().st_size, 0)

    def test_official_facts_and_datahot_interpretation_stay_separate(self):
        cases = product_cases.load_product_cases(
            MANIFEST_PATH, events=self.payload,
        )

        for case in cases:
            with self.subTest(event_id=case["event_id"]):
                official = case["official_facts"]
                interpretation = case["datahot_interpretation"]
                self.assertTrue(official)
                self.assertTrue(interpretation)
                self.assertTrue(set(official).isdisjoint(interpretation))
                self.assertFalse(
                    any(text.startswith("DataHot解读") for text in official)
                )
                self.assertFalse(
                    any(text.startswith("官方说明") for text in interpretation)
                )

    def test_validation_rejects_missing_events_and_uncached_heroes(self):
        missing_event = copy.deepcopy(self.manifest)
        missing_event["cases"][0]["event_id"] = "000000000000"
        errors = product_cases.validation_errors(missing_event, self.payload)
        self.assertTrue(any("absent from the event payload" in error for error in errors))

        uncached_hero = copy.deepcopy(self.manifest)
        # This source figure belongs to the event but was not safely cached.
        uncached_hero["cases"][0]["hero_figure_id"] = "b-1692bd327793"
        errors = product_cases.validation_errors(uncached_hero, self.payload)
        self.assertTrue(
            any("does not resolve to a cached figure" in error for error in errors)
        )

    def test_loader_rejects_blurred_fact_and_interpretation_sections(self):
        payload = copy.deepcopy(self.manifest)
        payload["cases"][0]["official_facts"] = list(
            payload["cases"][0]["datahot_interpretation"]
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "product_cases.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must keep official_facts"):
                product_cases.load_product_cases(path, events=self.payload)

    def test_missing_manifest_is_an_empty_optional_feature(self):
        path = ROOT / "pipeline" / "not-present-product-cases.json"
        self.assertFalse(path.exists())
        self.assertEqual(product_cases.load_product_cases(path), [])
        self.assertEqual(product_cases.product_case_event_ids(path), frozenset())


if __name__ == "__main__":
    unittest.main()

