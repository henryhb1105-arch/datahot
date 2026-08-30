import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import indexnow  # noqa: E402


SITE_BASE = "https://datahot.xiahongbin.com"


class FakeResponse:
    def __init__(self, status=200, body=b""):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class IndexNowTests(unittest.TestCase):
    def event(self, event_id, *, first_seen="2026-08-30T09:00:00+08:00", title="标题"):
        return {"event_id": event_id, "first_seen": first_seen, "zh_title": title}

    def test_key_writer_emits_exact_root_ownership_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = indexnow.write_key_file(directory)
            self.assertEqual(target.name, f"{indexnow.INDEXNOW_KEY}.txt")
            self.assertEqual(target.read_text(encoding="utf-8"), indexnow.INDEXNOW_KEY)
        for invalid in ("short", "contains_underscore", "x" * 129):
            with self.assertRaises(ValueError):
                indexnow.validate_key(invalid)

    def test_only_changed_details_and_affected_public_pages_are_submitted(self):
        baseline = {
            "top": ["aaaaaaaaaaaa"],
            "sources": [{"name": "A"}],
            "events": [
                self.event("aaaaaaaaaaaa"),
                self.event("bbbbbbbbbbbb"),
            ],
        }
        candidate = {
            "top": ["cccccccccccc"],
            "sources": [{"name": "B"}],
            "events": [
                self.event("aaaaaaaaaaaa", title="更新标题"),
                self.event("cccccccccccc"),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            topics = Path(directory) / "topics"
            topics.mkdir()
            (topics / "data-agent.html").write_text("ok", encoding="utf-8")
            urls = indexnow.changed_public_urls(
                baseline, candidate, site_root=directory, site_base=SITE_BASE,
            )
        for path in (
            "", "hot.html", "topics.html", "sources.html", "topics/data-agent.html",
            "e/aaaaaaaaaaaa.html", "e/bbbbbbbbbbbb.html", "e/cccccccccccc.html",
        ):
            expected = f"{SITE_BASE}/{path}" if path else f"{SITE_BASE}/"
            self.assertIn(expected, urls)
        self.assertFalse(any("favorites" in url or "for-me" in url for url in urls))

    def test_unchanged_release_has_no_urls_after_initial_bootstrap(self):
        payload = {"top": ["aaaaaaaaaaaa"], "sources": [], "events": [self.event("aaaaaaaaaaaa")]}
        self.assertEqual(
            indexnow.changed_public_urls(payload, payload, site_root=ROOT / "site"),
            (),
        )

    def test_initial_bootstrap_is_limited_to_recently_discovered_events(self):
        now = datetime(2026, 8, 30, 4, 0, tzinfo=timezone.utc)
        recent = (now - timedelta(hours=2)).isoformat()
        old = (now - timedelta(days=4)).isoformat()
        candidate = {"top": [], "sources": [], "events": [
            self.event("aaaaaaaaaaaa", first_seen=recent),
            self.event("bbbbbbbbbbbb", first_seen=old),
        ]}
        urls = indexnow.changed_public_urls(
            candidate,
            candidate,
            site_root=ROOT / "site",
            bootstrap=True,
            now=now,
        )
        self.assertIn(f"{SITE_BASE}/e/aaaaaaaaaaaa.html", urls)
        self.assertNotIn(f"{SITE_BASE}/e/bbbbbbbbbbbb.html", urls)

    def test_foreign_or_parameterized_urls_are_rejected(self):
        for url in (
            "https://example.com/e/a.html",
            f"{SITE_BASE}/e/a.html?utm_source=test",
            f"{SITE_BASE}/e/a.html#fragment",
        ):
            with self.assertRaises(ValueError):
                indexnow.validate_urls([url], site_base=SITE_BASE)

    def test_submit_uses_protocol_payload_and_accepts_pending_key_validation(self):
        captured = {}

        def opener(request, timeout=0):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(202)

        result = indexnow.submit_urls(
            [f"{SITE_BASE}/e/aaaaaaaaaaaa.html"], opener=opener,
        )
        self.assertEqual(result["status"], "accepted_pending_key_validation")
        self.assertEqual(result["http_status"], 202)
        request = captured["request"]
        self.assertEqual(request.full_url, indexnow.INDEXNOW_ENDPOINT)
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["host"], "datahot.xiahongbin.com")
        self.assertEqual(payload["key"], indexnow.INDEXNOW_KEY)
        self.assertEqual(payload["urlList"], [f"{SITE_BASE}/e/aaaaaaaaaaaa.html"])

    def test_live_wait_requires_matching_release_and_exact_key(self):
        sha = "a" * 40
        responses = iter([
            FakeResponse(200, json.dumps({"source_sha": sha}).encode("utf-8")),
            FakeResponse(200, indexnow.INDEXNOW_KEY.encode("utf-8")),
        ])
        indexnow.wait_until_release_live(
            sha,
            attempts=1,
            delay=0,
            opener=lambda *_args, **_kwargs: next(responses),
        )

    def test_cli_dry_run_never_waits_or_submits(self):
        baseline = {"top": [], "sources": [], "events": []}
        candidate = {"top": ["aaaaaaaaaaaa"], "sources": [], "events": [self.event("aaaaaaaaaaaa")]}
        with tempfile.TemporaryDirectory() as directory:
            baseline_path = Path(directory) / "baseline.json"
            candidate_path = Path(directory) / "candidate.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            with patch.object(indexnow, "wait_until_release_live") as wait, \
                    patch.object(indexnow, "submit_urls") as submit, \
                    patch("sys.stdout", new_callable=io.StringIO):
                result = indexnow.main([
                    "--baseline-latest", str(baseline_path),
                    "--candidate-latest", str(candidate_path),
                    "--site-root", directory,
                    "--dry-run",
                ])
        self.assertEqual(result, 0)
        wait.assert_not_called()
        submit.assert_not_called()

    def test_deploy_workflow_submits_only_after_pages_with_failure_isolation(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        publish_position = workflow.index("name: 发布到 GitHub Pages")
        indexnow_position = workflow.index("name: 通知 IndexNow 本轮变化 URL")
        self.assertGreater(indexnow_position, publish_position)
        indexnow_step = workflow[indexnow_position:]
        self.assertIn("continue-on-error: true", indexnow_step)
        self.assertIn("python3 pipeline/indexnow.py", indexnow_step)


if __name__ == "__main__":
    unittest.main()
