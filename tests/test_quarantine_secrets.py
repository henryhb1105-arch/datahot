import json
import os
import shutil
import string
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from quarantine_secrets import quarantine, scan_staged

SCANNER = os.getenv("GITLEAKS_BIN") or shutil.which("gitleaks")
if not SCANNER and (ROOT / "gitleaks").exists():
    SCANNER = str(ROOT / "gitleaks")


class SourceSecretQuarantineTests(unittest.TestCase):
    @unittest.skipUnless(SCANNER, "Gitleaks binary is required for integration checks")
    def test_real_staged_scan_quarantines_canary_and_retains_safe_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            git("init")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            shutil.copyfile(ROOT / ".gitleaks.toml", root / ".gitleaks.toml")
            path = root / "site/data/latest.json"; path.parent.mkdir(parents=True)
            baseline = {"events":[{"event_id":"a"*12,"body":"existing safe source"}]}
            path.write_text(json.dumps(baseline))
            git("add", "."); git("commit", "-m", "safe baseline")
            # A bare UUID can fall below the scanner's entropy threshold.
            canary = string.ascii_letters + string.digits + uuid.uuid4().hex
            candidate = {"events":baseline["events"] + [
                {"event_id":"b"*12,"body":"api_key = '" + canary + "'"},
                {"event_id":"c"*12,"body":"new safe source"}]}
            path.write_text(json.dumps(candidate, indent=2))
            git("add", ".")
            findings = scan_staged(root, SCANNER)
            self.assertTrue(findings, "scanner must detect the generated test credential")
            changes, paths = quarantine(root, findings, baseline)
            self.assertNotIn(canary, json.dumps(changes))
            self.assertEqual([row["event_id"] for row in json.loads(path.read_text())["events"]], ["a"*12,"c"*12])
            git("add", "--", *paths)
            self.assertEqual(scan_staged(root, SCANNER), [])

    def test_restores_changed_articles_and_removes_only_unsafe_new_candidates(self):
        baseline = {"events":[{"event_id":"a"*12,"full_zh":"safe original"}]}
        candidate = {"events":[{"event_id":"a"*12,"full_zh":"flagged-canary"},
                              {"event_id":"b"*12,"full_zh":"flagged-canary"},
                              {"event_id":"c"*12,"full_zh":"new safe source"}],"top":["b"*12,"c"*12]}
        finding = {"File":"site/data/latest.json","RuleID":"test-rule","StartLine":3,"Secret":"flagged-canary"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "site/data/latest.json"; path.parent.mkdir(parents=True)
            path.write_text(json.dumps(candidate))
            changes, paths = quarantine(Path(tmp), [finding,finding], baseline)
            result = json.loads(path.read_text())
            self.assertEqual(result["events"], baseline["events"] + [candidate["events"][2]])
            self.assertEqual(result["top"],["c"*12])
            self.assertEqual(len(changes),2)
            self.assertNotIn("flagged-canary",json.dumps(changes))
            self.assertEqual(paths,["site/data/latest.json"])

    def test_unknown_paths_and_untrusted_baseline_remain_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            finding = {"File":"site/data/llm_usage.json","RuleID":"test-rule","Secret":"canary"}
            with self.assertRaises(ValueError):
                quarantine(tmp,[finding],{"events":[]})
            path = Path(tmp) / "site/data/latest.json"; path.parent.mkdir(parents=True)
            payload = {"events":[{"event_id":"a"*12,"body":"canary"}]}
            path.write_text(json.dumps(payload))
            finding["File"] = "site/data/latest.json"
            with self.assertRaises(ValueError):
                quarantine(tmp,[finding],payload)
            self.assertEqual(json.loads(path.read_text()),payload)

    def test_cache_removal_preserves_usage_and_safe_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "site/data/candidate_cache.json"; path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"entries":{"bad":{"enrichment":"canary"},"good":{"status":"accepted"}},"runs":[{"calls":3}]}))
            finding = {"File":"site/data/candidate_cache.json","RuleID":"test-rule","Secret":"canary"}
            quarantine(tmp,[finding],{"events":[]})
            result = json.loads(path.read_text())
            self.assertEqual(list(result["entries"]),["good"])
            self.assertEqual(result["runs"],[{"calls":3}])
