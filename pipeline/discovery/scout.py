#!/usr/bin/env python3
"""Discover articles and source domains without publishing them.

The scout deliberately maximizes recall and writes only an internal shadow
registry.  Promotion into ``pipeline/sources.json`` remains an editorial act.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCHEMA_VERSION = 1
DISCOVERY_POLICY_VERSION = "source-scout-v3-data-specific-hn"
LIFECYCLE_STATES = (
    "DISCOVERED", "PROBATION", "ACTIVE", "DEGRADED", "PAUSED",
)
TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "ref", "source")
DEFAULT_BLOCKED_HOSTS = {
    "google.com", "www.google.com", "bing.com", "www.bing.com",
    "news.google.com", "reddit.com", "www.reddit.com", "quora.com",
    "www.quora.com", "wikipedia.org", "www.wikipedia.org",
}
NON_SOURCE_HOSTS = {
    "github.com", "www.github.com", "linkedin.com", "www.linkedin.com",
    "youtube.com", "www.youtube.com", "youtu.be", "x.com", "www.x.com",
    "twitter.com", "www.twitter.com", "claude.ai", "www.claude.ai",
}
EDITORIAL_PATH_MARKERS = (
    "/blog/", "/blogs/", "/research/", "/insights/", "/insight/",
    "/news/", "/article/", "/articles/", "/post/", "/posts/", "/report/",
    "/reports/", "/publication/", "/publications/",
)
DISCOVERY_TERMS = (
    "data", "database", "analytics", "warehouse", "lakehouse", "sql",
    "business intelligence", "semantic layer", "etl", "elt", "dbt",
    "数据", "分析", "数仓", "湖仓", "语义层",
    "可视化", "报表", "people analytics", "workforce analytics",
)
UA = {
    "User-Agent": "DataHot-Discovery/1.0 (+https://datahot.xiahongbin.com)",
    "Accept": "application/json,text/html;q=0.8,*/*;q=0.5",
}


def _now_utc(now=None):
    value = now or datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _truthy(value, default=False):
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_url(value):
    """Normalize an HTTP URL for cross-provider de-duplication."""
    try:
        parsed = urllib.parse.urlparse(str(value or "").strip())
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return ""
    if port and not (
        parsed.scheme.lower() == "http" and port == 80
    ) and not (
        parsed.scheme.lower() == "https" and port == 443
    ):
        host = f"{host}:{port}"
    query = [
        (key, item)
        for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith(TRACKING_PREFIXES)
    ]
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urllib.parse.urlunparse((
        parsed.scheme.lower(), host, path, "", urllib.parse.urlencode(query), "",
    ))


def url_host(value):
    normalized = normalize_url(value)
    if not normalized:
        return ""
    return (urllib.parse.urlparse(normalized).hostname or "").lower()


def _read_json(path, fallback):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback
    return payload


def _write_json_atomic(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=target.parent,
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def known_source_hosts(sources):
    hosts = set()
    for source in sources if isinstance(sources, list) else []:
        values = [source.get("url"), source.get("homepage"), source.get("base")]
        values.extend(source.get("urls") or [])
        for value in values:
            host = url_host(value)
            if host:
                hosts.add(host)
                if host.startswith("www."):
                    hosts.add(host[4:])
    return hosts


def catalog_urls(latest):
    return {
        normalized
        for event in (latest.get("events") or [])
        for item in (event.get("items") or [])
        if (normalized := normalize_url(item.get("link")))
    }


def extract_openai_sources(payload):
    """Extract consulted URLs from Responses API web-search output."""
    found = []
    seen = set()

    def add(source):
        if not isinstance(source, dict):
            return
        url = normalize_url(source.get("url"))
        if not url or url in seen:
            return
        seen.add(url)
        found.append({
            "url": url,
            "title": str(source.get("title") or "").strip()[:300],
        })

    for output in payload.get("output") or []:
        if not isinstance(output, dict):
            continue
        action = output.get("action") or {}
        for source in action.get("sources") or []:
            add(source)
        for content in output.get("content") or []:
            for annotation in content.get("annotations") or []:
                add(annotation)
    return found


class OpenAIWebSearchProvider:
    """Small standard-library client for the official Responses web search."""

    def __init__(self, api_key, *, model="gpt-5.6", timeout=120, opener=None):
        self.api_key = str(api_key or "")
        self.model = str(model or "gpt-5.6")
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen

    def search(self, query, *, blocked_hosts=None):
        filters = {}
        blocked = sorted({host for host in (blocked_hosts or []) if host})[:100]
        if blocked:
            filters["blocked_domains"] = blocked
        tool = {"type": "web_search"}
        if filters:
            tool["filters"] = filters
        payload = {
            "model": self.model,
            "reasoning": {"effort": "low"},
            "tools": [tool],
            "tool_choice": "required",
            "include": ["web_search_call.action.sources"],
            "input": query,
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self.opener(request, timeout=self.timeout) as response:
            return extract_openai_sources(json.loads(response.read()))


def _fetch_json(url, timeout=20):
    last_error = None
    for _attempt in range(2):
        request = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
    raise last_error


def discover_hn(*, max_ids=45, minimum_score=20, fetch_json=None):
    """Read official HN top/best/new lists, then apply a local broad filter."""
    getter = fetch_json or _fetch_json
    roots = {
        "top": "https://hacker-news.firebaseio.com/v0/topstories.json",
        "best": "https://hacker-news.firebaseio.com/v0/beststories.json",
        "new": "https://hacker-news.firebaseio.com/v0/newstories.json",
    }
    id_channels = {}
    for channel, url in roots.items():
        try:
            story_ids = getter(url) or []
        except Exception:
            continue
        for item_id in story_ids[:max_ids]:
            id_channels.setdefault(int(item_id), set()).add(channel)
    if not id_channels:
        raise urllib.error.URLError("all Hacker News list endpoints failed")

    def fetch_item(item_id):
        try:
            return getter(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json")
        except Exception:
            return None

    candidates = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        items = list(pool.map(fetch_item, sorted(id_channels)))
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "story":
            continue
        title = str(item.get("title") or "").strip()
        url = normalize_url(item.get("url"))
        score = max(0, int(item.get("score") or 0))
        haystack = f"{title} {url}".casefold()
        if not url or score < minimum_score:
            continue
        if not any(term in haystack for term in DISCOVERY_TERMS):
            continue
        candidates.append({
            "url": url,
            "title": title[:300],
            "channel": "hn",
            "provider_refs": [f"hn:{name}" for name in sorted(id_channels.get(int(item["id"]), []))],
            "signal": score,
        })
    return candidates


def _walk_links(value):
    if isinstance(value, dict):
        href = value.get("href")
        if isinstance(href, str):
            yield href
        for child in value.values():
            yield from _walk_links(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_links(child)


def discover_link_graph(latest, known_hosts, *, minimum_mentions=2):
    """Find domains repeatedly cited by already accepted high-quality articles."""
    evidence = {}
    for event in latest.get("events") or []:
        quality = event.get("quality_score", event.get("importance", 0))
        try:
            quality = int(quality or 0)
        except (TypeError, ValueError):
            quality = 0
        if quality < 70:
            continue
        event_id = str(event.get("event_id") or "")
        primary_hosts = {url_host(item.get("link")) for item in event.get("items") or []}
        for raw_url in _walk_links(event.get("content_blocks") or []):
            url = normalize_url(raw_url)
            host = url_host(url)
            if not url or not host or host in primary_hosts or host in known_hosts:
                continue
            if host in DEFAULT_BLOCKED_HOSTS:
                continue
            path = (urllib.parse.urlparse(url).path or "/").casefold()
            if not (
                any(marker in path for marker in EDITORIAL_PATH_MARKERS)
                or path.endswith(".pdf")
            ):
                continue
            row = evidence.setdefault(host, {"urls": {}, "events": set()})
            row["urls"].setdefault(url, 0)
            row["urls"][url] += 1
            row["events"].add(event_id)

    candidates = []
    for host, row in evidence.items():
        if len(row["events"]) < minimum_mentions:
            continue
        representative = sorted(
            row["urls"], key=lambda url: (-row["urls"][url], url),
        )[0]
        candidates.append({
            "url": representative,
            "title": host,
            "channel": "accepted_link_graph",
            "provider_refs": [f"accepted:{event_id}" for event_id in sorted(row["events"])],
            "signal": len(row["events"]),
        })
    return candidates


def _merge_raw_candidates(rows):
    merged = {}
    for row in rows:
        url = normalize_url(row.get("url"))
        host = url_host(url)
        base_host = host[4:] if host.startswith("www.") else host
        if (
            not url or not host or host in DEFAULT_BLOCKED_HOSTS
            or host in NON_SOURCE_HOSTS or base_host in NON_SOURCE_HOSTS
        ):
            continue
        target = merged.setdefault(url, {
            "candidate_id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
            "url": url,
            "title": "",
            "host": host,
            "channels": [],
            "query_ids": [],
            "provider_refs": [],
            "signal": 0,
        })
        if len(str(row.get("title") or "")) > len(target["title"]):
            target["title"] = str(row.get("title") or "")[:300]
        for field, value in (
            ("channels", row.get("channel")),
            ("query_ids", row.get("query_id")),
        ):
            if value and value not in target[field]:
                target[field].append(value)
        target["provider_refs"] = list(dict.fromkeys(
            target["provider_refs"] + list(row.get("provider_refs") or [])
        ))[:30]
        target["signal"] = max(target["signal"], int(row.get("signal") or 0))
    return list(merged.values())


def _select_queries(queries, now, maximum):
    available = [row for row in queries if row.get("id") and row.get("query")]
    if not available or maximum <= 0 or maximum >= len(available):
        return available
    offset = int(now.strftime("%j")) % len(available)
    rotated = available[offset:] + available[:offset]
    return rotated[:maximum]


def _article_registry(previous, candidates, known_urls, now):
    cutoff = now - timedelta(days=30)
    by_url = {}
    for row in previous.get("article_candidates") or []:
        last_seen = _parse_time(row.get("last_seen"))
        url = normalize_url(row.get("url"))
        host = url_host(url)
        base_host = host[4:] if host.startswith("www.") else host
        if (
            url and last_seen and last_seen >= cutoff
            and host not in NON_SOURCE_HOSTS and base_host not in NON_SOURCE_HOSTS
        ):
            by_url[url] = dict(row)
    duplicate_count = 0
    for row in candidates:
        if row["url"] in known_urls:
            duplicate_count += 1
            continue
        existing = by_url.get(row["url"], {})
        first_seen = existing.get("first_seen") or now.isoformat()
        merged = dict(existing)
        merged.update(row)
        merged["first_seen"] = first_seen
        merged["last_seen"] = now.isoformat()
        merged["status"] = "SHADOW"
        merged["channels"] = list(dict.fromkeys(
            list(existing.get("channels") or []) + row["channels"]
        ))
        merged["query_ids"] = list(dict.fromkeys(
            list(existing.get("query_ids") or []) + row["query_ids"]
        ))
        merged["provider_refs"] = list(dict.fromkeys(
            list(existing.get("provider_refs") or []) + row["provider_refs"]
        ))[:30]
        by_url[row["url"]] = merged
    ordered = sorted(
        by_url.values(),
        key=lambda row: (
            len(row.get("channels") or []), int(row.get("signal") or 0),
            row.get("last_seen") or "", row.get("url") or "",
        ),
        reverse=True,
    )[:500]
    return ordered, duplicate_count


def _source_registry(previous, articles, known_hosts, now):
    by_host = {
        str(row.get("host") or ""): dict(row)
        for row in (previous.get("source_candidates") or [])
        if str(row.get("host") or "")
    }
    for article in articles:
        host = str(article.get("host") or "")
        base_host = host[4:] if host.startswith("www.") else host
        if not host or host in known_hosts or base_host in known_hosts:
            continue
        if host in NON_SOURCE_HOSTS or base_host in NON_SOURCE_HOSTS:
            continue
        existing = by_host.get(host, {})
        article_ids = list(dict.fromkeys(
            list(existing.get("article_ids") or []) + [article["candidate_id"]]
        ))[-50:]
        channels = list(dict.fromkeys(
            list(existing.get("channels") or []) + list(article.get("channels") or [])
        ))
        evidence_refs = list(dict.fromkeys(
            list(existing.get("evidence_refs") or []) + list(article.get("provider_refs") or [])
        ))[-80:]
        state = str(existing.get("state") or "DISCOVERED")
        if state not in LIFECYCLE_STATES:
            state = "DISCOVERED"
        if state == "DISCOVERED" and (
            len(channels) >= 2 or len(article_ids) >= 3 or len(evidence_refs) >= 2
        ):
            state = "PROBATION"
        by_host[host] = {
            **existing,
            "host": host,
            "homepage": f"https://{host}/",
            "state": state,
            "first_seen": existing.get("first_seen") or now.isoformat(),
            "last_seen": now.isoformat(),
            "channels": channels,
            "evidence_refs": evidence_refs,
            "article_ids": article_ids,
            "article_count": len(article_ids),
            "sample_urls": list(dict.fromkeys(
                list(existing.get("sample_urls") or []) + [article["url"]]
            ))[-8:],
            "review": existing.get("review") or "pending",
            "auto_publish": False,
        }
    return sorted(
        by_host.values(),
        key=lambda row: (
            row.get("state") == "PROBATION", len(row.get("channels") or []),
            int(row.get("article_count") or 0), row.get("last_seen") or "",
        ),
        reverse=True,
    )[:300]


def managed_source_health(sources, status):
    """Project configured sources into the same lifecycle without auto-pausing."""
    rows = []
    for source in sources if isinstance(sources, list) else []:
        name = str(source.get("name") or "")
        current = status.get(name) if isinstance(status, dict) else {}
        current = current if isinstance(current, dict) else {}
        enabled = source.get("enabled") is not False
        fails = max(0, int(current.get("fails") or 0))
        state = "PAUSED" if not enabled else ("DEGRADED" if fails >= 3 else "ACTIVE")
        fetched = max(0, int(current.get("total_fetched") or 0))
        accepted = max(0, int(current.get("total_accepted") or 0))
        rows.append({
            "name": name,
            "state": state,
            "tier": source.get("tier", "default"),
            "fails": fails,
            "zero_accept_streak": max(0, int(current.get("zero_accept_streak") or 0)),
            "total_fetched": fetched,
            "total_accepted": accepted,
            "acceptance_rate": round(accepted / fetched, 4) if fetched else None,
            "last_attempt": current.get("last_attempt") or current.get("last_run") or "",
            "automatic_pause": False,
        })
    return sorted(rows, key=lambda row: (row["state"] != "DEGRADED", row["name"]))


def render_report(payload):
    stats = payload.get("stats") or {}
    providers = payload.get("providers") or []
    lines = [
        "# DataHot 信源侦察（影子模式）",
        "",
        f"- 生成时间：{payload.get('generated_at', '')}",
        f"- 本轮原始发现：{stats.get('raw_candidates', 0)}",
        f"- 未收录文章候选：{stats.get('article_candidates', 0)}",
        f"- 新信源候选：{stats.get('source_candidates', 0)}",
        f"- 已收录链接去重：{stats.get('catalog_duplicates', 0)}",
        "- 安全边界：候选不会自动进入公共时间轴，ACTIVE 仍需编辑确认。",
        "",
        "## 发现通道",
        "",
    ]
    for provider in providers:
        detail = provider.get("error") or provider.get("reason") or f"{provider.get('count', 0)} 条"
        lines.append(f"- {provider.get('name')}: {provider.get('status')} · {detail}")
    lines.extend(["", "## 优先检查的新信源", ""])
    for source in (payload.get("source_candidates") or [])[:15]:
        lines.append(
            f"- **{source['host']}** · {source['state']} · "
            f"{source.get('article_count', 0)} 篇 · {', '.join(source.get('channels') or [])}"
        )
    degraded = [row for row in (payload.get("managed_sources") or []) if row.get("state") == "DEGRADED"]
    if degraded:
        lines.extend(["", "## 现有信源健康提醒", ""])
        for source in degraded[:15]:
            lines.append(
                f"- **{source['name']}** · DEGRADED · 连续失败 {source.get('fails', 0)} 次"
            )
    lines.extend(["", "## 优先检查的文章", ""])
    for article in (payload.get("article_candidates") or [])[:20]:
        title = article.get("title") or article.get("host") or article["url"]
        lines.append(
            f"- [{title}]({article['url']}) · {', '.join(article.get('channels') or [])}"
        )
    lines.append("")
    return "\n".join(lines)


def run_scout(
    *, sources_path, latest_path, queries_path, state_path, report_path,
    source_status_path=None,
    now=None, environ=None, force=False, openai_provider=None, hn_provider=None,
):
    """Run one shadow discovery pass and return the persisted payload."""
    environ = environ if environ is not None else os.environ
    now = _now_utc(now)
    previous = _read_json(state_path, {})
    if previous.get("policy_version") != DISCOVERY_POLICY_VERSION:
        previous = {}
    interval = max(1, int(environ.get("DISCOVERY_INTERVAL_HOURS", "20") or 20))
    last_run = _parse_time(previous.get("generated_at"))
    if not force and last_run and now - last_run < timedelta(hours=interval):
        return {**previous, "run_status": "frequency_gate"}

    sources = _read_json(sources_path, [])
    latest = _read_json(latest_path, {"events": []})
    source_status = _read_json(source_status_path, {}) if source_status_path else {}
    queries = _read_json(queries_path, [])
    known_hosts = known_source_hosts(sources)
    known_urls = catalog_urls(latest)
    raw = []
    providers = []

    openai_enabled = _truthy(environ.get("DISCOVERY_OPENAI_ENABLED"), True)
    api_key = environ.get("OPENAI_API_KEY", "")
    if openai_enabled and (openai_provider or api_key):
        provider = openai_provider or OpenAIWebSearchProvider(
            api_key, model=environ.get("DISCOVERY_OPENAI_MODEL", "gpt-5.6"),
        )
        maximum = max(1, int(environ.get("DISCOVERY_MAX_QUERIES", "3") or 3))
        selected = _select_queries(queries, now, maximum)
        count = 0
        errors = []
        for query in selected:
            prompt = (
                "Search the public web for original, evidence-rich articles published in the "
                f"last {int(query.get('lookback_days') or 7)} days about: {query['query']}. "
                "Prioritize official engineering blogs, first-party research, technical case "
                "studies, and original reports. Avoid event pages, job posts, listicles, copied "
                "press releases, and generic AI news. Return a concise sourced answer."
            )
            try:
                rows = provider.search(prompt, blocked_hosts=known_hosts)
                for row in rows:
                    raw.append({**row, "channel": "openai_web_search", "query_id": query["id"]})
                count += len(rows)
            except Exception as exc:  # shadow discovery must never break publication
                errors.append(f"{query['id']}:{type(exc).__name__}")
        providers.append({
            "name": "openai_web_search",
            "status": "ok" if not errors else ("partial" if count else "error"),
            "count": count,
            **({"error": ", ".join(errors)[:240]} if errors else {}),
        })
    else:
        providers.append({
            "name": "openai_web_search", "status": "skipped", "count": 0,
            "reason": "OPENAI_API_KEY 未配置" if openai_enabled else "disabled",
        })

    hn_enabled = _truthy(environ.get("DISCOVERY_HN_ENABLED"), True)
    if hn_enabled:
        try:
            rows = hn_provider() if hn_provider else discover_hn(
                max_ids=max(5, int(environ.get("DISCOVERY_HN_MAX_IDS", "45") or 45)),
                minimum_score=max(0, int(environ.get("DISCOVERY_HN_MIN_SCORE", "20") or 20)),
            )
            raw.extend(rows)
            providers.append({"name": "hn_official", "status": "ok", "count": len(rows)})
        except Exception as exc:
            providers.append({
                "name": "hn_official", "status": "error", "count": 0,
                "error": type(exc).__name__,
            })
    else:
        providers.append({"name": "hn_official", "status": "skipped", "count": 0, "reason": "disabled"})

    link_rows = discover_link_graph(latest, known_hosts)
    raw.extend(link_rows)
    providers.append({"name": "accepted_link_graph", "status": "ok", "count": len(link_rows)})

    merged = _merge_raw_candidates(raw)
    articles, duplicate_count = _article_registry(previous, merged, known_urls, now)
    source_candidates = _source_registry(previous, articles, known_hosts, now)
    managed_sources = managed_source_health(sources, source_status)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": DISCOVERY_POLICY_VERSION,
        "mode": "shadow",
        "generated_at": now.isoformat(),
        "run_status": "completed",
        "providers": providers,
        "stats": {
            "raw_candidates": len(raw),
            "merged_candidates": len(merged),
            "article_candidates": len(articles),
            "source_candidates": len(source_candidates),
            "probation_sources": sum(row.get("state") == "PROBATION" for row in source_candidates),
            "catalog_duplicates": duplicate_count,
            "known_source_hosts": len(known_hosts),
            "catalog_urls": len(known_urls),
            "degraded_sources": sum(row.get("state") == "DEGRADED" for row in managed_sources),
        },
        "article_candidates": articles,
        "source_candidates": source_candidates,
        "managed_sources": managed_sources,
    }
    _write_json_atomic(state_path, payload)
    report = render_report(payload)
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(report, encoding="utf-8")
    return payload
