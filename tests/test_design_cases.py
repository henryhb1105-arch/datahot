import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build_site
import design_studies as studies
import case_readings as readings
import case_visuals as visuals
from product_cases import load_product_cases


class DesignStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = json.loads((ROOT / "site/data/latest.json").read_text())["events"]
        cls.payload = json.loads(studies.MANIFEST.read_text())
        cls.studies = studies.load_studies(cls.events)
        cls.cases = load_product_cases(events=cls.events)

    def test_six_studies_with_three_new_products_and_unique_stable_ids(self):
        self.assertEqual(len(self.studies), 6)
        self.assertEqual(sum(bool(s.get("event_id")) for s in self.studies), 3)
        identifiers = [studies.case_id(s) for s in self.studies]
        self.assertEqual(len(set(identifiers)), 6)
        for identifier in identifiers:
            self.assertRegex(identifier, r"^[a-f0-9]{12}$")
        all_event_ids = {e["event_id"] for e in self.events}
        self.assertTrue(all(studies.case_id(s) not in all_event_ids for s in self.studies if not s.get("event_id")))

    def test_all_images_are_real_local_files_and_sources_are_public_https(self):
        from PIL import Image
        for study in self.studies:
            for step in studies.resolved_steps(study, self.events):
                with self.subTest(study=study["slug"], step=step["title"]):
                    path = ROOT / ("pipeline/assets/" + step["src"] if step.get("asset") else "site/" + step["src"])
                    with Image.open(path) as image:
                        # A native 430px sharing dialog is readable at 1:1;
                        # do not upscale it just to meet a screenshot quota.
                        self.assertGreaterEqual(image.width, 320)
                        self.assertGreaterEqual(image.height, 120)
                        self.assertLess(image.width * image.height, 24000000)
                        image.verify()
                    self.assertTrue(studies.https_url(step["source_url"]))

    def test_library_merges_upgrades_without_duplicate_news_or_mutations(self):
        original_events, original_cases = copy.deepcopy(self.events), copy.deepcopy(self.cases)
        records, _ = studies.library_records(self.cases, self.events, self.studies)
        self.assertEqual(len(records), len(self.cases) + 3)
        self.assertEqual(len({r["event_id"] for r in records}), len(records))
        self.assertEqual(self.events, original_events)
        self.assertEqual(self.cases, original_cases)
        page = build_site.render_cases_page(self.cases, self.events, "", self.studies)
        self.assertEqual(page.count("data-case-card data-case-id="), 21)
        self.assertEqual(page.count("分步看设计"), 6)
        self.assertIn('href="cases/compare.html"', page)
        self.assertIn("架构/方法参考", page)
        self.assertNotIn("张原文图", page)

    def test_steps_work_without_js_and_have_traceable_sources_and_lessons(self):
        for study in self.studies:
            body = studies.render_study_body(study, self.studies, self.events, "")
            self.assertEqual(body.count("data-study-step="), len(study["steps"]))
            self.assertNotIn('data-study-step="1" hidden', body)
            self.assertIn("data-case-image", body)
            self.assertIn("资料出处", body)
            self.assertIn("DataHot 解读", body)
            self.assertIn("data-fav-record", body)
            self.assertIn("detail_path", body)
            self.assertIn('data-feedback-kind="design"', body)
            if study.get("event_id"):
                self.assertIn(f'../e/{study["event_id"]}.html', body)
            self.assertEqual(body.count('class="study-evidence"'), len(study["lessons"]))

    def test_comparison_references_specific_steps_and_preserves_unknowns(self):
        body = studies.render_comparison_body(self.studies, self.events)
        for slug in studies.COMPARISON_SLUGS:
            self.assertIn(slug + ".html#step-", body)
        self.assertIn("历史", body)
        self.assertIn("未展示", body)
        self.assertEqual(body.count("查看操作"), 12)

    def test_invalid_evidence_and_unsafe_paths_fail_closed(self):
        mutations = [
            (lambda p: p["studies"][0]["steps"][0].update(asset="../private.png"), "unsafe asset"),
            (lambda p: p["studies"][0]["steps"][0].update(source_id="missing"), "source missing"),
            (lambda p: p["studies"][0]["sources"][0].update(url="javascript:alert(1)"), "evidence source"),
            (lambda p: p["studies"][0]["lessons"][0].update(steps=[99]), "lesson evidence"),
            (lambda p: p["studies"][0]["comparison"]["edit"].update(step=0), "comparison evidence"),
            (lambda p: p["studies"][3]["steps"][0].update(figure_id="missing"), "figure missing"),
            (lambda p: p["studies"][0].update(hero_step=0), "hero_step"),
            (lambda p: p["studies"][0].update(sources=None), "requires evidence"),
            (lambda p: p["studies"][0]["sources"][0].update(url="https://[broken"), "evidence source"),
            (lambda p: p["studies"][0].update(lessons=[None]), "lesson must"),
            (lambda p: p["studies"][0].update(comparison=[]), "comparison must"),
        ]
        for mutate, expected in mutations:
            payload = copy.deepcopy(self.payload)
            mutate(payload)
            self.assertTrue(any(expected in e for e in studies.validate_studies(payload, self.events)), expected)

    def test_editorial_text_is_escaped(self):
        study = copy.deepcopy(self.studies[0])
        study["title"] = '<script>alert("x")</script>'
        body = studies.render_study_body(study, self.studies, self.events, "")
        self.assertNotIn('<script>alert("x")</script>', body)
        self.assertIn("&lt;script&gt;", body)

    def test_fifteen_reference_readings_preserve_evidence_articles_and_ids(self):
        upgraded = {s.get("event_id") for s in self.studies}
        references = [c for c in self.cases if c["event_id"] not in upgraded]
        self.assertEqual(len(references), 15)
        events = {e["event_id"]: e for e in self.events}
        before = copy.deepcopy(events)
        for case in references:
            event = events[case["event_id"]]
            figures = readings.reading_figures(case, event)
            original = {b["cached_src"] for b in event["content_blocks"] if b.get("type") == "figure" and b.get("cached_src")}
            self.assertEqual({f["cached_src"] for f in figures}, original)
            body = readings.render_reading_body(case, event, "")
            self.assertEqual(body.count("data-study-step="), len(figures))
            self.assertIn(f'../e/{case["event_id"]}.html', body)
            self.assertIn(f'data-fav="{case["event_id"]}"', body)
            self.assertIn(readings.reading_path(case), body)
            self.assertIn("配图不代表一次连续操作", body)
            self.assertIn('data-step-label="配图"', body)
            self.assertIn("资料出处", body)
            for figure in figures:
                self.assertTrue((ROOT / "site" / figure["cached_src"].removeprefix("../")).is_file())
        self.assertEqual(events, before)

    def test_focal_regions_match_original_dimensions_and_viewer_keeps_original(self):
        from PIL import Image
        for src, region in visuals.load_visuals().items():
            path = ROOT / ("pipeline/assets/" + src if src.startswith("case-media/") else "site/" + src)
            with Image.open(path) as image:
                self.assertEqual(image.size, (region["image_width"], region["image_height"]))
            self.assertIn(f'src="{src}"', visuals.card_image(src, "preview"))
            self.assertIn("局部预览", visuals.card_image(src, "preview"))
            detail = visuals.detail_image("../" + src, "image")
            self.assertIn(f'src="../{src}"', detail)
            self.assertIn('aria-hidden="true"', detail)
            self.assertIn(region["label"], visuals.focus_caption(src))
        body = readings.render_reading_body(next(c for c in self.cases if c["event_id"] == "29e0b8236c7e"), next(e for e in self.events if e["event_id"] == "29e0b8236c7e"), "")
        self.assertIn('href="../media/29e0b8236c7e/d45f74e73e29148873a6a60f.png" data-case-image', body)

    def test_case_pages_reference_versioned_scripts(self):
        page = build_site.render_cases_page(self.cases, self.events, "", self.studies)
        self.assertRegex(page, r'src="cases\.js\?v=[a-f0-9]{12}"')
        self.assertRegex(page, r'src="design-studies\.js\?v=[a-f0-9]{12}"')
        for study in self.studies:
            body = studies.render_study_body(study, self.studies, self.events, "")
            self.assertRegex(body, r'src="\.\./design-studies\.js\?v=[a-f0-9]{12}"')
        comparison = studies.render_comparison_body(self.studies, self.events)
        self.assertRegex(comparison, r'src="\.\./design-studies\.js\?v=[a-f0-9]{12}"')


if __name__ == "__main__":
    unittest.main()
