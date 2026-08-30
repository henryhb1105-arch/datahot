import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
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

    def english_event(self, event_id="cccccccccccc"):
        event = self.event(event_id, "Anthropic经济指数：AI采用的地理与企业不均")
        event["items"] = [{
            "title": "Anthropic Economic Index: Uneven AI adoption \\ Anthropic",
            "source": "Anthropic Economic Index",
        }]
        return event

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

    def test_english_discovery_selection_uses_source_title_without_translation(self):
        data = {"top": ["aaaaaaaaaaaa", "cccccccccccc"], "events": [
            self.event("aaaaaaaaaaaa"), self.english_event(),
        ]}
        selected = growth_share.select_highlight(data, require_english=True)
        self.assertEqual(selected["event_id"], "cccccccccccc")
        self.assertEqual(
            growth_share.english_title(selected),
            "Anthropic Economic Index: Uneven AI adoption",
        )
        self.assertEqual(growth_share.english_title(self.event()), "")

    def test_one_bilingual_slot_rotates_across_all_five_times(self):
        start = datetime(2026, 8, 30, 8, 0, tzinfo=growth_share.TZ)
        slots = [growth_share.bilingual_slot(start + timedelta(days=offset)) for offset in range(5)]
        self.assertEqual(set(slots), set(range(growth_share.DAILY_SLOTS)))
        for day in range(5):
            now = start + timedelta(days=day)
            self.assertEqual(sum(slot == growth_share.bilingual_slot(now) for slot in range(5)), 1)

    def test_one_image_card_slot_rotates_and_stays_distinct_from_bilingual(self):
        start = datetime(2026, 8, 30, 8, 0, tzinfo=growth_share.TZ)
        slots = [growth_share.image_card_slot(start + timedelta(days=offset)) for offset in range(5)]
        self.assertEqual(set(slots), set(range(growth_share.DAILY_SLOTS)))
        for day in range(5):
            now = start + timedelta(days=day)
            self.assertNotEqual(growth_share.image_card_slot(now), growth_share.bilingual_slot(now))

    def test_post_is_bounded_and_has_utf8_link_facet(self):
        event = self.event(title="数据" * 80)
        event["category"] = "agent"
        post = growth_share.build_post(event, slot=4)
        self.assertLessEqual(len(post["text"]), 300)
        encoded = post["text"].encode("utf-8")
        for facet in post["facets"]:
            index = facet["index"]
            value = encoded[index["byteStart"]:index["byteEnd"]].decode("utf-8")
            feature = facet["features"][0]
            if feature["$type"].endswith("#link"):
                self.assertEqual(value, post["url"])
            else:
                self.assertEqual(value, f'#{feature["tag"]}')
        self.assertNotIn("example.com", post["text"])
        self.assertIn("5/5", post["text"])
        self.assertIn("#DataEngineering #AIAgents #数据", post["text"])
        self.assertIn("utm_source=bluesky&utm_content=text", post["url"])
        self.assertEqual(post["canonical_url"], "https://datahot.xiahongbin.com/e/aaaaaaaaaaaa.html")

    def test_bilingual_post_is_bounded_has_matching_languages_and_facets(self):
        post = growth_share.build_post(self.english_event(), slot=3, creative="card", bilingual=True)
        self.assertLessEqual(len(post["text"]), 300)
        self.assertTrue(post["text"].startswith(
            "DataHot data pick 4/5｜Anthropic Economic Index: Uneven AI adoption"
        ))
        self.assertIn("Read / 中文全文：", post["text"])
        self.assertEqual(post["langs"], ["en", "zh-CN"])
        self.assertEqual(post["language_variant"], "bilingual")
        self.assertEqual(post["card_title"], "Anthropic Economic Index: Uneven AI adoption")
        encoded = post["text"].encode("utf-8")
        for facet in post["facets"]:
            index = facet["index"]
            value = encoded[index["byteStart"]:index["byteEnd"]].decode("utf-8")
            feature = facet["features"][0]
            self.assertEqual(value, post["url"] if feature["$type"].endswith("#link") else f'#{feature["tag"]}')

    def test_tracking_url_accepts_only_measurable_variants(self):
        self.assertEqual(
            growth_share.tracked_url("aaaaaaaaaaaa", source="x", creative="card"),
            "https://datahot.xiahongbin.com/e/aaaaaaaaaaaa.html?utm_source=x&utm_content=card",
        )
        with self.assertRaises(ValueError):
            growth_share.tracked_url("aaaaaaaaaaaa", source="newsletter", creative="card")

    def test_social_card_uses_only_safe_first_party_article_figures(self):
        event = self.event()
        event["content_blocks"] = [
            {"type": "figure", "cached_src": "../media/bbbbbbbbbbbb/wrong12345678.webp"},
            {
                "type": "figure", "cached_src": "../media/aaaaaaaaaaaa/123456789abc.webp",
                "alt": "上下文相关图", "width": "1200", "height": "invalid",
            },
        ]
        image = growth_share.social_image_for_event(event, growth_share.SITE_BASE)
        self.assertEqual(image["url"], "https://datahot.xiahongbin.com/media/aaaaaaaaaaaa/123456789abc.webp")
        self.assertEqual(image["alt"], "上下文相关图")
        self.assertEqual(image["width"], 1200)
        self.assertIsNone(image["height"])

        event["content_blocks"] = [{
            "type": "figure", "cached_src": "https://tracker.example/private.webp",
        }]
        self.assertIsNone(growth_share.social_image_for_event(event, growth_share.SITE_BASE))

    def test_image_highlight_prefers_the_highest_ranked_safe_candidate(self):
        unsafe = self.event("aaaaaaaaaaaa", "没有安全图片")
        unsafe["content_blocks"] = [{"type": "figure", "cached_src": "https://tracker.example/a.webp"}]
        safe = self.event("bbbbbbbbbbbb", "有安全图片")
        safe["content_blocks"] = [{
            "type": "figure", "cached_src": "../media/bbbbbbbbbbbb/123456789abc.webp",
        }]
        later = self.event("cccccccccccc", "更靠后的安全图片")
        later["content_blocks"] = [{
            "type": "figure", "cached_src": "../media/cccccccccccc/123456789abc.webp",
        }]
        data = {"top": [unsafe["event_id"], safe["event_id"], later["event_id"]],
                "events": [unsafe, safe, later]}
        self.assertEqual(growth_share.select_image_highlight(data)["event_id"], safe["event_id"])
        self.assertEqual(
            growth_share.select_image_highlight(data, excluded_event_ids={safe["event_id"]})["event_id"],
            later["event_id"],
        )
        self.assertIsNone(growth_share.select_image_highlight(data, limit=1))

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
        self.assertEqual(result["language_variant"], "zh")
        self.assertEqual(request.call_count, 2)
        self.assertIn("com.atproto.repo.putRecord", request.call_args_list[1].args[0])
        wait_until_live.assert_called_once_with("https://datahot.xiahongbin.com/e/bbbbbbbbbbbb.html")

    def test_text_slot_reserves_the_daily_image_candidate(self):
        now = datetime(2026, 8, 28, 14, 30, tzinfo=growth_share.TZ)
        treatment_slot = growth_share.image_card_slot(now)
        text_slot = next(slot for slot in range(growth_share.DAILY_SLOTS) if slot not in {
            treatment_slot, growth_share.bilingual_slot(now),
        })
        card = self.event("aaaaaaaaaaaa", "保留给图文卡")
        card["content_blocks"] = [{
            "type": "figure", "cached_src": "../media/aaaaaaaaaaaa/123456789abc.webp",
        }]
        text = self.event("bbbbbbbbbbbb", "纯文字时段使用")
        data = {"top": [card["event_id"], text["event_id"]], "events": [card, text]}
        responses = [
            {"did": "did:plc:test", "accessJwt": "token"},
            {"uri": "at://did:plc:test/app.bsky.feed.post/text"},
        ]
        with patch.object(growth_share, "_get_record", side_effect=[None] * 5), \
                patch.object(growth_share, "_json_request", side_effect=responses), \
                patch.object(growth_share, "wait_until_live"):
            result = growth_share.publish(
                data,
                handle="datahot.example",
                password="unit-test-only",
                slot=text_slot,
                now=now,
            )
        self.assertEqual(result["event_id"], text["event_id"])
        self.assertEqual(result["creative"], "text")

    def test_publish_uses_bilingual_record_only_for_the_rotating_slot(self):
        featured = self.english_event()
        data = {"top": [featured["event_id"]], "events": [featured]}
        responses = [
            {"did": "did:plc:test", "accessJwt": "token"},
            {"uri": "at://did:plc:test/app.bsky.feed.post/bilingual"},
        ]
        now = datetime(2026, 8, 30, 17, 47, tzinfo=growth_share.TZ)
        self.assertEqual(growth_share.bilingual_slot(now), 3)
        with patch.object(growth_share, "_get_record", side_effect=[None] * 5), \
                patch.object(growth_share, "_json_request", side_effect=responses) as request, \
                patch.object(growth_share, "wait_until_live"):
            result = growth_share.publish(
                data,
                handle="datahot.example",
                password="unit-test-only",
                slot=3,
                now=now,
            )
        self.assertEqual(result["language_variant"], "bilingual")
        record = request.call_args_list[1].kwargs["payload"]["record"]
        self.assertEqual(record["langs"], ["en", "zh-CN"])
        self.assertTrue(record["text"].startswith("DataHot data pick 4/5｜"))

    def test_publish_adds_external_image_card_and_matching_attribution(self):
        text_only = self.event("bbbbbbbbbbbb", "更靠前的纯文字候选")
        featured = self.event()
        featured["content_blocks"] = [{
            "type": "figure", "cached_src": "../media/aaaaaaaaaaaa/123456789abc.webp",
            "alt": "文章证据图", "width": 1200, "height": 630,
        }]
        data = {"top": ["bbbbbbbbbbbb", "aaaaaaaaaaaa"], "events": [text_only, featured]}
        responses = [
            {"did": "did:plc:test", "accessJwt": "token"},
            {"uri": "at://did:plc:test/app.bsky.feed.post/card"},
        ]
        now = datetime(2026, 8, 28, 14, 30, tzinfo=growth_share.TZ)
        slot = growth_share.image_card_slot(now)
        blob = {"$type": "blob", "ref": {"$link": "bafyreicard"}, "mimeType": "image/webp", "size": 1234}
        with patch.object(growth_share, "_get_record", side_effect=[None] * 5), \
                patch.object(growth_share, "_json_request", side_effect=responses) as request, \
                patch.object(growth_share, "wait_until_live"), \
                patch.object(growth_share, "_upload_image_blob", return_value=blob) as upload:
            result = growth_share.publish(
                data,
                handle="datahot.example",
                password="unit-test-only",
                slot=slot,
                now=now,
            )
        self.assertEqual(result["creative"], "card")
        upload.assert_called_once_with(
            token="token",
            image_url="https://datahot.xiahongbin.com/media/aaaaaaaaaaaa/123456789abc.webp",
        )
        record = request.call_args_list[1].kwargs["payload"]["record"]
        external = record["embed"]["external"]
        self.assertEqual(external["thumb"], blob)
        self.assertEqual(
            external["uri"],
            "https://datahot.xiahongbin.com/e/aaaaaaaaaaaa.html?utm_source=bluesky&utm_content=card",
        )
        self.assertIn(external["uri"], record["text"])

    def test_image_upload_failure_falls_back_to_tracked_text(self):
        featured = self.event()
        featured["content_blocks"] = [{
            "type": "figure", "cached_src": "../media/aaaaaaaaaaaa/123456789abc.webp",
        }]
        data = {"top": [featured["event_id"]], "events": [featured]}
        responses = [
            {"did": "did:plc:test", "accessJwt": "token"},
            {"uri": "at://did:plc:test/app.bsky.feed.post/text-fallback"},
        ]
        now = datetime(2026, 8, 28, 14, 30, tzinfo=growth_share.TZ)
        with patch.object(growth_share, "_get_record", side_effect=[None] * 5), \
                patch.object(growth_share, "_json_request", side_effect=responses) as request, \
                patch.object(growth_share, "wait_until_live"), \
                patch.object(growth_share, "_upload_image_blob", side_effect=ValueError("invalid image")):
            result = growth_share.publish(
                data,
                handle="datahot.example",
                password="unit-test-only",
                slot=growth_share.image_card_slot(now),
                now=now,
            )
        self.assertEqual(result["creative"], "text")
        record = request.call_args_list[1].kwargs["payload"]["record"]
        self.assertNotIn("embed", record)
        self.assertIn("utm_source=bluesky&utm_content=text", record["text"])

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

    def test_profile_sync_preserves_avatar_and_is_idempotent(self):
        existing = {
            "uri": "at://did:plc:test/app.bsky.actor.profile/self",
            "value": {"$type": "app.bsky.actor.profile", "avatar": {"ref": "blob"}},
        }
        responses = [
            {"did": "did:plc:test", "accessJwt": "token"},
            {"uri": "at://did:plc:test/app.bsky.actor.profile/self"},
        ]
        with patch.object(growth_share, "_get_record", return_value=existing), \
                patch.object(growth_share, "_json_request", side_effect=responses) as request:
            result = growth_share.sync_profile(handle="datahot.example", password="unit-test-only")
        self.assertEqual(result["status"], "synced")
        record = request.call_args_list[1].kwargs["payload"]["record"]
        self.assertEqual(record["avatar"], {"ref": "blob"})
        self.assertEqual(record["displayName"], growth_share.PROFILE_DISPLAY_NAME)
        self.assertEqual(record["website"], "https://datahot.xiahongbin.com/")

        synced = {"uri": existing["uri"], "value": {**existing["value"],
            "displayName": growth_share.PROFILE_DISPLAY_NAME,
            "description": growth_share.PROFILE_DESCRIPTION,
            "website": growth_share.PROFILE_WEBSITE,
        }}
        with patch.object(growth_share, "_get_record", return_value=synced), \
                patch.object(growth_share, "_json_request", return_value={"did": "did:plc:test", "accessJwt": "token"}) as request:
            result = growth_share.sync_profile(handle="datahot.example", password="unit-test-only")
        self.assertEqual(result["status"], "already_synced")
        self.assertEqual(request.call_count, 1)

    def test_growth_workflow_has_five_idempotent_daily_slots_with_retries(self):
        workflow = (ROOT / ".github" / "workflows" / "growth-share.yml").read_text(encoding="utf-8")
        deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        for hour, slot in ((0, 0), (3, 1), (6, 2), (9, 3), (12, 4)):
            primary = f"47 {hour} * * *"
            retry = f"57 {hour} * * *"
            self.assertIn(f'cron: "{primary}"', workflow)
            self.assertIn(f'cron: "{retry}"', workflow)
            self.assertIn(f'"{primary}"|"{retry}") slot={slot}', workflow)
        self.assertEqual(workflow.count("- cron:"), 10)
        self.assertIn('python3 pipeline/growth_share.py --slot "$GROWTH_SLOT"', workflow)
        self.assertIn("python3 pipeline/growth_share.py --sync-profile", workflow)
        self.assertNotIn("pipeline/growth_share.py", deploy)


if __name__ == "__main__":
    unittest.main()
