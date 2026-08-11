#!/usr/bin/env python3
"""LLM usage telemetry and budget guardrails for DataHot.

The tracker intentionally stores metadata and token counts only. Prompt and
response bodies are never persisted.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))


class LLMBudgetExceeded(RuntimeError):
    """Raised before an API request when a configured budget is exhausted."""


def _positive_int(value, default=0):
    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _empty_totals():
    return {
        "calls": 0,
        "failures": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "accounted_tokens": 0,
    }


def _add_totals(target, values, sign=1):
    for key in _empty_totals():
        target[key] = max(0, int(target.get(key, 0)) + sign * int(values.get(key, 0)))


class LLMUsageTracker:
    def __init__(self, path, environ=None, now_fn=None):
        self.path = Path(path)
        self.environ = environ if environ is not None else os.environ
        self.now_fn = now_fn or (lambda: datetime.now(TZ))
        self.lock = threading.Lock()
        self.started_at = self.now_fn().isoformat()
        github_run = str(self.environ.get("GITHUB_RUN_ID", "")).strip()
        github_attempt = str(self.environ.get("GITHUB_RUN_ATTEMPT", "")).strip()
        self.run_id = (
            f"github-{github_run}-{github_attempt or '1'}"
            if github_run
            else f"local-{uuid.uuid4().hex[:12]}"
        )
        self.max_run_tokens = _positive_int(self.environ.get("MAX_LLM_TOKENS_PER_RUN"))
        self.max_daily_tokens = _positive_int(self.environ.get("MAX_LLM_TOKENS_PER_DAY"))
        self.max_compile_events = _positive_int(self.environ.get("MAX_COMPILE_EVENTS_PER_RUN"))
        self.calls = []
        self.totals = _empty_totals()
        self.by_purpose = {}
        self.by_source = {}
        self.compile_items = set()
        self.reserved_tokens = 0
        self.skipped = {"budget": 0, "compile_limit": 0}
        self._finalized = False
        self._history = self._load_history()
        today = self.now_fn().date().isoformat()
        self._daily_tokens_before_run = int(
            self._history.get("daily", {}).get(today, {}).get(
                "accounted_tokens",
                self._history.get("daily", {}).get(today, {}).get("total_tokens", 0),
            )
        )

    def _load_history(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def before_call(self, purpose="other", item_id="", estimated_tokens=0):
        purpose = purpose or "other"
        estimated_tokens = max(0, int(estimated_tokens or 0))
        with self.lock:
            projected_run = self.totals["accounted_tokens"] + self.reserved_tokens + estimated_tokens
            if self.max_run_tokens and projected_run > self.max_run_tokens:
                self.skipped["budget"] += 1
                raise LLMBudgetExceeded(
                    f"run token budget would be exceeded ({projected_run}/{self.max_run_tokens})"
                )
            projected_daily = self._daily_tokens_before_run + projected_run
            if self.max_daily_tokens and projected_daily > self.max_daily_tokens:
                self.skipped["budget"] += 1
                raise LLMBudgetExceeded(
                    f"daily token budget would be exceeded ({projected_daily}/{self.max_daily_tokens})"
                )
            if purpose == "compile" and self.max_compile_events:
                stable_id = str(item_id or "unknown")
                if stable_id not in self.compile_items:
                    if len(self.compile_items) >= self.max_compile_events:
                        self.skipped["compile_limit"] += 1
                        raise LLMBudgetExceeded(
                            f"compile event budget reached ({self.max_compile_events})"
                        )
                    self.compile_items.add(stable_id)
            self.reserved_tokens += estimated_tokens
        return estimated_tokens

    def record(
        self,
        *,
        model,
        purpose="other",
        source="",
        item_id="",
        prompt_chars=0,
        response_chars=0,
        max_tokens=None,
        usage=None,
        success=True,
        error_type="",
        reserved_tokens=0,
    ):
        usage = usage if isinstance(usage, dict) else {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        accounted_tokens = total_tokens if usage else max(0, int(reserved_tokens or 0))
        purpose = purpose or "other"
        source = source or "unknown"
        call = {
            "at": self.now_fn().isoformat(),
            "model": str(model or ""),
            "purpose": purpose,
            "source": source,
            "item_id": str(item_id or ""),
            "success": bool(success),
            "usage_reported": bool(usage),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "accounted_tokens": accounted_tokens,
            "prompt_chars": int(prompt_chars or 0),
            "response_chars": int(response_chars or 0),
        }
        if max_tokens:
            call["max_tokens"] = int(max_tokens)
        if error_type:
            call["error_type"] = str(error_type)[:80]

        delta = {
            "calls": 1,
            "failures": 0 if success else 1,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "accounted_tokens": accounted_tokens,
        }
        with self.lock:
            self.reserved_tokens = max(0, self.reserved_tokens - int(reserved_tokens or 0))
            call["index"] = len(self.calls) + 1
            self.calls.append(call)
            _add_totals(self.totals, delta)
            purpose_totals = self.by_purpose.setdefault(purpose, _empty_totals())
            source_totals = self.by_source.setdefault(source, _empty_totals())
            _add_totals(purpose_totals, delta)
            _add_totals(source_totals, delta)

    def snapshot(self):
        with self.lock:
            return {
                "run_id": self.run_id,
                "started_at": self.started_at,
                "finished_at": self.now_fn().isoformat(),
                **self.totals,
                "by_purpose": self.by_purpose,
                "by_source": self.by_source,
                "skipped": dict(self.skipped),
                "budgets": {
                    "max_run_tokens": self.max_run_tokens,
                    "max_daily_tokens": self.max_daily_tokens,
                    "max_compile_events": self.max_compile_events,
                },
                "calls_detail": list(self.calls),
            }

    def _update_daily(self, store, run, previous_run=None):
        day = self.now_fn().date().isoformat()
        daily = store.setdefault("daily", {})
        rec = daily.setdefault(day, {**_empty_totals(), "by_purpose": {}, "by_source": {}})
        if previous_run:
            _add_totals(rec, previous_run, sign=-1)
            for group_name in ("by_purpose", "by_source"):
                for key, values in previous_run.get(group_name, {}).items():
                    target = rec.setdefault(group_name, {}).setdefault(key, _empty_totals())
                    _add_totals(target, values, sign=-1)
        _add_totals(rec, run)
        for group_name in ("by_purpose", "by_source"):
            for key, values in run.get(group_name, {}).items():
                target = rec.setdefault(group_name, {}).setdefault(key, _empty_totals())
                _add_totals(target, values)
        rec["updated_at"] = run["finished_at"]

    def _prune(self, store):
        daily = store.get("daily", {})
        keep_days = sorted(daily)[-45:]
        store["daily"] = {day: daily[day] for day in keep_days}
        runs = sorted(store.get("runs", []), key=lambda r: r.get("started_at", ""))[-50:]
        remaining_calls = 2000
        for run in reversed(runs):
            calls = run.get("calls_detail", [])
            if len(calls) > remaining_calls:
                run["calls_detail"] = calls[-remaining_calls:] if remaining_calls else []
            remaining_calls = max(0, remaining_calls - len(run.get("calls_detail", [])))
        store["runs"] = runs

    def _write_actions_summary(self, run):
        summary_path = str(self.environ.get("GITHUB_STEP_SUMMARY", "")).strip()
        if not summary_path:
            return
        purpose_rows = "\n".join(
            f"| {name} | {values['calls']} | {values['total_tokens']} |"
            for name, values in sorted(run["by_purpose"].items())
        ) or "| 无调用 | 0 | 0 |"
        text = (
            "\n## DeepSeek usage\n\n"
            f"- Run: `{run['run_id']}`\n"
            f"- Calls: **{run['calls']}**（失败 {run['failures']}）\n"
            f"- Prompt tokens: **{run['prompt_tokens']}**\n"
            f"- Completion tokens: **{run['completion_tokens']}**\n"
            f"- Total tokens: **{run['total_tokens']}**\n"
            f"- Budget accounted tokens: **{run['accounted_tokens']}**\n"
            f"- Budget skips: **{run['skipped']['budget']}**；全文上限跳过：**{run['skipped']['compile_limit']}**\n\n"
            "| 用途 | 调用数 | Token |\n|---|---:|---:|\n"
            f"{purpose_rows}\n"
        )
        Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(text)

    def finalize(self):
        with self.lock:
            if self._finalized:
                return self._history
            self._finalized = True
        run = self.snapshot()
        store = self._load_history()
        store.setdefault("version", 1)
        runs = store.setdefault("runs", [])
        previous = next((r for r in runs if r.get("run_id") == self.run_id), None)
        runs[:] = [r for r in runs if r.get("run_id") != self.run_id]
        runs.append(run)
        self._update_daily(store, run, previous)
        self._prune(store)
        store["updated_at"] = run["finished_at"]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        self._write_actions_summary(run)
        self._history = store
        return store

    def one_line_summary(self):
        snap = self.snapshot()
        return (
            f"[llm-usage] calls={snap['calls']} failures={snap['failures']} "
            f"prompt={snap['prompt_tokens']} completion={snap['completion_tokens']} "
            f"total={snap['total_tokens']} accounted={snap['accounted_tokens']} "
            f"skips={sum(snap['skipped'].values())}"
        )
