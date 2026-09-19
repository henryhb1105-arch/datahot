"""Keep source credentials out of both main and Pages without losing safe updates.

Raw scanner findings exist only in an ephemeral private directory. Public logs
contain rule/file/line/record IDs, never matches, secrets or article text.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scan_staged(root=ROOT, scanner=None):
    scanner = scanner or os.getenv("GITLEAKS_BIN") or str(root / "gitleaks")
    with tempfile.TemporaryDirectory(prefix="datahot-secret-scan-") as temporary:
        report = Path(temporary) / "findings.json"
        result = subprocess.run([scanner,"git","--pre-commit","--staged","--no-banner",
                                 "--report-format","json","--report-path",str(report),"."],
                                cwd=root, capture_output=True, text=True, timeout=180)
        if result.returncode not in (0,1):
            raise RuntimeError("staged secret scanner failed; data is not publishable")
        findings = json.loads(report.read_text()) if report.exists() else []
        if result.returncode == 1 and not findings:
            raise RuntimeError("scanner rejected content without a readable report")
        return findings


def contains_secret(value, secret):
    if not secret:
        return False
    serialized = json.dumps(value, ensure_ascii=False)
    return secret in serialized or secret in json.dumps(value, ensure_ascii=True) or (
        isinstance(value, dict) and any(contains_secret(v, secret) for v in value.values())
    ) or (isinstance(value, list) and any(contains_secret(v, secret) for v in value)) or (
        isinstance(value, str) and secret in value
    )


def quarantine(root, findings, baseline):
    root = Path(root)
    baseline_map = {event["event_id"]:event for event in baseline["events"]}
    changes, documents, rejected_urls = [], {}, set()
    allowed = {"site/data/latest.json", "site/data/candidate_cache.json", "site/data/cluster_cache.json"}
    for finding in findings:
        file = finding["File"]
        diagnostic = {"rule":finding["RuleID"],"file":file,"line":finding.get("StartLine")}
        if file not in allowed:
            raise ValueError("unhandled secret finding: " + json.dumps(diagnostic))
        if file not in documents:
            documents[file] = json.loads((root / file).read_text())
        document = documents[file]
        secret = finding.get("Secret") or ""
        matched = False
        if file.endswith("/latest.json"):
            events = []
            for event in document["events"]:
                if not contains_secret(event, secret):
                    events.append(event); continue
                matched = True
                identifier = event["event_id"]
                rejected_urls.update(i.get("link", "") for i in event.get("items", []))
                restored = baseline_map.get(identifier)
                if restored and contains_secret(restored, secret):
                    raise ValueError("baseline is not a safe replacement: " + json.dumps(diagnostic))
                if restored:
                    events.append(restored)
                changes.append({**diagnostic,"record_id":identifier,"action":"restore_baseline" if restored else "remove_new_candidate"})
            document["events"] = events
            ids = {e["event_id"] for e in events}
            document["top"] = [identifier for identifier in document.get("top", []) if identifier in ids]
        else:
            for key, entry in list(document["entries"].items()):
                if contains_secret(entry, secret):
                    matched = True
                    del document["entries"][key]
                    changes.append({**diagnostic,"record_id":key,"action":"remove_unsafe_cache_entry"})
        # Duplicate findings may refer to an entity already removed by an earlier
        # finding. A clean document confirms removal; otherwise fail closed.
        if not matched and contains_secret(document, secret):
            raise ValueError("finding is outside a supported candidate record: " + json.dumps(diagnostic))
    cache_name = "site/data/candidate_cache.json"
    cache_path = root / cache_name
    if rejected_urls and cache_path.exists():
        cache = documents.setdefault(cache_name, json.loads(cache_path.read_text()))
        for entry in cache.get("entries", {}).values():
            if entry.get("normalized_url") in rejected_urls:
                entry.pop("enrichment", None)
                entry["status"] = "rejected"
                entry["quarantine_reason"] = "secret_scan"
                entry["decided_at"] = datetime.now(timezone.utc).isoformat()
    for file, document in documents.items():
        path = root / file
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n")
        os.replace(temporary, path)
    return changes, list(documents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    args = parser.parse_args()
    findings = scan_staged()
    if not findings:
        print("[secret-scan] staged content passed")
        return
    baseline = json.loads(args.baseline.read_text())
    changes, paths = quarantine(ROOT, findings, baseline)
    if paths:
        subprocess.run(["git","add","--",*paths], cwd=ROOT, check=True)
    remaining = scan_staged()
    if remaining:
        safe = [{"rule":f["RuleID"],"file":f["File"],"line":f.get("StartLine")} for f in remaining]
        raise RuntimeError("secret findings remain; stopping: " + json.dumps(safe))
    print("[secret-scan] quarantined source records: " + json.dumps(changes, ensure_ascii=False))


if __name__ == "__main__":
    main()
