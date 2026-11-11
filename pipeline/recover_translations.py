#!/usr/bin/env python3
"""Manually recover retained translations without collection or weekly generation."""
import copy
import json
import os
from datetime import datetime, timezone


def recover(payload, runtime, cfg, *, now=None, source_configs=None):
    if not all(cfg):
        raise RuntimeError("Translation recovery requires complete LLM configuration")
    now = now or datetime.now(timezone.utc)
    result = copy.deepcopy(payload)
    events = result["events"]
    ids = [e["event_id"] for e in events]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate event IDs in recovery baseline")
    report = {"metadata": [], "bodies": []}
    failed = False
    # Each article is attempted at most once per phase. Existing functions retain
    # their cooldown, source quality, Chinese validation and token reservations.
    candidates = [e for e in events if runtime.is_pending_original(e)]
    for start in range(0, len(candidates), 8):
        if not runtime.LLM_USAGE.can_call(1):
            break
        summary = runtime.backfill_event_metadata(
            candidates[start:start + 8], cfg, now=now, limit=8,
        )
        report["metadata"].append(summary)
        print("[recovery-metadata]", json.dumps(summary), flush=True)
        if summary.get("failed") or summary.get("deferred_budget"):
            failed = bool(summary.get("failed"))
            break

    # Only untranslated retained originals; leave editorial excerpts and already
    # translated historical articles alone. Newest articles are stored first.
    originals = [e for e in events if (
        e.get("content_mode") == "original"
        and e.get("source_language") not in ("zh", None, "unknown")
        and e.get("translation_status") != "complete"
        and e.get("enrichment_status") != "rejected"
    )]
    for event in ([] if failed else originals):
        if (not runtime.LLM_USAGE.can_call(1)
                or runtime.LLM_USAGE.snapshot()["failures"]):
            break
        summary = runtime.backfill_structured_content(
            [event], cfg, now=now, limit=1, lookback_days=90,
            source_configs=source_configs,
        )
        report["bodies"].append(summary)
        print("[recovery-body]", event["event_id"], json.dumps(summary), flush=True)
        if summary.get("failed"):
            break
        # generate_event_body catches provider errors and keeps the original.
        if runtime.LLM_USAGE.snapshot()["failures"]:
            break
    if [e["event_id"] for e in events] != ids:
        raise RuntimeError("Recovery changed event identity or ordering")
    usage = runtime.LLM_USAGE.snapshot()
    if usage.get("calls") and usage["failures"] == usage["calls"]:
        raise RuntimeError("All recovery model calls failed; refusing to publish a false recovery")
    runtime.repair_content_metadata(events)
    for event in events:
        runtime.recalc_event_heat(event, reference_time=now)
    result["top"] = [e["event_id"] for e in runtime.rank_hot_events(
        events, limit=3, source_cap=2, reference_time=now,
    )]
    result["generated_at"] = now.astimezone(runtime.TZ).isoformat()
    result["translation_recovery"] = report
    return result


def main():
    # Preserve the workflow's existing ceilings, including for local invocation.
    os.environ.setdefault("MAX_LLM_TOKENS_PER_RUN", "160000")
    os.environ.setdefault("MAX_LLM_TOKENS_PER_DAY", "1000000")
    import run_update as runtime
    path = runtime.DATA / "latest.json"
    sources = json.loads((runtime.ROOT / "pipeline/sources.json").read_text())
    try:
        result = recover(
            json.loads(path.read_text()), runtime, runtime.load_llm_config(),
            source_configs={s["name"]: s for s in sources},
        )
        temp = path.with_suffix(".recovery.tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
        temp.replace(path)
    finally:
        runtime.LLM_USAGE.finalize()
        print(runtime.LLM_USAGE.one_line_summary(), flush=True)


if __name__ == "__main__":
    main()
