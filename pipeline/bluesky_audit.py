#!/usr/bin/env python3
"""Read-only Bluesky distribution audit for DataHot posts."""

from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import growth_share


DISCOVER_FEED = (
    "at://did:plc:z72i7hdynmk6r22z27h6tvur/"
    "app.bsky.feed.generator/whats-hot"
)
SEARCH_QUERIES = {
    "brand": "DataHot",
    "domain": "datahot.xiahongbin.com",
    "data_engineering": "DataEngineering",
    "ai_agents": "AIAgents",
    "analytics": "Analytics",
}


def _own_ranks(posts, did):
    return [
        rank
        for rank, post in enumerate(posts, start=1)
        if (post.get("author") or {}).get("did") == did
        or str(post.get("uri") or "").startswith(f"at://{did}/")
    ]


def _safe_query(url, *, token):
    """Run one query without leaking response bodies or credentials on failure."""
    try:
        return growth_share._json_request(url, token=token), ""
    except (HTTPError, URLError, TimeoutError) as error:
        return {}, error.__class__.__name__


def audit_distribution(*, handle, password):
    """Authenticate, then inspect search and Discover without writing social state."""
    session = growth_share._json_request(
        f"{growth_share.BSKY_API}/com.atproto.server.createSession",
        payload={"identifier": handle.strip().lower(), "password": password},
    )
    did = session["did"]
    token = session["accessJwt"]
    search = {}

    for label, query in SEARCH_QUERIES.items():
        url = f"{growth_share.BSKY_API}/app.bsky.feed.searchPosts?" + urlencode({
            "q": query,
            "sort": "latest",
            "limit": 100,
        })
        payload, error = _safe_query(url, token=token)
        posts = payload.get("posts") or []
        ranks = _own_ranks(posts, did)
        search[label] = {
            "ok": not error,
            "error": error or None,
            "query": query,
            "results_checked": len(posts),
            "hits_total": payload.get("hitsTotal"),
            "own_post_count": len(ranks),
            "own_ranks": ranks,
        }

    discover_url = f"{growth_share.BSKY_API}/app.bsky.feed.getFeed?" + urlencode({
        "feed": DISCOVER_FEED,
        "limit": 100,
    })
    discover_payload, discover_error = _safe_query(discover_url, token=token)
    discover_posts = [
        item.get("post") or {}
        for item in discover_payload.get("feed") or []
        if isinstance(item, dict)
    ]
    discover_ranks = _own_ranks(discover_posts, did)
    successful_checks = sum(item["ok"] for item in search.values()) + (not discover_error)

    return {
        "status": "audited" if successful_checks else "unavailable",
        "observed_at": datetime.now(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"),
        "account": {"handle": handle.strip().lower(), "did": did},
        "read_only": True,
        "successful_checks": successful_checks,
        "search_indexed": any(
            search[label]["own_post_count"] > 0 for label in ("brand", "domain")
        ),
        "topic_search_presence": any(
            search[label]["own_post_count"] > 0
            for label in ("data_engineering", "ai_agents", "analytics")
        ),
        "search": search,
        "discover": {
            "ok": not discover_error,
            "error": discover_error or None,
            "feed": DISCOVER_FEED,
            "results_checked": len(discover_posts),
            "own_post_count": len(discover_ranks),
            "own_ranks": discover_ranks,
        },
    }


def main():
    handle = os.environ.get("BSKY_HANDLE", "").strip()
    password = os.environ.get("BSKY_APP_PASSWORD", "")
    if not handle or not password:
        raise SystemExit("BSKY_HANDLE and BSKY_APP_PASSWORD are required")
    report = audit_distribution(handle=handle, password=password)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["successful_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
