import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from agent_feed import (  # noqa: E402
    build_agent_feed, find_forbidden_fields, recommended_push,
    validate_agent_feed,
)
from site_config import DEFAULT_SITE_BASE_URL  # noqa: E402


GENERATED_AT = "2026-08-22T12:00:00+08:00"
SITE_BASE = DEFAULT_SITE_BASE_URL


def event(index, *, importance=80, pinned=False, sources=1, first_seen=None):
    event_id = f"{index:012x}"[-12:]
    return {
        "event_id": event_id,
        "zh_title": f"数据与 AI 重要更新 {index}",
        "zh_summary": "这是一条经过中文编辑的完整事件摘要。",
        "reason": "它会影响数据产品的能力边界和落地方式。",
        "full_zh": "THIRD_PARTY_BODY_MUST_NOT_APPEAR",
        "content_blocks": [{"type": "paragraph", "text": "forbidden"}],
        "category": "platform",
        "category_label": "AI 数据平台",
        "vendors": ["Vendor"],
        "topics": ["平台AI化"],
        "heat": 61,
        "importance": importance,
        "star": False,
        "shelf": "news",
        "pinned": pinned,
        "published": "2026-08-22T08:00:00+08:00",
        "first_seen": first_seen or "2026-08-22T09:00:00+08:00",
        "items": [
            {
                "source": f"Source {source_index}",
                "link": f"https://source.example/{source_index}",
                "article_text": "forbidden",
            }
            for source_index in range(sources)
        ],
    }


class AgentFeedTests(unittest.TestCase):
    def test_feed_is_small_versioned_and_uses_stable_detail_links(self):
        item = event(1, sources=2)
        payload = build_agent_feed([item], GENERATED_AT, site_base=SITE_BASE)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["push_policy"]["recommended_poll_seconds"], 900)
        projected = payload["events"][0]
        self.assertEqual(projected["event_id"], item["event_id"])
        self.assertEqual(
            projected["links"]["detail"],
            f"{SITE_BASE}/e/{item['event_id']}.html",
        )
        self.assertEqual(projected["sources"], {
            "count": 2, "names": ["Source 0", "Source 1"],
        })
        self.assertEqual(find_forbidden_fields(payload), [])
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("THIRD_PARTY_BODY_MUST_NOT_APPEAR", encoded)
        self.assertNotIn("https://source.example", encoded)

    def test_server_side_push_policy_is_deterministic(self):
        self.assertEqual(recommended_push(event(1, importance=80)), (True, "importance_80"))
        self.assertEqual(
            recommended_push(event(2, importance=75, sources=2)),
            (True, "multi_source_importance_75"),
        )
        self.assertEqual(
            recommended_push(event(3, importance=20, pinned=True)),
            (True, "editor_pinned"),
        )
        self.assertEqual(recommended_push(event(4, importance=79)), (False, None))

    def test_feed_uses_discovery_window_and_excludes_unfinished_items(self):
        recent = event(1)
        old = event(2, first_seen="2026-08-10T09:00:00+08:00")
        unfinished = event(3)
        unfinished["zh_summary"] = ""
        payload = build_agent_feed(
            [old, unfinished, recent], GENERATED_AT, site_base=SITE_BASE,
        )
        self.assertEqual(
            [item["event_id"] for item in payload["events"]],
            [recent["event_id"]],
        )

    def test_validator_checks_uniqueness_order_and_detail_files(self):
        first = event(1, first_seen="2026-08-22T10:00:00+08:00")
        second = event(2, first_seen="2026-08-22T09:00:00+08:00")
        payload = build_agent_feed([second, first], GENERATED_AT, site_base=SITE_BASE)
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            (site / "e").mkdir()
            for item in (first, second):
                (site / "e" / f"{item['event_id']}.html").write_text("ok", encoding="utf-8")
            self.assertEqual(
                validate_agent_feed(payload, site_base=SITE_BASE, site_root=site),
                [],
            )
            payload["events"].append(dict(payload["events"][0]))
            errors = validate_agent_feed(payload, site_base=SITE_BASE, site_root=site)
            self.assertTrue(any(error.startswith("duplicate:") for error in errors))
            self.assertTrue(any(error.startswith("order:") for error in errors))
            (site / "e" / f"{first['event_id']}.html").unlink()
            errors = validate_agent_feed(payload, site_base=SITE_BASE, site_root=site)
            self.assertTrue(any(error.startswith("detail_missing:") for error in errors))


if __name__ == "__main__":
    unittest.main()
