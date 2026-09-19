"""Opt-in, weekly X candidate intake. Default invocation is an offline plan.

The collector never publishes, buys credits, expands users/media, or retries a
request. A worst-case reservation is durably written BEFORE every API call.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
TERMS = '(agent OR semantic OR analytics OR dashboard OR context)'
MAX_POSTS = 200
MAX_BUDGET = Decimal("5")


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc) if len(value) == 10 else datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def plan(config):
    accounts = config.get("accounts") or []
    if not 1 <= len(accounts) <= 12 or any(not re.fullmatch(r"[A-Za-z0-9_]{1,15}", a) for a in accounts):
        raise ValueError("an explicit allowlist of 1-12 account handles is required")
    limit = int(config["weekly_post_limit"])
    price = Decimal(config["post_price_ceiling_usd"])
    budget = Decimal(config["rolling_31_day_budget_usd"])
    if not 10 <= limit <= MAX_POSTS or not price.is_finite() or price < Decimal("0.005"):
        raise ValueError("invalid read count or stale price ceiling")
    if not budget.is_finite() or not 0 <= budget <= MAX_BUDGET:
        raise ValueError("budget must be between 0 and 5 USD")
    query = "(" + " OR ".join("from:" + a for a in dict.fromkeys(accounts)) + ") " + TERMS + " -is:retweet -is:reply"
    if len(query) > 512:
        raise ValueError("query exceeds the self-serve limit")
    return {"enabled":config.get("enabled") is True, "query":query, "max_posts":limit,
            "max_weekly_cost_usd":str(limit * price), "rolling_31_day_budget_usd":str(budget),
            "mode":"candidates_only", "network_requests":0}


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("API redirects are not followed")


def fetch_page(params, token):
    req = Request("https://api.x.com/2/tweets/search/recent?" + urlencode(params),
                  headers={"Authorization":"Bearer " + token, "User-Agent":"DataHot-X-Radar/1.0"})
    with build_opener(NoRedirect()).open(req, timeout=25) as response:
        return json.load(response)


def canonical_link(value):
    p = urlparse(value)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        return ""
    query = [(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith("utm_") and k.lower() not in {"ref","s","t"}]
    return urlunparse(("https",p.netloc.lower(),p.path.rstrip("/") or "/","",urlencode(query),""))


def collect(config, state_path, *, token, now=None, fetch=fetch_page):
    proposal = plan(config)
    now = now or datetime.now(timezone.utc)
    if not proposal["enabled"] or Decimal(proposal["rolling_31_day_budget_usd"]) <= 0:
        return {**proposal, "status":"disabled"}
    for field in ("pricing_verified_at", "console_spending_limit_verified_at"):
        verified = timestamp(str(config.get(field) or ""))
        if not timedelta(0) <= now - verified <= timedelta(days=30):
            raise ValueError("pricing and console limit must be verified within 30 days")
    if not token:
        raise ValueError("a dedicated read bearer token is required")
    state_path = Path(state_path).resolve()
    if (ROOT / "site").resolve() in state_path.parents:
        raise ValueError("candidate state must stay outside the public site")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # A corrupt ledger fails closed instead of silently restoring budget.
        state = json.loads(state_path.read_text()) if state_path.exists() else {"reservations":[],"candidates":{},"seen":[]}
        if state.get("last_attempt") and now - timestamp(state["last_attempt"]) < timedelta(days=7):
            return {**proposal, "status":"weekly_cache_hit"}
        reservations = [r for r in state["reservations"] if now - timestamp(r["at"]) < timedelta(days=31)]
        spent = sum((Decimal(r["usd"]) for r in reservations), Decimal(0))
        price, budget = Decimal(config["post_price_ceiling_usd"]), Decimal(config["rolling_31_day_budget_usd"])
        remaining = min(proposal["max_posts"], int((budget - spent) / price))
        if remaining < 10:
            return {**proposal, "status":"budget_exhausted"}
        state["last_attempt"] = now.isoformat()
        state["reservations"] = reservations
        seen = set(state.get("seen", []))
        links = {url for row in state["candidates"].values() for url in row.get("links", []) if urlparse(url).path != "/"}
        params = {"query":proposal["query"], "start_time":(now-timedelta(days=7)+timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "end_time":(now-timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ"), "tweet.fields":"created_at,entities", "sort_order":"recency"}
        calls, added, complete = 0, 0, False
        while remaining >= 10:
            count = min(50, remaining)
            params["max_results"] = count
            state["reservations"].append({"at":now.isoformat(), "usd":str(count * price),
                                          "posts":count, "query_hash":hashlib.sha256(proposal["query"].encode()).hexdigest()[:16]})
            atomic_json(state_path, state)
            calls += 1
            try:
                response = fetch(params, token)
            except Exception as error:
                state["last_status"] = "request_failed_no_retry"
                atomic_json(state_path, state)
                return {"status":state["last_status"], "error_type":type(error).__name__, "network_requests":calls, "added":added}
            rows = response.get("data") or []
            if not isinstance(rows, list) or len(rows) > count or response.get("errors"):
                raise ValueError("unexpected API response; reservation retained")
            for row in rows:
                identifier = str(row.get("id") or "")
                if not re.fullmatch(r"[0-9]{1,19}", identifier) or identifier in seen:
                    continue
                seen.add(identifier)
                urls = list(dict.fromkeys(filter(None, (canonical_link(u.get("expanded_url") or "") for u in (row.get("entities") or {}).get("urls", [])))))
                if any(url in links for url in urls if urlparse(url).path != "/"):
                    continue
                links.update(url for url in urls if urlparse(url).path != "/")
                state["candidates"][identifier] = {"id":identifier, "x_url":"https://x.com/i/status/"+identifier,
                    "text":str(row.get("text") or "")[:10000], "published":row.get("created_at"), "links":urls,
                    "status":"needs_editorial_review", "collected_at":now.isoformat()}
                added += 1
            state["seen"] = sorted(seen)[-10000:]
            state["candidates"] = dict(list(state["candidates"].items())[-1000:])
            atomic_json(state_path, state)
            remaining -= count  # No refund: charge uncertainty stays reserved.
            next_token = (response.get("meta") or {}).get("next_token")
            if not next_token:
                complete = True
                break
            params["next_token"] = str(next_token)
        state["last_status"] = "collected" if complete else "stopped_at_budget"
        atomic_json(state_path, state)
        return {"status":state["last_status"], "network_requests":calls, "added":added,
                "coverage_complete":complete, "auto_published":0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "pipeline/x_radar_config.json")
    parser.add_argument("--state", type=Path, default=ROOT / ".local/x-radar/state.json")
    parser.add_argument("--execute", action="store_true", help="Requires enabled config, verified console limit and read token")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    result = collect(config, args.state, token=os.getenv("DATAHOT_X_READ_BEARER_TOKEN", "")) if args.execute else plan(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
