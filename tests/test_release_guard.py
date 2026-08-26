import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from release_guard import (  # noqa: E402
    PROTECTED_EVENT_IDS,
    ReleaseGuardError,
    assess_release,
    quarantine_new_stored_chrome,
)
from quarantine_content import main as quarantine_main  # noqa: E402


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
            {"structured": 1, "renderable": 1, "suspect": 0, "stored_chrome": 0},
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

    def test_persisted_article_tail_components_are_blocked_before_publish(self):
        polluted = with_article(event("recent-b"))
        polluted["content_blocks"].extend([
            {
                "type": "paragraph",
                "children": [{"type": "text", "text": "下一篇", "marks": []}],
            },
            {
                "type": "paragraph",
                "children": [{"type": "text", "text": "相邻文章标题", "marks": []}],
            },
        ])
        candidate = payload(*self.protected, self.recent, polluted)

        with self.assertRaisesRegex(ReleaseGuardError, "still contain page chrome"):
            self.assess(candidate)

    def test_new_polluted_article_is_quarantined_without_removing_baseline(self):
        polluted = with_article(event("recent-b"))
        polluted["zh_title"] = "污染文章"
        polluted["content_blocks"].extend([
            {"type": "paragraph", "children": [{"type": "text", "text": "下一篇", "marks": []}]},
            {"type": "paragraph", "children": [{"type": "text", "text": "相邻文章标题", "marks": []}]},
        ])
        candidate = payload(*self.protected, self.recent, polluted)

        cleaned, quarantined = quarantine_new_stored_chrome(self.baseline, candidate)

        self.assertEqual(
            {item["event_id"] for item in cleaned["events"]},
            self.baseline_ids,
        )
        self.assertEqual(quarantined, [{
            "event_id": "recent-b",
            "title": "污染文章",
            "reason": "stored_article_chrome",
            "disposition": "removed_new_event",
        }])

    def test_multiple_new_polluted_articles_are_quarantined_together(self):
        polluted_events = []
        for event_id in ("recent-b", "recent-c"):
            item = with_article(event(event_id))
            item["content_blocks"].extend([
                {"type": "paragraph", "children": [{"type": "text", "text": "下一篇", "marks": []}]},
                {"type": "paragraph", "children": [{"type": "text", "text": "相邻文章标题", "marks": []}]},
            ])
            polluted_events.append(item)

        cleaned, quarantined = quarantine_new_stored_chrome(
            self.baseline, payload(*self.protected, self.recent, *polluted_events),
        )

        self.assertEqual({item["event_id"] for item in cleaned["events"]}, self.baseline_ids)
        self.assertEqual(
            {item["event_id"] for item in quarantined},
            {"recent-b", "recent-c"},
        )

    def test_existing_polluted_article_is_never_auto_quarantined(self):
        existing = with_article(event("recent-a"))
        existing["content_blocks"].extend([
            {"type": "paragraph", "children": [{"type": "text", "text": "下一篇", "marks": []}]},
            {"type": "paragraph", "children": [{"type": "text", "text": "相邻文章标题", "marks": []}]},
        ])
        baseline = payload(*self.protected, existing)
        candidate = payload(*self.protected, existing)

        with self.assertRaisesRegex(ReleaseGuardError, "cannot be quarantined"):
            quarantine_new_stored_chrome(baseline, candidate)

    def test_existing_clean_article_is_restored_when_backfill_adds_chrome(self):
        polluted = with_article(event("recent-a"))
        polluted["zh_title"] = "被回填污染的文章"
        polluted["content_blocks"].extend([
            {"type": "paragraph", "children": [{"type": "text", "text": "下一篇", "marks": []}]},
            {"type": "paragraph", "children": [{"type": "text", "text": "相邻文章标题", "marks": []}]},
        ])
        candidate = payload(*self.protected, polluted)

        cleaned, quarantined = quarantine_new_stored_chrome(self.baseline, candidate)

        restored = next(item for item in cleaned["events"] if item["event_id"] == "recent-a")
        baseline_event = next(
            item for item in self.baseline["events"] if item["event_id"] == "recent-a"
        )
        self.assertEqual(restored, baseline_event)
        self.assertEqual(quarantined[0]["disposition"], "restored_baseline")

    def test_clean_candidate_is_unchanged_by_quarantine(self):
        candidate = payload(*self.protected, self.recent, with_article(event("recent-b")))
        cleaned, quarantined = quarantine_new_stored_chrome(self.baseline, candidate)

        self.assertIs(cleaned, candidate)
        self.assertEqual(quarantined, [])

    def test_quarantine_cli_rewrites_candidate_and_emits_audit_report(self):
        polluted = with_article(event("recent-b"))
        polluted["content_blocks"].extend([
            {"type": "paragraph", "children": [{"type": "text", "text": "下一篇", "marks": []}]},
            {"type": "paragraph", "children": [{"type": "text", "text": "相邻文章标题", "marks": []}]},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_path = root / "baseline.json"
            candidate_path = root / "candidate.json"
            report_path = root / "report.json"
            baseline_path.write_text(json.dumps(self.baseline), encoding="utf-8")
            candidate_path.write_text(
                json.dumps(payload(*self.protected, self.recent, polluted)), encoding="utf-8"
            )

            result = quarantine_main([
                "--baseline", str(baseline_path),
                "--candidate", str(candidate_path),
                "--report", str(report_path),
            ])

            self.assertEqual(result, 0)
            cleaned = json.loads(candidate_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual({item["event_id"] for item in cleaned["events"]}, self.baseline_ids)
            self.assertEqual(report["candidate_event_count_before"], len(self.baseline_ids) + 1)
            self.assertEqual(report["candidate_event_count_after"], len(self.baseline_ids))
            self.assertEqual(report["quarantined"][0]["disposition"], "removed_new_event")

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

    def test_newer_published_time_is_used_when_first_seen_is_old(self):
        rolling = event("rolling-release", days_ago=30)
        rolling["published"] = (NOW - timedelta(days=1)).isoformat()
        baseline = payload(*self.protected, rolling)
        baseline_ids = {item["event_id"] for item in baseline["events"]}
        candidate = payload(*self.protected)

        with self.assertRaisesRegex(ReleaseGuardError, "recent event"):
            assess_release(
                baseline,
                candidate,
                baseline_ids,
                {item["event_id"] for item in candidate["events"]},
                source_sha="candidate-sha",
                run_id="12345",
                issue="automatic",
                baseline_manifest={"source_sha": "baseline-sha"},
                now=NOW,
            )

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
        self.assertIn("pipeline/quarantine_content.py", update)
        self.assertLess(
            update.index("pipeline/quarantine_content.py"),
            update.index("python3 pipeline/build_site.py"),
        )
        self.assertIn("主线数据回写前防缩水", update)
        self.assertIn("site/data/release.json", deploy)
        self.assertIn("allow_shrink:", deploy)
        self.assertIn("release_issue:", deploy)


if __name__ == "__main__":
    unittest.main()
