import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import growth_share  # noqa: E402


class GrowthShareTests(unittest.TestCase):
    def event(self, event_id="aaaaaaaaaaaa", title="一个值得读的数据产品案例"):
        return {
            "event_id": event_id,
            "zh_title": title,
            "reason": "它提供了可复用的方法和清晰证据，适合数据团队今天阅读。",
        }

    def test_selects_first_ranked_top_event(self):
        data = {"top": ["bbbbbbbbbbbb", "aaaaaaaaaaaa"], "events": [
            self.event("aaaaaaaaaaaa"), self.event("bbbbbbbbbbbb", "TOP 1"),
        ]}
        self.assertEqual(growth_share.select_highlight(data)["zh_title"], "TOP 1")

    def test_selects_distinct_ranked_events_by_position_and_exclusion(self):
        data = {"top": ["bbbbbbbbbbbb", "aaaaaaaaaaaa"], "events": [
            self.event("aaaaaaaaaaaa"),
            self.event("bbbbbbbbbbbb", "TOP 1"),
            self.event("cccccccccccc", "候补"),
        ]}
        self.assertEqual(growth_share.select_highlight(data, position=1)["event_id"], "aaaaaaaaaaaa")
        selected = growth_share.select_highlight(data, excluded_event_ids={"bbbbbbbbbbbb", "aaaaaaaaaaaa"})
        self.assertEqual(selected["event_id"], "cccccccccccc")

    def test_post_is_bounded_and_has_utf8_link_facet(self):
        post = growth_share.build_post(self.event(title="数据" * 80), slot=4)
        self.assertLessEqual(len(post["text"]), 300)
        encoded = post["text"].encode("utf-8")
        index = post["facets"][0]["index"]
        self.assertEqual(encoded[index["byteStart"]:index["byteEnd"]].decode("utf-8"), post["url"])
        self.assertNotIn("example.com", post["text"])
        self.assertIn("5/5", post["text"])

    def test_disabled_mode_never_calls_the_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(json.dumps({"top": ["aaaaaaaaaaaa"], "events": [self.event()]}), encoding="utf-8")
            with patch.object(growth_share, "publish") as publish, patch.dict("os.environ", {}, clear=True):
                self.assertEqual(growth_share.main(["--data", str(path), "--slot", "0"]), 0)
                publish.assert_not_called()

    def test_enabled_mode_verifies_live_page_before_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(json.dumps({"top": ["aaaaaaaaaaaa"], "events": [self.event()]}), encoding="utf-8")
            env = {
                "GROWTH_BSKY_ENABLED": "true",
                "BSKY_HANDLE": "datahot.example",
                "BSKY_APP_PASSWORD": "unit-test-only",
            }
            with patch.object(growth_share, "publish", return_value={"status": "published"}) as publish, \
                    patch.dict("os.environ", env, clear=True):
                self.assertEqual(growth_share.main(["--data", str(path), "--slot", "3"]), 0)
            publish.assert_called_once_with(
                {"top": ["aaaaaaaaaaaa"], "events": [self.event()]},
                handle="datahot.example",
                password="unit-test-only",
                slot=3,
            )

    def test_daily_record_key_is_a_stable_tid(self):
        now = datetime(2026, 8, 28, 14, 30, tzinfo=growth_share.TZ)
        tid = growth_share.daily_tid(now)
        self.assertRegex(tid, r"^[234567abcdefghij][234567abcdefghijklmnopqrstuvwxyz]{12}$")
        self.assertEqual(tid, growth_share.daily_tid(now.replace(hour=23)))
        tids = {growth_share.daily_slot_tid(now, slot) for slot in range(growth_share.DAILY_SLOTS)}
        self.assertEqual(len(tids), 5)
        self.assertEqual(growth_share.daily_slot_tid(now, 0), tid)

    def test_missing_record_uses_official_xrpc_error_then_publishes(self):
        missing = HTTPError(
            "https://bsky.social/xrpc/com.atproto.repo.getRecord",
            400,
            "Bad Request",
            {},
            io.BytesIO(json.dumps({"error": "RecordNotFound"}).encode("utf-8")),
        )
        with patch.object(growth_share, "_json_request", side_effect=[missing]) as request:
            result = growth_share._get_record(did="did:plc:test", token="token", rkey="example")
        self.assertIsNone(result)
        self.assertEqual(request.call_count, 1)

    def test_publish_excludes_articles_already_used_by_other_slots(self):
        data = {"top": ["aaaaaaaaaaaa", "bbbbbbbbbbbb"], "events": [
            self.event("aaaaaaaaaaaa"), self.event("bbbbbbbbbbbb", "第二条"),
        ]}
        previous = {
            "uri": "at://did:plc:test/app.bsky.feed.post/previous",
            "value": {"text": "已发 https://datahot.xiahongbin.com/e/aaaaaaaaaaaa.html"},
        }
        records = [None, previous, None, None, None]
        responses = [
            {"did": "did:plc:test", "accessJwt": "token"},
            {"uri": "at://did:plc:test/app.bsky.feed.post/example"},
        ]
        with patch.object(growth_share, "_get_record", side_effect=records), \
                patch.object(growth_share, "_json_request", side_effect=responses) as request, \
                patch.object(growth_share, "wait_until_live") as wait_until_live:
            result = growth_share.publish(
                data,
                handle="datahot.example",
                password="unit-test-only",
                slot=1,
                now=datetime(2026, 8, 28, 14, 30, tzinfo=growth_share.TZ),
            )
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["event_id"], "bbbbbbbbbbbb")
        self.assertEqual(request.call_count, 2)
        self.assertIn("com.atproto.repo.putRecord", request.call_args_list[1].args[0])
        wait_until_live.assert_called_once_with("https://datahot.xiahongbin.com/e/bbbbbbbbbbbb.html")

    def test_unexpected_xrpc_400_is_not_treated_as_missing(self):
        invalid = HTTPError(
            "https://bsky.social/xrpc/com.atproto.repo.getRecord",
            400,
            "Bad Request",
            {},
            io.BytesIO(json.dumps({"error": "InvalidRequest"}).encode("utf-8")),
        )
        with patch.object(growth_share, "_json_request", side_effect=[invalid]):
            with self.assertRaises(HTTPError):
                growth_share._get_record(did="did:plc:test", token="token", rkey="example")

    def test_growth_workflow_has_five_daily_slots_and_deploy_does_not_post(self):
        workflow = (ROOT / ".github" / "workflows" / "growth-share.yml").read_text(encoding="utf-8")
        deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        for cron in ("47 0 * * *", "47 3 * * *", "47 6 * * *", "47 9 * * *", "47 12 * * *"):
            self.assertIn(f'cron: "{cron}"', workflow)
        self.assertIn('python3 pipeline/growth_share.py --slot "$GROWTH_SLOT"', workflow)
        self.assertNotIn("pipeline/growth_share.py", deploy)


if __name__ == "__main__":
    unittest.main()
