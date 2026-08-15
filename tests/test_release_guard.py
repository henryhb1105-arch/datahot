import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from release_guard import PROTECTED_EVENT_IDS, ReleaseGuardError, assess_release  # noqa: E402


NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


def event(event_id, *, days_ago=1):
    observed = NOW - timedelta(days=days_ago)
    return {
        "event_id": event_id,
        "first_seen": observed.isoformat(),
        "published": observed.isoformat(),
    }


def payload(*events):
    return {"events": list(events)}


def with_article(item, text="这是经过清洗、能够稳定展示给读者的可信正文。"):
    item["content_blocks"] = [{
        "type": "paragraph",
        "children": [{"type": "text", "text": text * 30, "marks": []}],
    }]
    return item


def protected_events():
    return [event(event_id, days_ago=60) for event_id in sorted(PROTECTED_EVENT_IDS)]


class ReleaseGuardTests(unittest.TestCase):
    def setUp(self):
        self.protected = protected_events()
        self.recent = event("recent-a")
        self.baseline = payload(*self.protected, self.recent)
        self.baseline_ids = {item["event_id"] for item in self.baseline["events"]}

    def assess(self, candidate, *, baseline_details=None, candidate_details=None, **kwargs):
        candidate_ids = {item["event_id"] for item in candidate["events"]}
        return assess_release(
            self.baseline,
            candidate,
            baseline_details if baseline_details is not None else self.baseline_ids,
            candidate_details if candidate_details is not None else candidate_ids,
            source_sha=kwargs.pop("source_sha", "candidate-sha"),
            run_id="12345",
            issue=kwargs.pop("issue", "automatic"),
            baseline_manifest=kwargs.pop("baseline_manifest", {"source_sha": "baseline-sha"}),
            now=NOW,
            **kwargs,
        )

    def test_healthy_release_emits_manifest_and_publishes_new_sha(self):
        self.baseline["events"][-1] = with_article(self.recent)
        candidate = payload(*self.protected, self.recent, event("recent-b"))
        manifest = self.assess(candidate)
        self.assertTrue(manifest["should_publish"])
        self.assertEqual(manifest["event_count"], 4)
        self.assertEqual(manifest["recent_event_count"], 2)
        self.assertEqual(manifest["detail_count"], 4)
        self.assertEqual(manifest["overrides"], [])
        self.assertFalse(manifest["allow_shrink"])
        self.assertEqual(
            manifest["content_quality"],
            {"structured": 1, "renderable": 1, "suspect": 0},
        )

    def test_existing_structured_article_cannot_lose_its_blocks(self):
        with_article(self.recent)
        candidate_recent = event("recent-a")
        candidate = payload(*self.protected, candidate_recent)

        with self.assertRaisesRegex(ReleaseGuardError, "lost blocks"):
            self.assess(candidate)

    def test_new_suspect_structured_article_is_blocked(self):
        suspect = event("recent-b")
        suspect["content_blocks"] = [
            {
                "type": "paragraph",
                "children": [{"type": "text", "text": "View pricing", "marks": []}],
            },
            {
                "type": "paragraph",
                "children": [{
                    "type": "text", "text": "Measured product results and technical facts. " * 30,
                    "marks": [],
                }],
            },
        ]
        candidate = payload(*self.protected, self.recent, suspect)

        with self.assertRaisesRegex(ReleaseGuardError, "new suspect structured"):
            self.assess(candidate)

    def test_event_count_and_recent_event_regression_are_blocked(self):
        candidate = payload(*self.protected)
        with self.assertRaisesRegex(ReleaseGuardError, "recent event"):
            self.assess(candidate)

    def test_expired_news_may_roll_out_without_a_shrink_override(self):
        stale = event("expired-news", days_ago=90)
        baseline = payload(*self.protected, self.recent, stale)
        baseline_ids = {item["event_id"] for item in baseline["events"]}
        candidate = payload(*self.protected, self.recent)
        candidate_ids = {item["event_id"] for item in candidate["events"]}

        manifest = assess_release(
            baseline,
            candidate,
            baseline_ids,
            candidate_ids,
            source_sha="candidate-sha",
            run_id="12345",
            issue="automatic",
            baseline_manifest={"source_sha": "baseline-sha"},
            now=NOW,
        )
        self.assertEqual(manifest["overrides"], [])
        self.assertEqual(manifest["baseline"]["allowed_expired_count"], 1)
        self.assertEqual(manifest["baseline"]["expired_removed_count"], 1)

    def test_recent_event_replacement_is_blocked_even_when_total_is_equal(self):
        candidate = payload(*self.protected, event("old-replacement", days_ago=90))
        with self.assertRaisesRegex(ReleaseGuardError, "recent event"):
            self.assess(candidate)

    def test_detail_page_count_regression_is_blocked(self):
        candidate = payload(*self.protected, self.recent)
        with self.assertRaisesRegex(ReleaseGuardError, "details 4 -> 3"):
            self.assess(
                candidate,
                baseline_details=self.baseline_ids | {"historical-detail"},
            )

    def test_candidate_event_without_detail_page_is_always_blocked(self):
        with self.assertRaisesRegex(ReleaseGuardError, "candidate detail pages missing: recent-a"):
            self.assess(
                self.baseline,
                candidate_details=self.baseline_ids - {"recent-a"},
                allow_shrink=True,
                issue="#46",
            )

    def test_shrink_override_requires_explicit_issue(self):
        candidate = payload(*self.protected)
        with self.assertRaisesRegex(ReleaseGuardError, "requires an explicit #Issue"):
            self.assess(candidate, allow_shrink=True)

        manifest = self.assess(candidate, allow_shrink=True, issue="#46")
        self.assertTrue(manifest["allow_shrink"])
        self.assertEqual(
            {violation["code"] for violation in manifest["overrides"]},
            {"event_count_decreased", "recent_events_missing", "detail_count_decreased"},
        )

    def test_same_source_sha_skips_duplicate_pages_write(self):
        manifest = self.assess(
            self.baseline,
            source_sha="same-sha",
            baseline_manifest={"source_sha": "same-sha"},
        )
        self.assertFalse(manifest["should_publish"])


class ReleaseWorkflowTests(unittest.TestCase):
    def test_all_pages_writes_route_through_guarded_deploy_workflow(self):
        update = (ROOT / ".github" / "workflows" / "update.yml").read_text()
        deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
        tts = (ROOT / ".github" / "workflows" / "tts.yml").read_text()

        self.assertNotIn("peaceiris/actions-gh-pages", update)
        self.assertNotIn("peaceiris/actions-gh-pages", tts)
        self.assertEqual(deploy.count("peaceiris/actions-gh-pages@v4"), 1)
        self.assertIn("cname: datahot.xiahongbin.com", deploy)
        self.assertIn('SITE_BASE_URL: "https://datahot.xiahongbin.com"', deploy)
        self.assertIn('SITE_BASE_URL: "https://datahot.xiahongbin.com"', update)
        self.assertIn("group: datahot-update", update)
        self.assertIn("group: datahot-publish", deploy)
        self.assertIn("uses: ./.github/workflows/deploy.yml", update)
        self.assertIn("uses: ./.github/workflows/deploy.yml", tts)
        self.assertIn("python3 pipeline/release_guard.py", deploy)
        self.assertIn("保存本轮主线数据基线", update)
        self.assertIn("主线数据回写前防缩水", update)
        self.assertIn("site/data/release.json", deploy)
        self.assertIn("allow_shrink:", deploy)
        self.assertIn("release_issue:", deploy)


if __name__ == "__main__":
    unittest.main()
