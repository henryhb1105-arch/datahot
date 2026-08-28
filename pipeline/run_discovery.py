#!/usr/bin/env python3
"""CLI entrypoint for DataHot's internal shadow discovery pass."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from discovery.scout import run_scout


ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "pipeline" / "discovery_state"


def main():
    parser = argparse.ArgumentParser(description="Run the DataHot shadow article/source scout")
    parser.add_argument("--force", action="store_true", help="ignore the frequency gate")
    parser.add_argument("--state", type=Path, default=STATE_DIR / "scout.json")
    parser.add_argument("--report", type=Path, default=STATE_DIR / "latest_report.md")
    args = parser.parse_args()
    payload = run_scout(
        sources_path=ROOT / "pipeline" / "sources.json",
        latest_path=ROOT / "site" / "data" / "latest.json",
        source_status_path=ROOT / "site" / "data" / "sources_status.json",
        queries_path=ROOT / "pipeline" / "discovery_queries.json",
        state_path=args.state,
        report_path=args.report,
        force=args.force,
    )
    status = payload.get("run_status", "unknown")
    stats = payload.get("stats") or {}
    print(
        f"[discovery] {status} | articles={stats.get('article_candidates', 0)} "
        f"sources={stats.get('source_candidates', 0)} probation={stats.get('probation_sources', 0)}"
    )
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and args.report.exists() and status != "frequency_gate":
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("\n" + args.report.read_text(encoding="utf-8") + "\n")


if __name__ == "__main__":
    main()
