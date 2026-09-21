#!/usr/bin/env python3
"""Recover the current weekly brief using stored evidence and existing budgets.

No discovery, source fetch, translation, or forced regeneration is performed.
The normal weekly cache, retry ceiling, and daily token budget remain in force.
"""
import json
import os
from datetime import datetime, timezone


def main():
    # This smaller recovery budget also applies when the usual update budget is
    # larger. Configure it before importing run_update's usage tracker.
    try:
        configured = int(os.getenv("MAX_LLM_TOKENS_PER_RUN", "80000"))
    except ValueError:
        configured = 80000
    os.environ["MAX_LLM_TOKENS_PER_RUN"] = str(min(configured, 80000) if configured > 0 else 80000)
    os.environ["WEEKLY_BRIEF_FORCE"] = "false"
    import run_update

    events = json.loads((run_update.DATA / "latest.json").read_text())["events"]
    try:
        brief, status = run_update.generate_weekly_brief_for_events(
            events, run_update.load_llm_config(), datetime.now(timezone.utc),
        )
        print(f"[weekly-only] {status}; no source ingestion or article processing")
        if brief.get("fallback_reason"):
            print("[weekly-only] validation: " + json.dumps(
                brief["fallback_reason"], ensure_ascii=False,
            ))
    finally:
        run_update.LLM_USAGE.finalize()
        print(run_update.LLM_USAGE.one_line_summary())


if __name__ == "__main__":
    main()
