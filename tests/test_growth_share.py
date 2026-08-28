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

    def test_post_is_bounded_and_has_utf8_link_facet(self):
        post = growth_share.build_post(self.event(title="数据" * 80))
        self.assertLessEqual(len(post["text"]), 300)
        encoded = post["text"].encode("utf-8")
        index = post["facets"][0]["index"]
        self.assertEqual(encoded[index["byteStart"]:index["byteEnd"]].decode("utf-8"), post["url"])
        self.assertNotIn("example.com", post["text"])

    def test_disabled_mode_never_calls_the_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(json.dumps({"top": ["aaaaaaaaaaaa"], "events": [self.event()]}), encoding="utf-8")
            with patch.object(growth_share, "publish") as publish, patch.dict("os.environ", {}, clear=True):
                self.assertEqual(growth_share.main(["--data", str(path)]), 0)
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
            calls = []
            with patch.object(growth_share, "wait_until_live", side_effect=lambda _url: calls.append("live")), \
                    patch.object(growth_share, "publish", side_effect=lambda *_args, **_kwargs: calls.append("publish") or {"status": "published"}), \
                    patch.dict("os.environ", env, clear=True):
                self.assertEqual(growth_share.main(["--data", str(path)]), 0)
            self.assertEqual(calls, ["live", "publish"])

    def test_daily_record_key_is_a_stable_tid(self):
        now = datetime(2026, 8, 28, 14, 30, tzinfo=growth_share.TZ)
        tid = growth_share.daily_tid(now)
        self.assertRegex(tid, r"^[234567abcdefghij][234567abcdefghijklmnopqrstuvwxyz]{12}$")
        self.assertEqual(tid, growth_share.daily_tid(now.replace(hour=23)))

    def test_missing_record_uses_official_xrpc_error_then_publishes(self):
        missing = HTTPError(
            "https://bsky.social/xrpc/com.atproto.repo.getRecord",
            400,
            "Bad Request",
            {},
            io.BytesIO(json.dumps({"error": "RecordNotFound"}).encode("utf-8")),
        )
        responses = [
            {"did": "did:plc:test", "accessJwt": "token"},
            missing,
            {"uri": "at://did:plc:test/app.bsky.feed.post/example"},
        ]
        with patch.object(growth_share, "_json_request", side_effect=responses) as request:
            result = growth_share.publish(
                growth_share.build_post(self.event()),
                handle="datahot.example",
                password="unit-test-only",
                now=datetime(2026, 8, 28, 14, 30, tzinfo=growth_share.TZ),
            )
        self.assertEqual(result["status"], "published")
        self.assertEqual(request.call_count, 3)
        self.assertIn("com.atproto.repo.putRecord", request.call_args_list[2].args[0])

    def test_unexpected_xrpc_400_is_not_treated_as_missing(self):
        invalid = HTTPError(
            "https://bsky.social/xrpc/com.atproto.repo.getRecord",
            400,
            "Bad Request",
            {},
            io.BytesIO(json.dumps({"error": "InvalidRequest"}).encode("utf-8")),
        )
        responses = [
            {"did": "did:plc:test", "accessJwt": "token"},
            invalid,
        ]
        with patch.object(growth_share, "_json_request", side_effect=responses):
            with self.assertRaises(HTTPError):
                growth_share.publish(
                    growth_share.build_post(self.event()),
                    handle="datahot.example",
                    password="unit-test-only",
                    now=datetime(2026, 8, 28, 14, 30, tzinfo=growth_share.TZ),
                )


if __name__ == "__main__":
    unittest.main()
