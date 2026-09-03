"""Shared retention policy for generated data and release validation."""

from datetime import datetime, timezone

from product_cases import product_case_event_ids


PROTECTED_EVENT_IDS = (
    frozenset({"65c35101abc1", "dfb9071b69e0"})
    | product_case_event_ids()
)


def parse_event_time(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def event_recency_time(event):
    """Use the newest known event timestamp for retention decisions.

    ``first_seen`` keeps newly discovered older articles visible, while a newer
    ``published`` value keeps rolling release-note events alive after updates.
    """
    timestamps = [
        parsed
        for parsed in (
            parse_event_time(event.get("first_seen")),
            parse_event_time(event.get("published")),
        )
        if parsed is not None
    ]
    return max(timestamps) if timestamps else None


def should_retain_event(event, *, cutoff):
    """Return whether an event belongs in the next generated catalog."""
    if str(event.get("event_id") or "") in PROTECTED_EVENT_IDS:
        return True
    if event.get("shelf") == "evergreen":
        return True
    observed = event_recency_time(event)
    return bool(observed and observed > cutoff.astimezone(timezone.utc))
