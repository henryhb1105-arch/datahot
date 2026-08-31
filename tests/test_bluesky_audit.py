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
    def post(self, did="did:plc:other", *, embed=None, likes=0, reposts=0, replies=0, quotes=0):
        post = {
            "uri": f"at://{did}/app.bsky.feed.post/example",
            "author": {"did": did},
            "likeCount": likes,
            "repostCount": reposts,
            "replyCount": replies,
            "quoteCount": quotes,
        }
        if embed is not None:
            post["embed"] = embed
        return post

    def test_format_benchmark_separates_visual_treatments_and_engagement(self):
        posts = [
            self.post(embed={"$type": "app.bsky.embed.images#view"}, likes=4, reposts=2),
            self.post(embed={"$type": "app.bsky.embed.images#view"}),
            self.post(embed={
                "$type": "app.bsky.embed.external#view",
                "external": {"thumb": "https://cdn.example/image.jpg"},
            }, likes=3),
            self.post(embed={
                "$type": "app.bsky.embed.external#view",
                "external": {},
            }),
            self.post(),
        ]

        benchmark = bluesky_audit._format_benchmark(posts)

        self.assertEqual(benchmark["sample_size"], 5)
        self.assertEqual(benchmark["visual_share"], 0.6)
        self.assertEqual(benchmark["formats"]["images"], {
            "posts": 2,
            "engagement_total": 6,
            "engagement_median": 3.0,
            "zero_engagement_rate": 0.5,
        })
        self.assertEqual(benchmark["formats"]["external_card"]["engagement_total"], 3)
        self.assertEqual(benchmark["formats"]["external_link"]["posts"], 1)
        self.assertEqual(benchmark["formats"]["text_only"]["posts"], 1)

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
                posts = [self.post(), self.post(own_did)] if "DataHot" in url else [
                    self.post(embed={"$type": "app.bsky.embed.images#view"}, likes=2)
                ]
                return {"posts": posts, "hitsTotal": len(posts)}
            if "getFeed" in url:
                return {"feed": [{"post": self.post()}, {"post": self.post(own_did)}]}
            self.fail(f"unexpected URL: {url}")

        with patch.object(bluesky_audit.growth_share, "_json_request", side_effect=response) as request:
            report = bluesky_audit.audit_distribution(
                handle="DataHot.Example", password="secret"
            )

        self.assertEqual(request.call_count, 10)
        self.assertTrue(report["read_only"])
        self.assertTrue(report["search_indexed"])
        self.assertFalse(report["topic_search_presence"])
        self.assertEqual(report["search"]["brand"]["own_ranks"], [2])
        self.assertEqual(report["topic_top"]["ai_agents"]["format_benchmark"]["visual_share"], 1.0)
        self.assertEqual(report["discover"]["own_ranks"], [2])
        self.assertNotIn("access-token", json.dumps(report))
        self.assertNotIn("secret", json.dumps(report))

    def test_one_failed_query_does_not_hide_other_evidence(self):
        error = HTTPError("https://example.test", 503, "unavailable", {}, io.BytesIO(b""))
        responses = (
            [{"did": "did:plc:datahot", "accessJwt": "token"}, error]
            + [{"posts": [self.post("did:plc:datahot")]}]
            + [{"posts": []}] * 6
            + [{"feed": []}]
        )
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
