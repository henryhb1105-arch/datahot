"""Explicit, conservative original-first fallback. Never invent editorial output."""
import json
from functools import lru_cache
from pathlib import Path

TRUSTED_TIERS = frozenset({"official_high", "official_targeted", "media_targeted", "engineering_targeted"})

@lru_cache(maxsize=1)
def trusted_sources():
    return frozenset(s["name"] for s in json.loads(
        (Path(__file__).parent / "sources.json").read_text()
    ) if s.get("enabled", True) and s.get("tier") in TRUSTED_TIERS)

def is_pending_original(event):
    status = event.get("enrichment_status")
    if status in {"complete", "rejected"}:
        return False
    primary = (event.get("items") or [{}])[0]
    if primary.get("source") not in trusted_sources():
        return False
    if status == "pending":
        return True
    # Migrate only evidenced failed legacy metadata, never arbitrary untranslated
    # records. Original titles and neutral scores were preserved by ingestion.
    report = event.get("content_parse") or {}
    failed = ((report.get("metadata_translation") or {}).get("status") == "provider_error"
              or report.get("translation_status") == "failed")
    return bool(failed and not event.get("reason")
                and event.get("zh_title") == primary.get("title")
                and event.get("importance", 50) == 50)
