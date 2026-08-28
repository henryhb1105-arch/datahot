import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from discovery.scout import (  # noqa: E402
    extract_openai_sources,
    managed_source_health,
    normalize_url,
    run_scout,
)


NOW = datetime(2026, 8, 28, 6, 0, tzinfo=timezone.utc)


class DiscoveryTests(unittest.TestCase):
    def test_configured_sources_share_a_non_destructive_health_lifecycle(self):
        rows = managed_source_health(
            [
                {"name": "Healthy", "enabled": True},
                {"name": "Failing", "enabled": True},
                {"name": "Off", "enabled": False},
            ],
            {"Failing": {"fails": 4, "total_fetched": 20, "total_accepted": 2}},
        )
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["Healthy"]["state"], "ACTIVE")
        self.assertEqual(by_name["Failing"]["state"], "DEGRADED")
        self.assertEqual(by_name["Off"]["state"], "PAUSED")
        self.assertFalse(by_name["Failing"]["automatic_pause"])

    def test_normalize_url_removes_tracking_and_fragment(self):
        self.assertEqual(
            normalize_url("HTTPS://Example.com/post/?utm_source=x&keep=1#part"),
            "https://example.com/post?keep=1",
        )
        self.assertEqual(normalize_url("javascript:alert(1)"), "")
        self.assertEqual(normalize_url("https://example.com:bad/post"), "")

    def test_extracts_only_unique_web_search_sources(self):
        payload = {
            "output": [
                {"type": "web_search_call", "action": {"sources": [
                    {"url": "https://new.example/a?utm_source=x", "title": "A"},
                    {"url": "https://new.example/a", "title": "A duplicate"},
                ]}},
                {"type": "message", "content": [{"annotations": [
                    {"type": "url_citation", "url": "https://other.example/b", "title": "B"}
                ]}]},
            ]
        }
        sources = extract_openai_sources(payload)
        self.assertEqual([row["url"] for row in sources], [
            "https://new.example/a", "https://other.example/b",
        ])

    def test_shadow_registry_deduplicates_catalog_and_promotes_repeated_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sources = folder / "sources.json"
            latest = folder / "latest.json"
            queries = folder / "queries.json"
            state = folder / "state.json"
            report = folder / "report.md"
            sources.write_text(json.dumps([
                {"name": "Known", "url": "https://known.example/feed.xml"}
            ]), encoding="utf-8")
            latest.write_text(json.dumps({"events": [{"event_id": "a" * 12, "items": [
                {"link": "https://known.example/already"}
            ]}]}), encoding="utf-8")
            queries.write_text(json.dumps([
                {"id": "data", "query": "data", "lookback_days": 7}
            ]), encoding="utf-8")

            class FakeOpenAI:
                def search(self, _query, *, blocked_hosts):
                    self.blocked_hosts = blocked_hosts
                    return [
                        {"url": "https://known.example/already", "title": "duplicate"},
                        {"url": "https://fresh.example/one", "title": "fresh one"},
                        {"url": "https://fresh.example/two", "title": "fresh two"},
                    ]

            payload = run_scout(
                sources_path=sources, latest_path=latest, queries_path=queries,
                state_path=state, report_path=report, now=NOW, force=True,
                environ={"OPENAI_API_KEY": "test", "DISCOVERY_HN_ENABLED": "false"},
                openai_provider=FakeOpenAI(),
            )
            self.assertEqual(payload["stats"]["catalog_duplicates"], 1)
            self.assertEqual(payload["stats"]["article_candidates"], 2)
            self.assertEqual(payload["source_candidates"][0]["host"], "fresh.example")
            self.assertEqual(payload["source_candidates"][0]["state"], "DISCOVERED")

            class FakeHN:
                def __call__(self):
                    return [{
                        "url": "https://fresh.example/three", "title": "third",
                        "channel": "hn", "provider_refs": ["hn:top"], "signal": 100,
                    }]

            payload = run_scout(
                sources_path=sources, latest_path=latest, queries_path=queries,
                state_path=state, report_path=report, now=NOW, force=True,
                environ={"DISCOVERY_OPENAI_ENABLED": "false"}, hn_provider=FakeHN(),
            )
            candidate = next(row for row in payload["source_candidates"] if row["host"] == "fresh.example")
            self.assertEqual(candidate["state"], "PROBATION")
            self.assertFalse(candidate["auto_publish"])
            self.assertIn("影子模式", report.read_text(encoding="utf-8"))

    def test_missing_openai_key_is_safe_and_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, payload in (
                ("sources.json", []), ("latest.json", {"events": []}), ("queries.json", []),
            ):
                (folder / name).write_text(json.dumps(payload), encoding="utf-8")
            result = run_scout(
                sources_path=folder / "sources.json",
                latest_path=folder / "latest.json",
                queries_path=folder / "queries.json",
                state_path=folder / "state.json",
                report_path=folder / "report.md",
                now=NOW, force=True,
                environ={"DISCOVERY_HN_ENABLED": "false"},
            )
            provider = result["providers"][0]
            self.assertEqual(provider["status"], "skipped")
            self.assertIn("OPENAI_API_KEY", provider["reason"])

    def test_link_graph_rejects_generic_profile_and_documentation_links(self):
        from discovery.scout import discover_link_graph

        latest = {"events": [
            {
                "event_id": "a" * 12, "quality_score": 80,
                "items": [{"link": "https://known.example/a"}],
                "content_blocks": [
                    {"href": "https://github.com/org/repo"},
                    {"href": "https://new.example/research/report-a"},
                ],
            },
            {
                "event_id": "b" * 12, "quality_score": 85,
                "items": [{"link": "https://known.example/b"}],
                "content_blocks": [
                    {"href": "https://www.linkedin.com/in/person"},
                    {"href": "https://new.example/insights/report-b"},
                ],
            },
        ]}
        rows = discover_link_graph(latest, {"known.example"})
        self.assertEqual([row["url"] for row in rows], [
            "https://new.example/insights/report-b",
        ])


if __name__ == "__main__":
    unittest.main()
