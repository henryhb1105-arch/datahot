import base64
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import x_growth_share as m

NOW = datetime(2026, 9, 5, 3, 0, tzinfo=timezone.utc)
DAY = "2026-09-05"
UID = "12345"
ITEM = {"slug": "metabase-metabot", "step": 3, "body": "SQL 怎么接手？DataHot 设计参考。",
        "reviewed_on": "2026-09-05", "valid_through": "2026-09-30", "source": "https://example.org/docs"}


def land(item):
    path = f'/cases/{item["slug"]}.html'
    return path, f'https://{m.HOST}{path}?utm_source=x&utm_content=text#step-{item["step"]}'


def make_post(text, date=DAY):
    url = text.split("\n\n")[-1]
    return {"id": "67890", "author_id": UID, "created_at": date + "T03:00:00Z",
            "text": text.replace(url, "https://t.co/test"),
            "entities": {"urls": [{"url": "https://t.co/test", "expanded_url": url}]}}


class FakeLedger:
    def __init__(self):
        self.state = {"version": 1, "handle": m.HANDLE, "account_id": UID, "days": {}}
        self.revision = 0
        self.saves = 0
        self.fail_at = None

    def load(self):
        return copy.deepcopy(self.state), str(self.revision)

    def save(self, state, sha):
        self.saves += 1
        if self.saves == self.fail_at or sha != str(self.revision):
            raise m.HttpFailure(409)
        self.state = copy.deepcopy(state)
        self.revision += 1
        return str(self.revision)


class FakeX:
    def __init__(self, ledger):
        self.ledger = ledger
        self.post_writes = 0
        self.reads = 0
        self.posts = []
        self.fail_create = False
        self.fail_readback = False
        self.user_id = UID

    def identity(self):
        self.reads += 1
        return {"id": self.user_id, "username": m.HANDLE}

    def timeline(self, user_id, day):
        self.reads += 1
        return self.posts

    def create(self, text):
        assert self.ledger.state["days"][DAY]["status"] == "reserved"
        self.post_writes += 1
        if self.fail_create:
            raise m.SafeStop("network_or_response_failure")
        self.posts = [make_post(text)]
        return "67890"

    def get_post(self, post_id):
        self.reads += 1
        if self.fail_readback:
            raise m.SafeStop("network_or_response_failure")
        return self.posts[0]


