import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER = os.environ.get("GITLEAKS_BIN") or shutil.which("gitleaks")
if not SCANNER and (ROOT / "gitleaks").exists():
    SCANNER = str(ROOT / "gitleaks")


@unittest.skipUnless(SCANNER, "Gitleaks binary is required for integration checks")
class GitleaksBoundaryTests(unittest.TestCase):
    def scan_header(self, header, value):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "example.sh"
            fixture.write_text("curl https://example.test -H '" + header + ": " + value + "'\n")
            result = subprocess.run([
                SCANNER, "dir", "--config", str(ROOT / ".gitleaks.toml"),
                "--redact", "--no-banner", directory,
            ], capture_output=True, text=True, timeout=30)
            self.assertIn(result.returncode, (0, 1), "scanner could not run")
            return result.returncode

    def test_documentation_literals_are_accepted(self):
        self.assertEqual(self.scan_header("X-ClickHouse-Key", "YOUR-PASSWORD"), 0)
        self.assertEqual(self.scan_header("Authorization", "Bearer YOUR_COHERE_API_KEY"), 0)

    def test_arbitrary_credentials_and_extended_placeholders_are_blocked(self):
        for value in (uuid.uuid4().hex, "YOUR-PASSWORD-" + uuid.uuid4().hex):
            with self.subTest(kind="nonliteral ClickHouse credential"):
                self.assertEqual(self.scan_header("X-ClickHouse-Key", value), 1)
        self.assertEqual(self.scan_header("Authorization", "Bearer " + uuid.uuid4().hex), 1)


class DataWritebackBoundaryTests(unittest.TestCase):
    def test_staged_content_is_scanned_before_commit(self):
        workflow = (ROOT / ".github/workflows/update.yml").read_text()
        stage = workflow.index("git add -- site/data")
        scan = workflow.index("./gitleaks git --pre-commit --staged --redact .")
        commit = workflow.index('git commit -m "chore:')
        self.assertLess(stage, scan)
        self.assertLess(scan, commit)

