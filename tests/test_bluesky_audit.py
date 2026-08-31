import io
import json
import os
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import bluesky_audit  # noqa: E402


class BlueskyAuditTests(unittest.TestCase):
    def post(self, did="did:plc:other"):
        return {
            "uri": f"at://{did}/app.bsky.feed.post/example",
            "author": {"did": did},
        }

    def test_audit_uses_only_session_and_query_endpoints(self):
        own_did = "did:plc:datahot"

        def response(url, *, payload=None, token=""):
            if url.endswith("com.atproto.server.createSession"):
                self.assertEqual(payload["identifier"], "datahot.example")
                self.assertEqual(payload["password"], "secret")
                return {"did": own_did, "accessJwt": "access-token"}
            self.assertIsNone(payload)
            self.assertEqual(token, "access-token")
            self.assertNotIn("putRecord", url)
            self.assertNotIn("uploadBlob", url)
            if "searchPosts" in url:
                posts = [self.post(), self.post(own_did)] if "DataHot" in url else [self.post()]
                return {"posts": posts, "hitsTotal": len(posts)}
            if "getFeed" in url:
                return {"feed": [{"post": self.post()}, {"post": self.post(own_did)}]}
            self.fail(f"unexpected URL: {url}")

        with patch.object(bluesky_audit.growth_share, "_json_request", side_effect=response) as request:
            report = bluesky_audit.audit_distribution(
                handle="DataHot.Example", password="secret"
            )

        self.assertEqual(request.call_count, 7)
        self.assertTrue(report["read_only"])
        self.assertTrue(report["search_indexed"])
        self.assertFalse(report["topic_search_presence"])
        self.assertEqual(report["search"]["brand"]["own_ranks"], [2])
        self.assertEqual(report["discover"]["own_ranks"], [2])
        self.assertNotIn("access-token", json.dumps(report))
        self.assertNotIn("secret", json.dumps(report))

    def test_one_failed_query_does_not_hide_other_evidence(self):
        error = HTTPError("https://example.test", 503, "unavailable", {}, io.BytesIO(b""))
        responses = [
            {"did": "did:plc:datahot", "accessJwt": "token"},
            error,
            {"posts": [self.post("did:plc:datahot")]},
            {"posts": []},
            {"posts": []},
            {"posts": []},
            {"feed": []},
        ]
        with patch.object(bluesky_audit.growth_share, "_json_request", side_effect=responses):
            report = bluesky_audit.audit_distribution(handle="datahot.example", password="secret")

        self.assertEqual(report["status"], "audited")
        self.assertFalse(report["search"]["brand"]["ok"])
        self.assertEqual(report["search"]["brand"]["error"], "HTTPError")
        self.assertTrue(report["search_indexed"])

    def test_main_requires_credentials_before_network(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(bluesky_audit, "audit_distribution") as audit:
            with self.assertRaisesRegex(SystemExit, "BSKY_HANDLE"):
                bluesky_audit.main()
        audit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