class XPublisherTests(unittest.TestCase):
    def setUp(self):
        self.ledger = FakeLedger()
        self.x = FakeX(self.ledger)

    def run_publish(self, **kwargs):
        return m.publish(self.x, self.ledger, [ITEM], now=lambda: NOW, check_landing=land, **kwargs)

    def test_success_has_durable_intent_and_verified_post(self):
        result = self.run_publish()
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["post_id"], "67890")
        self.assertEqual(self.x.post_writes, 1)
        self.assertEqual(self.ledger.saves, 3)
        self.assertIn("utm_source=x&utm_content=text", result["url"])

    def test_duplicate_does_not_call_x(self):
        self.run_publish()
        reads = self.x.reads
        result = self.run_publish()
        self.assertEqual(result["status"], "already_published")
        self.assertEqual(self.x.reads, reads)
        self.assertEqual(self.x.post_writes, 1)

    def test_compare_and_swap_failure_prevents_post(self):
        self.ledger.fail_at = 1
        with self.assertRaises(m.HttpFailure):
            self.run_publish()
        self.assertEqual(self.x.post_writes, 0)

    def test_unknown_response_never_retries_post(self):
        self.x.fail_create = True
        with self.assertRaises(m.SafeStop):
            self.run_publish()
        self.x.fail_create = False
        with self.assertRaisesRegex(m.SafeStop, "no_retry"):
            self.run_publish()
        self.assertEqual(self.x.post_writes, 1)
        self.assertEqual(self.ledger.state["days"][DAY]["status"], "reserved")

    def test_unknown_response_can_reconcile_without_post(self):
        self.x.fail_create = True
        with self.assertRaises(m.SafeStop):
            self.run_publish()
        self.x.posts = [make_post(self.ledger.state["days"][DAY]["text"])]
        self.assertEqual(self.run_publish()["status"], "reconciled")
        self.assertEqual(self.x.post_writes, 1)

    def test_result_save_failure_keeps_reservation(self):
        self.ledger.fail_at = 2
        with self.assertRaises(m.HttpFailure):
            self.run_publish()
        self.assertEqual(self.ledger.state["days"][DAY]["status"], "reserved")
        self.assertEqual(self.run_publish()["status"], "reconciled")
        self.assertEqual(self.x.post_writes, 1)

    def test_readback_failure_keeps_post_id_and_does_not_resend(self):
        self.x.fail_readback = True
        with self.assertRaises(m.SafeStop):
            self.run_publish()
        self.assertEqual(self.ledger.state["days"][DAY]["post_id"], "67890")
        self.x.fail_readback = False
        self.assertEqual(self.run_publish()["status"], "reconciled")
        self.assertEqual(self.x.post_writes, 1)

    def test_mismatched_account_fails_before_post_or_ledger_write(self):
        self.x.user_id = "999"
        with self.assertRaisesRegex(m.SafeStop, "account_mismatch"):
            self.run_publish()
        self.assertEqual((self.x.post_writes, self.ledger.saves), (0, 0))

    def test_manually_published_datahot_link_blocks_daily_slot(self):
        self.x.posts = [make_post("Manual post\n\n" + land(ITEM)[1])]
        result = self.run_publish()
        self.assertEqual(result["status"], "already_published")
        self.assertEqual(self.x.post_writes, 0)

    def test_cross_midnight_never_posts_for_yesterday(self):
        times = iter([datetime(2026, 9, 5, 15, 59, 59, tzinfo=timezone.utc),
                      datetime(2026, 9, 5, 16, 0, 1, tzinfo=timezone.utc)])
        result = m.publish(self.x, self.ledger, [ITEM], now=lambda: next(times), check_landing=land)
        self.assertEqual(result["status"], "crossed_midnight_no_post")
        self.assertEqual(self.x.post_writes, 0)

    def test_used_case_is_not_recycled(self):
        self.run_publish()
        result = m.publish(self.x, self.ledger, [ITEM],
                           now=lambda: datetime(2026, 9, 6, 3, tzinfo=timezone.utc), check_landing=land)
        self.assertEqual(result["status"], "no_fresh_candidate")
        self.assertEqual(self.x.post_writes, 1)

    def test_expired_copy_is_not_published(self):
        result = m.publish(self.x, self.ledger, [ITEM],
                           now=lambda: datetime(2026, 10, 1, 3, tzinfo=timezone.utc), check_landing=land)
        self.assertEqual(result["status"], "no_fresh_candidate")
        self.assertEqual(self.x.reads, 0)

    def test_bad_landing_prevents_reservation(self):
        def fail(item):
            raise m.SafeStop("landing_not_ready")
        with self.assertRaises(m.SafeStop):
            m.publish(self.x, self.ledger, [ITEM], now=lambda: NOW, check_landing=fail)
        self.assertEqual(self.ledger.saves, 0)

    def test_readback_requires_author_date_and_exact_expanded_copy(self):
        record = {"account_id": UID, "date": DAY, "text": "A\n\n" + land(ITEM)[1]}
        post = make_post(record["text"])
        self.assertTrue(m.matches(post, record))
        for key, value in [("author_id", "999"), ("created_at", "2026-09-04T00:00:00Z"), ("text", "wrong")]:
            changed = dict(post, **{key: value})
            self.assertFalse(m.matches(changed, record))

    def test_oauth_known_signature_vector(self):
        header = m.oauth_header("GET", "http://photos.example.net/photos?file=vacation.jpg&size=original",
                                ("dpf43f3p2l4k3l03", "kd94hf93k423kf44", "nnch734d00sl2jdk", "pfkkdhi9sl3r4s00"),
                                nonce="kllo9940pd9333jh", timestamp=1191242096)
        self.assertIn('oauth_signature="tR3%2BTy81lMeYAr%2FFid0kMTYa%2FWM%3D"', header)

    def test_x_user_is_constrained(self):
        for user in [{"id": UID, "username": "someone_else"},
                     {"id": UID, "username": m.HANDLE, "protected": True}]:
            x = m.XClient(("a", "b", "c", "d"), lambda *a: {"data": user})
            with self.assertRaises(m.SafeStop):
                x.identity()

    def test_incomplete_timeline_stops_without_paging_cost(self):
        x = m.XClient(("a", "b", "c", "d"), lambda *a: {"meta": {"next_token": "next"}})
        with self.assertRaisesRegex(m.SafeStop, "timeline_incomplete"):
            x.timeline(UID, DAY)

    def test_queue_real_cases_and_length(self):
        items = json.loads((m.ROOT / "x_growth_queue.json").read_text())
        studies = json.loads((m.ROOT / "design_studies.json").read_text())["studies"]
        self.assertEqual(len(m.validate_queue(items, studies)), 5)

    def test_queue_rejects_external_urls_mentions_and_missing_old_version(self):
        studies = [{"slug": ITEM["slug"], "steps": [1, 2, 3], "sources": [{"url": ITEM["source"]}]}]
        for change in [{"body": "DataHot https://evil.example"}, {"body": "DataHot @someone"},
                       {"historical": True}, {"step": 99}, {"source": "https://other.example"},
                       {"body": "DataHot" + "字" * 150}]:
            with self.assertRaises(m.SafeStop):
                m.validate_queue([{**ITEM, **change}], studies)

    def test_ledger_missing_does_not_auto_initialize(self):
        def missing(*args, **kwargs):
            raise m.HttpFailure(404)
        ledger = m.Ledger("fake", missing)
        with self.assertRaises(m.HttpFailure):
            m.publish(self.x, ledger, [ITEM], now=lambda: NOW, check_landing=land)
        self.assertEqual(self.x.reads, 0)

    def test_ledger_invalid_rejected(self):
        invalid = {"version": 1, "handle": "other", "account_id": UID, "days": {}}
        payload = {"sha": "abc", "content": base64.b64encode(json.dumps(invalid).encode()).decode()}
        with self.assertRaises(m.SafeStop):
            m.Ledger("fake", lambda *a: payload).load()

    def test_schedule_window_and_timezone(self):
        self.assertEqual(m.day_of(datetime(2026, 9, 5, 16, tzinfo=timezone.utc)), "2026-09-06")
        self.assertTrue(m.scheduled_allowed(datetime(2026, 9, 5, 10, 7, tzinfo=timezone.utc)))
        self.assertFalse(m.scheduled_allowed(datetime(2026, 9, 5, 11, 37, tzinfo=timezone.utc)))
        self.assertFalse(m.scheduled_allowed(NOW))

    def test_cli_blocks_local_and_untrusted_refs(self):
        with patch.dict(m.os.environ, {}, clear=True), patch.object(sys, "argv", ["x_growth_share.py"]):
            with self.assertRaisesRegex(m.SafeStop, "trusted_main"):
                m.main()

    def test_no_redirects_for_credential_bearing_requests(self):
        self.assertIsNone(m.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))


if __name__ == "__main__":
    unittest.main()
