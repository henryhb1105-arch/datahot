import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import build_site  # noqa: E402
from feed import ATOM, build_atom_feed, validate_atom_feed  # noqa: E402


SITE_BASE = "https://henryhb1105-arch.github.io/datahot"
NS = {"atom": ATOM}


def event(number, *, title=None, summary=None, source_link="https://source.example/post"):
    event_id = f"{number:012x}"
    return {
        "event_id": event_id,
        "zh_title": title if title is not None else f"事件 {number}",
        "zh_summary": summary if summary is not None else f"DataHot 摘要 {number}",
        "full_zh": "THIRD_PARTY_FULLTEXT_MUST_NOT_APPEAR <script>alert(1)</script>",
        "category": "platform",
        "category_label": "AI 数据平台",
        "published": "2026-08-11T08:00:00+08:00",
        "first_seen": "2026-08-11T09:00:00+08:00",
        "items": [{
            "source": "Source & Vendor",
            "link": source_link,
            "published": "2026-08-11T08:00:00+08:00",
            "ingested_at": "2026-08-11T09:30:00+08:00",
        }],
    }


class AtomFeedTests(unittest.TestCase):
    def test_feed_is_valid_atom_with_xml_escaping_and_safe_summary_only(self):
        title = 'A < B & "quoted"'
        summary = "摘要含 <标签> & 特殊字符"
        payload = build_atom_feed(
            [event(1, title=title, summary=summary)],
            "2026-08-11T10:00:00+08:00", site_base=SITE_BASE,
        )
        self.assertTrue(payload.startswith(b"<?xml"))
        root = ET.fromstring(payload)
        entry = root.find("atom:entry", NS)
        self.assertEqual(root.tag, f"{{{ATOM}}}feed")
        self.assertEqual(entry.findtext("atom:title", namespaces=NS), title)
        self.assertEqual(entry.findtext("atom:summary", namespaces=NS), summary)
        self.assertEqual(entry.find("atom:summary", NS).get("type"), "text")
        self.assertIsNone(entry.find("atom:content", NS))
        self.assertNotIn(b"THIRD_PARTY_FULLTEXT_MUST_NOT_APPEAR", payload)
        self.assertNotIn(b"<script>", payload)
        self.assertEqual(entry.find("atom:category", NS).get("label"), "AI 数据平台")
        self.assertEqual(entry.findtext("atom:source/atom:title", namespaces=NS), "Source & Vendor")
        self.assertEqual(validate_atom_feed(payload, site_base=SITE_BASE), [])

    def test_entry_ids_and_links_are_stable_absolute_https_urls(self):
        events = [event(i) for i in range(3)]
        first = ET.fromstring(build_atom_feed(
            events, "2026-08-11T10:00:00+08:00", site_base=SITE_BASE,
        ))
        second = ET.fromstring(build_atom_feed(
            list(reversed(events)), "2026-08-11T14:00:00+08:00", site_base=SITE_BASE,
        ))
        first_ids = [entry.findtext("atom:id", namespaces=NS) for entry in first.findall("atom:entry", NS)]
        second_ids = [entry.findtext("atom:id", namespaces=NS) for entry in second.findall("atom:entry", NS)]
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(len(first_ids), len(set(first_ids)))
        for entry_id in first_ids:
            self.assertTrue(entry_id.startswith(f"{SITE_BASE}/e/"))
            self.assertTrue(entry_id.endswith(".html"))

    def test_validator_checks_every_entry_detail_file(self):
        events = [event(i) for i in range(2)]
        payload = build_atom_feed(events, "2026-08-11T10:00:00+08:00", site_base=SITE_BASE)
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "e").mkdir()
            for item in events:
                (site / "e" / f'{item["event_id"]}.html').write_text("ok", encoding="utf-8")
            self.assertEqual(validate_atom_feed(payload, site_base=SITE_BASE, site_root=site), [])
            (site / "e" / f'{events[0]["event_id"]}.html').unlink()
            self.assertIn("entry_missing", validate_atom_feed(payload, site_base=SITE_BASE, site_root=site))

    def test_http_source_is_omitted_but_entry_stays_valid(self):
        payload = build_atom_feed(
            [event(1, source_link="http://unsafe.example/post")],
            "2026-08-11T10:00:00+08:00", site_base=SITE_BASE,
        )
        root = ET.fromstring(payload)
        self.assertIsNone(root.find("atom:entry/atom:source/atom:link", NS))
        self.assertEqual(validate_atom_feed(payload, site_base=SITE_BASE), [])

    def test_empty_summary_gets_datahot_fallback(self):
        payload = build_atom_feed(
            [event(1, summary="")], "2026-08-11T10:00:00+08:00", site_base=SITE_BASE,
        )
        root = ET.fromstring(payload)
        summary = root.findtext("atom:entry/atom:summary", namespaces=NS)
        self.assertIn("DataHot 已收录", summary)
        self.assertEqual(validate_atom_feed(payload, site_base=SITE_BASE), [])

    def test_stale_insight_label_is_canonicalized_in_feed(self):
        item = event(1)
        item["category"] = "insight"
        item["category_label"] = "AI 分析与洞察"
        root = ET.fromstring(build_atom_feed(
            [item], "2026-08-11T10:00:00+08:00", site_base=SITE_BASE,
        ))
        self.assertEqual(
            root.find("atom:entry/atom:category", NS).get("label"), "AI分析",
        )


class FeedDiscoveryTests(unittest.TestCase):
    def test_root_nested_and_detail_pages_include_autodiscovery(self):
        marker = 'type="application/atom+xml"'
        self.assertIn(marker, build_site.page_shell("Title", "Description", "", "", ""))
        self.assertIn(marker, build_site.page_shell("Title", "Description", "", "", "", prefix="../"))
        detail_event = event(1)
        detail_event.update({
            "reason": "", "heat": 50, "importance": 50, "signal": 0,
            "topics": [], "vendors": [], "shelf": "news", "pinned": False,
        })
        self.assertIn(marker, build_site.render_detail(detail_event, [detail_event], ""))
        self.assertIn(f'href="{SITE_BASE}/feed.xml"', build_site.feed_discovery())

    def test_feature_switch_removes_autodiscovery(self):
        with patch.dict(build_site.os.environ, {"FEED_ENABLED": "false"}, clear=False):
            self.assertEqual(build_site.feed_discovery(), "")
            self.assertNotIn("application/atom+xml", build_site.page_shell("Title", "Description", "", "", ""))


if __name__ == "__main__":
    unittest.main()
