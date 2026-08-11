#!/usr/bin/env python3
"""Persistent candidate decision cache for the DataHot update pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


TZ = timezone(timedelta(hours=8))
VALID_STATUSES = {"accepted", "rejected", "error"}


def _positive_int(value, default):
    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _enabled(value):
    return str(value if value is not None else "true").strip().lower() not in {
        "0", "false", "no", "off",
    }


def candidate_content_hash(item):
    """Hash stable feed metadata before expensive article fetching."""
    parts = [
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
    ]
    normalized = "\n".join(re.sub(r"\s+", " ", part).strip() for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _empty_stats():
    return {
        "lookups": 0,
        "hits": 0,
        "accepted_hits": 0,
        "rejected_hits": 0,
        "misses": 0,
        "expired": 0,
        "content_changed": 0,
        "version_invalidated": 0,
        "error_backoff_hits": 0,
        "error_retries": 0,
        "writes": 0,
    }


class CandidateCache:
    def __init__(self, path, environ=None, now_fn=None):
        self.path = Path(path)
        self.environ = environ if environ is not None else os.environ
        self.now_fn = now_fn or (lambda: datetime.now(TZ))
        self.enabled = _enabled(self.environ.get("CANDIDATE_CACHE_ENABLED", "true"))
        self.ttl_days = _positive_int(self.environ.get("CANDIDATE_CACHE_TTL_DAYS"), 21)
        self.error_ttl_hours = _positive_int(
            self.environ.get("CANDIDATE_CACHE_ERROR_TTL_HOURS"), 6
        )
        github_run = str(self.environ.get("GITHUB_RUN_ID", "")).strip()
        github_attempt = str(self.environ.get("GITHUB_RUN_ATTEMPT", "")).strip()
        self.run_id = (
            f"github-{github_run}-{github_attempt or '1'}"
            if github_run
            else f"local-{uuid.uuid4().hex[:12]}"
        )
        self.started_at = self.now_fn().isoformat()
        self.lock = threading.Lock()
        self.stats = _empty_stats()
        self._store = self._load()
        self._finalized = False

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("entries", {}), dict):
                raise ValueError("candidate cache root must be an object")
            return data
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return {"version": 1, "entries": {}, "runs": []}

    @staticmethod
    def _key(normalized_url):
        return hashlib.sha256(str(normalized_url).encode("utf-8")).hexdigest()

    def lookup(self, *, normalized_url, source_id, content_hash, model, rule_version):
        if not self.enabled:
            return None
        now = self.now_fn()
        with self.lock:
            self.stats["lookups"] += 1
            entry = self._store.get("entries", {}).get(self._key(normalized_url))
            if not isinstance(entry, dict):
                self.stats["misses"] += 1
                return None
            if entry.get("content_hash") != content_hash:
                self.stats["content_changed"] += 1
                self.stats["misses"] += 1
                return None
            if entry.get("model") != model or entry.get("rule_version") != rule_version:
                self.stats["version_invalidated"] += 1
                self.stats["misses"] += 1
                return None
            try:
                decided_at = datetime.fromisoformat(entry["decided_at"])
                if decided_at.tzinfo is None:
                    decided_at = decided_at.replace(tzinfo=TZ)
            except (KeyError, TypeError, ValueError):
                self.stats["expired"] += 1
                self.stats["misses"] += 1
                return None
            status = entry.get("status")
            ttl = (
                timedelta(hours=self.error_ttl_hours)
                if status == "error"
                else timedelta(days=self.ttl_days)
            )
            if now - decided_at >= ttl:
                if status == "error":
                    self.stats["error_retries"] += 1
                else:
                    self.stats["expired"] += 1
                self.stats["misses"] += 1
                return None
            if status == "error":
                self.stats["error_backoff_hits"] += 1
                self.stats["hits"] += 1
                return dict(entry)
            if status not in {"accepted", "rejected"}:
                self.stats["misses"] += 1
                return None
            self.stats["hits"] += 1
            self.stats[f"{status}_hits"] += 1
            return dict(entry)

    def remember(
        self,
        *,
        normalized_url,
        source_id,
        content_hash,
        status,
        model,
        rule_version,
        enrichment=None,
        error_type="",
    ):
        if not self.enabled:
            return
        if status not in VALID_STATUSES:
            raise ValueError(f"unsupported candidate status: {status}")
        entry = {
            "normalized_url": normalized_url,
            "source_id": str(source_id or "unknown"),
            "content_hash": content_hash,
            "status": status,
            "decided_at": self.now_fn().isoformat(),
            "model": str(model or ""),
            "rule_version": str(rule_version or ""),
        }
        if enrichment and status == "accepted":
            entry["enrichment"] = dict(enrichment)
        if error_type and status == "error":
            entry["error_type"] = str(error_type)[:80]
        with self.lock:
            self._store.setdefault("entries", {})[self._key(normalized_url)] = entry
            self.stats["writes"] += 1

    def _prune(self):
        now = self.now_fn()
        keep_for = timedelta(days=self.ttl_days + 7)
        entries = self._store.get("entries", {})
        kept = {}
        for key, entry in entries.items():
            try:
                decided_at = datetime.fromisoformat(entry["decided_at"])
                if decided_at.tzinfo is None:
                    decided_at = decided_at.replace(tzinfo=TZ)
            except (KeyError, TypeError, ValueError):
                continue
            if now - decided_at < keep_for:
                kept[key] = entry
        if len(kept) > 5000:
            newest = sorted(
                kept.items(), key=lambda pair: pair[1].get("decided_at", ""), reverse=True
            )[:5000]
            kept = dict(newest)
        self._store["entries"] = kept

    def _write_actions_summary(self, run):
        summary_path = str(self.environ.get("GITHUB_STEP_SUMMARY", "")).strip()
        if not summary_path:
            return
        hit_rate = (run["hits"] / run["lookups"] * 100) if run["lookups"] else 0
        text = (
            "\n## Candidate cache\n\n"
            f"- Lookups: **{run['lookups']}**\n"
            f"- Hits: **{run['hits']}** ({hit_rate:.1f}%)\n"
            f"- Misses: **{run['misses']}**\n"
            f"- Accepted / rejected hits: **{run['accepted_hits']} / {run['rejected_hits']}**\n"
            f"- Invalidated by content / version / TTL: **{run['content_changed']} / "
            f"{run['version_invalidated']} / {run['expired']}**\n"
        )
        Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(text)

    def finalize(self):
        with self.lock:
            if self._finalized:
                return self._store
            self._finalized = True
            if not self.enabled:
                return self._store
            self._prune()
            finished_at = self.now_fn().isoformat()
            run = {
                "run_id": self.run_id,
                "started_at": self.started_at,
                "finished_at": finished_at,
                **self.stats,
            }
            runs = self._store.setdefault("runs", [])
            runs[:] = [old for old in runs if old.get("run_id") != self.run_id]
            runs.append(run)
            self._store["runs"] = runs[-50:]
            self._store["last_stats"] = run
            self._store["updated_at"] = finished_at
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._store, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            self._write_actions_summary(run)
            return self._store

    def one_line_summary(self):
        with self.lock:
            lookups = self.stats["lookups"]
            hit_rate = self.stats["hits"] / lookups * 100 if lookups else 0
            return (
                f"[candidate-cache] lookups={lookups} hits={self.stats['hits']} "
                f"hit_rate={hit_rate:.1f}% misses={self.stats['misses']} "
                f"writes={self.stats['writes']}"
            )
