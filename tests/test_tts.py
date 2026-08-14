import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402
from tts_generate import (  # noqa: E402
    empty_manifest,
    load_manifest,
    prune_expired,
    select_jobs,
    write_manifest,
)
from tts_text import build_tts_script, narration_hash  # noqa: E402


def event_fixture():
    return {
        "event_id": "0123456789ab",
        "zh_title": "数据智能体正在进入生产环境",
        "zh_summary": "企业开始让数据智能体理解业务语义、分析指标变化，并给出可以验证的决策建议。",
        "reason": "推荐理由：这代表数据平台从查询工具走向可执行的业务系统。",
        "full_zh": "## 关键进展\n\n团队开始建立评测和审计机制。\n\n```sql\nSELECT secret FROM users\n```\n\n详情 https://example.com/private",
        "content_blocks": [
            {"type": "heading", "children": [{"type": "text", "text": "关键进展"}]},
            {"type": "paragraph", "children": [{"type": "text", "text": "团队开始建立评测和审计机制。"}]},
            {"type": "code", "text": "SELECT secret FROM users"},
            {"type": "table", "rows": [{"cells": [{"children": [{"type": "text", "text": "不朗读表格"}]}]}]},
        ],
        "category": "agent",
        "importance": 82,
        "topics": ["Data Agent"],
        "vendors": [],
        "heat": 80,
        "published": "2026-08-12T09:00:00+08:00",
        "first_seen": "2026-08-12T09:05:00+08:00",
        "items": [{
            "id": "source-1",
            "source": "测试信源",
            "link": "https://example.com/article",
            "published": "2026-08-12T09:00:00+08:00",
            "title": "Source title",
        }],
    }


class TTSTextTests(unittest.TestCase):
    def test_script_is_bounded_deterministic_and_excludes_non_narrative_blocks(self):
        event = event_fixture()
        first = build_tts_script(event, maximum=220)
        second = build_tts_script(event, maximum=220)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 220)
        self.assertIn(event["zh_title"], first)
        self.assertIn("企业开始让数据智能体", first)
        self.assertIn("推荐理由：这代表", first)
        self.assertNotIn("推荐理由：推荐理由", first)
        self.assertNotIn("SELECT", first)
        self.assertNotIn("不朗读表格", first)
        self.assertNotIn("https://", first)

    def test_hash_changes_with_voice_or_text(self):
        self.assertEqual(narration_hash("正文", "v1"), narration_hash("正文", "v1"))
        self.assertNotEqual(narration_hash("正文", "v1"), narration_hash("正文", "v2"))
        self.assertNotEqual(narration_hash("正文", "v1"), narration_hash("正文变化", "v1"))

    def test_script_does_not_end_with_a_hard_cut_fragment(self):
        event = event_fixture()
        event["zh_summary"] = "这是一段很长且没有结束标点的说明" * 20
        script = build_tts_script(event, maximum=140)
        self.assertNotIn("没有结束标点的说。", script)
        self.assertTrue(script.endswith(("。", "！", "？", "；")))


class TTSManifestTests(unittest.TestCase):
    def test_manifest_round_trip_and_cache_hit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "data" / "tts-manifest.json"
            manifest = empty_manifest("datahot-anchor-v1")
            jobs = select_jobs([event_fixture()], manifest, root, "datahot-anchor-v1")
            self.assertEqual(len(jobs), 1)
            job = jobs[0]
            audio = root / job.audio_path
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"ID3-test")
            manifest["items"][job.event_id] = {
                "status": "ready",
                "content_hash": job.content_hash,
                "audio_path": job.audio_path,
                "duration_seconds": 58,
                "generated_at": "2026-08-12T00:00:00+00:00",
            }
            write_manifest(manifest_path, manifest)
            loaded = load_manifest(manifest_path, "datahot-anchor-v1")
            self.assertEqual(select_jobs([event_fixture()], loaded, root, "datahot-anchor-v1"), [])
            self.assertEqual(json.loads(manifest_path.read_text())["version"], 1)

    def test_voice_version_invalidates_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            write_manifest(path, empty_manifest("v1"))
            self.assertEqual(load_manifest(path, "v2")["items"], {})
            self.assertEqual(load_manifest(path, "v2")["voice_version"], "v2")

    def test_prune_only_removes_valid_expired_audio_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "audio/2026/07/0123456789ab-aaaaaaaaaaaa.mp3"
            audio = root / relative
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"old")
            manifest = empty_manifest("v1")
            manifest["items"] = {
                "0123456789ab": {
                    "audio_path": relative,
                    "generated_at": "2026-07-01T00:00:00+00:00",
                },
                "badbadbadbad": {
                    "audio_path": "../../outside.mp3",
                    "generated_at": "2026-07-01T00:00:00+00:00",
                },
            }
            removed = prune_expired(
                manifest, root, 30, now=datetime(2026, 8, 12, tzinfo=timezone.utc),
            )
            self.assertEqual(set(removed), {"0123456789ab", "badbadbadbad"})
            self.assertFalse(audio.exists())


