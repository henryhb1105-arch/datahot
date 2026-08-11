#!/usr/bin/env python3
"""Persistent cache for LLM event-clustering decisions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


TZ = timezone(timedelta(hours=8))


def cluster_pair_key(left, right):
    def normalize(value):
        return re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    pair = sorted((normalize(left), normalize(right)))
    return hashlib.sha256("\0".join(pair).encode("utf-8")).hexdigest()


class ClusterDecisionCache:
    def __init__(self, path, environ=None, now_fn=None):
        self.path = Path(path)
        self.environ = environ if environ is not None else os.environ
        self.now_fn = now_fn or (lambda: datetime.now(TZ))
        try:
            self.ttl_days = max(1, int(self.environ.get("CLUSTER_CACHE_TTL_DAYS", "14")))
        except ValueError:
            self.ttl_days = 14
        self.lock = threading.Lock()
        self.stats = {"hits": 0, "misses": 0, "writes": 0, "expired": 0}
        self._store = self._load()
        self._finalized = False

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("entries", {}), dict):
                raise ValueError("invalid cluster cache")
            return data
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return {"version": 1, "entries": {}}

    def lookup(self, pair_key, version):
        with self.lock:
            entry = self._store.get("entries", {}).get(pair_key)
            if not isinstance(entry, dict) or entry.get("version") != version:
                self.stats["misses"] += 1
                return None
            try:
                decided_at = datetime.fromisoformat(entry["decided_at"])
                if decided_at.tzinfo is None:
                    decided_at = decided_at.replace(tzinfo=TZ)
            except (KeyError, TypeError, ValueError):
                self.stats["misses"] += 1
                return None
            if self.now_fn() - decided_at >= timedelta(days=self.ttl_days):
                self.stats["expired"] += 1
                self.stats["misses"] += 1
                return None
            self.stats["hits"] += 1
            return bool(entry.get("same"))

    def remember(self, pair_key, version, same):
        with self.lock:
            self._store.setdefault("entries", {})[pair_key] = {
                "same": bool(same),
                "version": version,
                "decided_at": self.now_fn().isoformat(),
            }
            self.stats["writes"] += 1

    def finalize(self):
        with self.lock:
            if self._finalized:
                return self._store
            self._finalized = True
            cutoff = self.now_fn() - timedelta(days=self.ttl_days + 7)
            kept = {}
            for key, entry in self._store.get("entries", {}).items():
                try:
                    decided_at = datetime.fromisoformat(entry["decided_at"])
                    if decided_at.tzinfo is None:
                        decided_at = decided_at.replace(tzinfo=TZ)
                except (KeyError, TypeError, ValueError):
                    continue
                if decided_at >= cutoff:
                    kept[key] = entry
            if len(kept) > 5000:
                newest = sorted(
                    kept.items(), key=lambda pair: pair[1].get("decided_at", ""), reverse=True
                )[:5000]
                kept = dict(newest)
            self._store["entries"] = kept
            self._store["updated_at"] = self.now_fn().isoformat()
            self._store["last_stats"] = dict(self.stats)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._store, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            return self._store

    def one_line_summary(self):
        return (
            f"[cluster-cache] hits={self.stats['hits']} misses={self.stats['misses']} "
            f"writes={self.stats['writes']} expired={self.stats['expired']}"
        )
