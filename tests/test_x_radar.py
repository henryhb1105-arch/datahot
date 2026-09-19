import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from x_radar import collect, plan

NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
CONFIG = {"enabled":True, "accounts":["hex_tech"], "weekly_post_limit":200,
          "rolling_31_day_budget_usd":"0.25", "post_price_ceiling_usd":"0.005",
          "pricing_verified_at":"2026-09-19", "console_spending_limit_verified_at":"2026-09-19"}


class XRadarBoundaryTests(unittest.TestCase):
    def test_repository_default_never_makes_a_request(self):
        config = json.loads((ROOT / "pipeline/x_radar_config.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            result = collect(config, path, token="", now=NOW,
                             fetch=lambda *_:self.fail("default must stay offline"))
            self.assertEqual(result["status"], "disabled")
            self.assertFalse(path.exists())
            self.assertEqual(plan(config)["network_requests"], 0)

    def test_budget_is_reserved_before_request_and_survives_network_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            def fail_after_accept(params, token):
                state = json.loads(path.read_text())
                self.assertEqual(state["reservations"][0]["usd"], "0.250")
                self.assertEqual(params["max_results"], 50)
                self.assertNotIn("expansions", params)
                raise TimeoutError("simulated")
            result = collect(CONFIG, path, token="test", now=NOW, fetch=fail_after_accept)
            self.assertEqual(result["status"], "request_failed_no_retry")
            self.assertEqual(result["network_requests"], 1)
            again = collect(CONFIG, path, token="test", now=NOW+timedelta(hours=1), fetch=lambda *_:self.fail("no retry"))
            self.assertEqual(again["status"], "weekly_cache_hit")
            later = collect(CONFIG, path, token="test", now=NOW+timedelta(days=7), fetch=lambda *_:self.fail("no overspend"))
            self.assertEqual(later["status"], "budget_exhausted")

    def test_deduplication_and_budget_truncation_do_not_autopublish(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            rows = [{"id":str(i),"text":"Agent update","entities":{"urls":[{"expanded_url":url}]}}
                    for i,url in [(1,"https://hex.tech/blog/agent?utm_source=x"),(2,"https://hex.tech/blog/agent"),(1,"https://hex.tech/new")]]
            result = collect(CONFIG, path, token="test", now=NOW,
                             fetch=lambda *_:{"data":rows,"meta":{"next_token":"next"}})
            self.assertEqual(result["added"], 1)
            self.assertFalse(result["coverage_complete"])
            self.assertEqual(result["auto_published"], 0)
            self.assertEqual(result["status"], "stopped_at_budget")
            self.assertEqual(json.loads(path.read_text())["candidates"]["1"]["status"], "needs_editorial_review")

    def test_corrupt_ledger_and_expired_pricing_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("broken")
            with self.assertRaises(ValueError):
                collect(CONFIG, path, token="test", now=NOW, fetch=lambda *_:self.fail("corrupt ledger"))
            expired = copy.deepcopy(CONFIG)
            expired["pricing_verified_at"] = "2026-08-01"
            with self.assertRaises(ValueError):
                collect(expired, path, token="test", now=NOW, fetch=lambda *_:self.fail("stale price"))

    def test_query_cannot_expand_outside_allowlist(self):
        config = copy.deepcopy(CONFIG)
        config["accounts"] = ["hex_tech OR from:other"]
        with self.assertRaises(ValueError):
            plan(config)
