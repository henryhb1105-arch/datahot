import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from candidate_cache import CandidateCache, candidate_content_hash  # noqa: E402
import run_update  # noqa: E402


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 11, 11, 0, tzinfo=TZ)


def context(url="https://example.com/post", content_hash="hash-a", **overrides):
    values = {
        "normalized_url": url,
        "source_id": "Feed A",
        "content_hash": content_hash,
        "model": "deepseek-test",
        "rule_version": "enrich-v1",
    }
    values.update(overrides)
    return values


class CandidateCacheTests(unittest.TestCase):
    def test_url_normalization_removes_tracking_and_fragment(self):
        left = run_update.norm_url(
            "HTTPS://Example.COM/post/?utm_source=x&keep=1&fbclid=abc#section"
        )
        right = run_update.norm_url("https://example.com/post?keep=1")
        self.assertEqual(left, right)

    def test_content_hash_ignores_whitespace_but_detects_changes(self):
        first = {"title": "A  title", "summary": "one\n two", "article_text": "body"}
        same = {"title": "A title", "summary": "one two", "article_text": "body"}
        changed = {**same, "summary": "changed summary"}
        self.assertEqual(candidate_content_hash(first), candidate_content_hash(same))
        self.assertNotEqual(candidate_content_hash(first), candidate_content_hash(changed))

    def test_rejected_hit_and_content_model_rule_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = CandidateCache(Path(tmp) / "cache.json", environ={}, now_fn=lambda: NOW)
            cache.remember(**context(), status="rejected")
            self.assertEqual(cache.lookup(**context())["status"], "rejected")
            self.assertIsNone(cache.lookup(**context(content_hash="hash-b")))
            self.assertIsNone(cache.lookup(**context(model="new-model")))
            self.assertIsNone(cache.lookup(**context(rule_version="enrich-v2")))
            self.assertEqual(cache.stats["hits"], 1)
            self.assertEqual(cache.stats["content_changed"], 1)
            self.assertEqual(cache.stats["version_invalidated"], 2)

    def test_ttl_expiry_and_error_backoff(self):
        clock = [NOW]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = CandidateCache(
                path,
                environ={"CANDIDATE_CACHE_TTL_DAYS": "21", "CANDIDATE_CACHE_ERROR_TTL_HOURS": "6"},
                now_fn=lambda: clock[0],
            )
            cache.remember(**context(url="https://example.com/rejected"), status="rejected")
            cache.remember(
                **context(url="https://example.com/error"),
                status="error",
                error_type="TimeoutError",
            )
            clock[0] = NOW + timedelta(hours=5)
            self.assertEqual(
                cache.lookup(**context(url="https://example.com/error"))["status"], "error"
            )
            clock[0] = NOW + timedelta(hours=7)
            self.assertIsNone(cache.lookup(**context(url="https://example.com/error")))
            clock[0] = NOW + timedelta(days=21)
            self.assertIsNone(cache.lookup(**context(url="https://example.com/rejected")))

    def test_corrupt_cache_falls_back_and_finalizes_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text("{broken", encoding="utf-8")
            cache = CandidateCache(path, environ={}, now_fn=lambda: NOW)
            cache.remember(**context(), status="accepted", enrichment={"zh_title": "标题"})
            cache.finalize()
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["entries"]), 1)
            self.assertEqual(data["last_stats"]["writes"], 1)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_warm_cache_keeps_repeat_model_call_ratio_below_five_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            warm = CandidateCache(path, environ={}, now_fn=lambda: NOW)
            contexts = [
                context(url=f"https://example.com/{i}", content_hash=f"hash-{i}")
                for i in range(100)
            ]
            for item_context in contexts:
                warm.remember(**item_context, status="rejected")
            warm.finalize()

            run = CandidateCache(path, environ={}, now_fn=lambda: NOW + timedelta(hours=1))
            misses = sum(run.lookup(**item_context) is None for item_context in contexts)
            self.assertLess(misses / len(contexts), 0.05)
            self.assertEqual(run.stats["hits"], 100)


class CandidateCachePipelineTests(unittest.TestCase):
    def setUp(self):
        self.original_cache = run_update.CANDIDATE_CACHE
        self.tmp = tempfile.TemporaryDirectory()
        run_update.CANDIDATE_CACHE = CandidateCache(
            Path(self.tmp.name) / "cache.json", environ={}, now_fn=lambda: NOW
        )

    def tearDown(self):
        run_update.CANDIDATE_CACHE = self.original_cache
        self.tmp.cleanup()

    def test_rejected_candidates_do_not_call_llm_twice(self):
        item = {
            "id": "item-1",
            "title": "Unrelated story",
            "summary": "Not about data",
            "article_text": "Full text",
            "source": "Feed A",
            "link": "https://example.com/story?utm_source=test",
            "vendor_default": False,
        }
        with patch.object(run_update, "llm_chat", return_value={"relevant": False}) as call:
            self.assertEqual(run_update.llm_enrich([dict(item)], ("k", "base", "model")), [])
            self.assertEqual(run_update.llm_enrich([dict(item)], ("k", "base", "model")), [])
        self.assertEqual(call.call_count, 1)
        self.assertEqual(run_update.CANDIDATE_CACHE.stats["rejected_hits"], 1)


if __name__ == "__main__":
    unittest.main()