class TTSDetailRenderingTests(unittest.TestCase):
    def test_ready_audio_renders_accessible_player(self):
        item = {
            "status": "ready",
            "audio_path": "audio/2026/08/0123456789ab-aaaaaaaaaaaa.mp3",
            "duration_seconds": 58,
        }
        page = build_site.render_detail(event_fixture(), [event_fixture()], "", tts_item=item)
        self.assertIn("data-tts-open", page)
        self.assertIn("data-tts-player", page)
        self.assertIn("../audio/2026/08/0123456789ab-aaaaaaaaaaaa.mp3", page)
        self.assertIn('src="../tts-player.js"', page)
        self.assertIn("aria-label=\"文章精华朗读\"", page)
        self.assertIn('aria-label="速听" title="速听"', page)
        self.assertIn('class="sbtn-label" data-tts-open-label>速听</span>', page)
        self.assertNotIn("听这篇", page)

    def test_missing_or_unsafe_audio_hides_player(self):
        page = build_site.render_detail(event_fixture(), [event_fixture()], "")
        self.assertNotIn("data-tts-open", page)
        unsafe = {"status": "ready", "audio_path": "../../secret.mp3", "duration_seconds": 10}
        page = build_site.render_detail(event_fixture(), [event_fixture()], "", tts_item=unsafe)
        self.assertNotIn("data-tts-open", page)

    def test_detail_actions_are_consistent_and_mobile_toolbar_stays_single_line(self):
        item = {
            "status": "ready",
            "audio_path": "audio/2026/08/0123456789ab-aaaaaaaaaaaa.mp3",
            "duration_seconds": 58,
        }
        page = build_site.render_detail(event_fixture(), [event_fixture()], "", tts_item=item)
        self.assertIn(".topbar .back{flex:0 0 auto;white-space:nowrap}", page)
        self.assertIn("flex:0 0 auto;white-space:nowrap", page)
        self.assertIn(".sharebtns .sbtn{min-width:76px}", page)
        self.assertIn(".topbar{align-items:center;flex-direction:row;gap:8px}", page)
        self.assertIn(".sharebtns{width:auto;gap:4px;overflow:visible;padding-bottom:0}", page)
        self.assertIn(".sharebtns .sbtn{width:44px;min-width:44px;height:44px;padding:0}", page)
        self.assertIn(".sharebtns .sbtn-label{display:none}", page)
        self.assertNotIn(".sharebtns::-webkit-scrollbar", page)
        self.assertIn('aria-label="收藏" aria-pressed="false"', page)
        self.assertIn('class="sbtn-label">收藏</span>', page)
        self.assertIn('aria-label="海报"', page)
        self.assertIn('class="sbtn-label">海报</span>', page)
        self.assertIn('aria-label="分享"', page)
        self.assertIn('class="sbtn-label">分享</span>', page)
        self.assertIn('aria-label="原文"', page)
        self.assertIn('class="sbtn-label">原文</span>', page)
        self.assertEqual(page.count('class="sbtn-label"'), 5)
        self.assertIn('class="sbtn ghost" href="https://example.com/article"', page)
        self.assertNotIn('class="meta-original"', page)
        self.assertIn("@media(max-width:359px)", page)
        self.assertIn(".topbar.detail-context .back-label{display:none}", page)


class TTSWorkflowTests(unittest.TestCase):
    def test_generated_audio_retries_push_and_calls_reusable_publish(self):
        tts_workflow = (ROOT / ".github" / "workflows" / "tts.yml").read_text()
        deploy_workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
        self.assertIn("for attempt in 1 2 3", tts_workflow)
        self.assertIn('echo "changed=true" >> "$GITHUB_OUTPUT"', tts_workflow)
        self.assertIn("feat: update DataHot narration audio [skip ci]", tts_workflow)
        self.assertIn("uses: ./.github/workflows/deploy.yml", tts_workflow)
        self.assertIn("workflow_call:", deploy_workflow)
        self.assertIn("ref: main", deploy_workflow)


if __name__ == "__main__":
    unittest.main()
