import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations" / "openclaw"))

import datahot_push  # noqa: E402


NOW = datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc)


def item(index, *, importance=80, recommended=True, discovered=None, reason=None):
    event_id = f"{index:012x}"[-12:]
    return {
        "event_id": event_id,
        "title": f"重要资讯 {index}",
        "summary": "这是摘要。",
        "why_it_matters": reason or "这会影响数据产品的落地。",
        "importance": importance,
        "discovered_at": (discovered or NOW).isoformat(),
        "push": {"recommended": recommended, "reason": "importance_80" if recommended else None},
        "links": {"detail": f"https://datahot.xiahongbin.com/e/{event_id}.html"},
    }


def payload(events):
    return {
        "schema_version": 1,
        "generated_at": NOW.isoformat(),
        "events": events,
    }


class DataHotPushTests(unittest.TestCase):
    def run_process(self, feed, state, *, now=NOW, sender=None, **limits):
        snapshots = []
        sender = sender or (lambda _message: (True, ""))
        result = datahot_push.process_payload(
            feed, state, now=now, etag='"etag"', sender=sender,
            persist=lambda value: snapshots.append(copy.deepcopy(value)),
            **limits,
        )
        return result, snapshots

    def test_first_run_only_builds_a_baseline(self):
        state = datahot_push.new_state()
        calls = []
        result, snapshots = self.run_process(
            payload([item(1)]), state,
            sender=lambda message: calls.append(message) or (True, ""),
        )
        self.assertTrue(result["baseline"])
        self.assertEqual(calls, [])
        self.assertEqual(state["events"][item(1)["event_id"]]["status"], "seen")
        self.assertEqual(snapshots[-1]["etag"], '"etag"')

    def test_new_important_event_sends_one_item_with_one_raw_detail_url(self):
        state = datahot_push.new_state()
        self.run_process(payload([item(1)]), state)
        messages = []
        new_item = item(
            2,
            reason="详情参考 https://untrusted.example/path 但只应保留 DataHot 链接。",
        )
        result, _ = self.run_process(
            payload([item(1), new_item]), state, now=NOW + timedelta(minutes=15),
            sender=lambda message: messages.append(message) or (True, ""),
        )
        self.assertEqual(result["sent"], [new_item["event_id"]])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].count("https://"), 1)
        self.assertTrue(messages[0].endswith(new_item["links"]["detail"]))
        self.assertNotIn("[", messages[0])

        again = []
        repeat, _ = self.run_process(
            payload([item(1), new_item]), state, now=NOW + timedelta(minutes=30),
            sender=lambda message: again.append(message) or (True, ""),
        )
        self.assertEqual(repeat["sent"], [])
        self.assertEqual(again, [])

    def test_existing_event_is_sent_when_it_crosses_the_server_threshold(self):
        state = datahot_push.new_state()
        low = item(1, importance=79, recommended=False)
        self.run_process(payload([low]), state)
        high = item(1, importance=80, recommended=True)
        messages = []
        result, _ = self.run_process(
            payload([high]), state, now=NOW + timedelta(minutes=15),
            sender=lambda message: messages.append(message) or (True, ""),
        )
        self.assertEqual(result["sent"], [high["event_id"]])
        self.assertEqual(len(messages), 1)

    def test_caps_defer_pending_events_without_losing_them(self):
        state = datahot_push.new_state()
        self.run_process(payload([]), state)
        events = [item(index) for index in range(1, 5)]
        first, _ = self.run_process(
            payload(events), state, now=NOW + timedelta(minutes=15),
            max_per_run=2, max_per_day=3,
        )
        self.assertEqual(len(first["sent"]), 2)
        self.assertEqual(first["pending"], 2)
        second, _ = self.run_process(
            payload(events), state, now=NOW + timedelta(minutes=30),
            max_per_run=2, max_per_day=3,
        )
        self.assertEqual(len(second["sent"]), 1)
        self.assertEqual(second["pending"], 1)

    def test_failed_or_ambiguous_attempt_is_recorded_before_send_and_not_retried(self):
        state = datahot_push.new_state()
        self.run_process(payload([]), state)
        event = item(1)
        observed_statuses = []

        def fail(_message):
            observed_statuses.append(state["events"][event["event_id"]]["status"])
            return False, "ambiguous plugin output"

        result, snapshots = self.run_process(
            payload([event]), state, now=NOW + timedelta(minutes=15), sender=fail,
        )
        self.assertEqual(observed_statuses, ["attempted"])
        self.assertEqual(result["failed"], [event["event_id"]])
        self.assertEqual(state["events"][event["event_id"]]["status"], "failed")
        self.assertTrue(any(
            snapshot["events"][event["event_id"]]["status"] == "attempted"
            for snapshot in snapshots
        ))

        calls = []
        repeat, _ = self.run_process(
            payload([event]), state, now=NOW + timedelta(minutes=30),
            sender=lambda message: calls.append(message) or (True, ""),
        )
        self.assertEqual(repeat["sent"], [])
        self.assertEqual(calls, [])

    def test_state_is_atomic_private_and_openclaw_uses_argv_not_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "state.json"
            state = datahot_push.new_state()
            datahot_push.save_state(path, state)
            self.assertEqual(datahot_push.load_state(path), state)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        completed = type("Completed", (), {"returncode": 0, "stdout": "not-json noise", "stderr": ""})()
        config = {
            "openclaw_command": "/safe/oc",
            "channel": "openclaw-weixin",
            "target": "private-target",
            "account": "private-account",
        }
        with patch.object(datahot_push.subprocess, "run", return_value=completed) as run:
            self.assertEqual(datahot_push.openclaw_sender(config)("hello"), (True, ""))
        argv = run.call_args.args[0]
        self.assertEqual(argv[0:3], ["/safe/oc", "message", "send"])
        self.assertIn("hello", argv)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_fetch_uses_etag_and_treats_304_as_no_change(self):
        raw = json.dumps(payload([item(1)])).encode("utf-8")

        class Response:
            headers = {"ETag": '"new-etag"'}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return raw

        with patch.object(datahot_push, "urlopen", return_value=Response()) as opened:
            fetched, etag, unchanged = datahot_push.fetch_feed(
                datahot_push.DEFAULT_FEED_URL, etag='"old-etag"',
            )
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header("If-none-match"), '"old-etag"')
        self.assertEqual(fetched["events"][0]["event_id"], item(1)["event_id"])
        self.assertEqual(etag, '"new-etag"')
        self.assertFalse(unchanged)

        not_modified = HTTPError(
            datahot_push.DEFAULT_FEED_URL, 304, "Not Modified", {}, None,
        )
        with patch.object(datahot_push, "urlopen", side_effect=not_modified):
            fetched, etag, unchanged = datahot_push.fetch_feed(
                datahot_push.DEFAULT_FEED_URL, etag='"old-etag"',
            )
        self.assertIsNone(fetched)
        self.assertEqual(etag, '"old-etag"')
        self.assertTrue(unchanged)


if __name__ == "__main__":
    unittest.main()
