"""Bounded X distribution. Secrets stay in Actions; every POST has a durable intent.

There is deliberately no retry of an X write, no arbitrary API method, no media,
and no automatic ledger initialization. A missing or uncertain ledger fails shut.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

REPO = "henryhb1105-arch/datahot"
HANDLE = "AA_basketball"
HOST = "datahot.xiahongbin.com"
BRANCH = "growth-x-ledger"
STATE_PATH = "x-state.json"
TZ = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parent
TERMINAL = {"published", "external_post", "cancelled_before_post"}


class SafeStop(Exception):
    """Only fixed non-secret messages may be exposed to logs."""


class HttpFailure(SafeStop):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"http_status_{status}")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(method, url, headers=None, payload=None, *, raw=False):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=data, method=method, headers={
        "User-Agent": "DataHot-growth/1.0", **(headers or {}),
        **({"Content-Type": "application/json"} if data is not None else {}),
    })
    try:
        with build_opener(NoRedirect).open(request, timeout=25) as response:
            body = response.read(3_000_001)
            if len(body) > 3_000_000:
                raise SafeStop("response_too_large")
            return body.decode("utf-8") if raw else json.loads(body)
    except HTTPError as exc:
        # Never log response bodies, request headers, or credential-bearing errors.
        raise HttpFailure(exc.code) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise SafeStop("network_or_response_failure") from None


def enc(value):
    return quote(str(value), safe="~-._")


def oauth_header(method, url, credentials, *, nonce=None, timestamp=None):
    key, secret, token, token_secret = credentials
    auth = {"oauth_consumer_key": key, "oauth_token": token,
            "oauth_nonce": nonce or secrets.token_hex(16),
            "oauth_timestamp": str(timestamp or int(datetime.now(timezone.utc).timestamp())),
            "oauth_signature_method": "HMAC-SHA1", "oauth_version": "1.0"}
    parsed = urlsplit(url)
    parameters = sorted((enc(k), enc(v)) for k, v in list(auth.items()) + parse_qsl(parsed.query))
    normalized = "&".join(f"{k}={v}" for k, v in parameters)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    base = "&".join(map(enc, [method.upper(), base_url, normalized]))
    signing_key = f"{enc(secret)}&{enc(token_secret)}"
    auth["oauth_signature"] = base64.b64encode(
        hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{enc(k)}="{enc(v)}"' for k, v in sorted(auth.items()))


def utc_now():
    return datetime.now(timezone.utc)


def day_of(now):
    if now.tzinfo is None:
        raise SafeStop("timezone_required")
    return now.astimezone(TZ).date().isoformat()


def bounds(day):
    start = datetime.fromisoformat(day).replace(tzinfo=TZ)
    return tuple(t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                 for t in (start, start + timedelta(days=1)))


def scheduled_allowed(now):
    local = now.astimezone(TZ)
    return 18 * 60 + 7 <= local.hour * 60 + local.minute < 19 * 60 + 37


class XClient:
    def __init__(self, credentials, transport=http):
        if len(credentials) != 4 or not all(credentials):
            raise SafeStop("missing_x_credentials")
        self.credentials, self.transport = credentials, transport

    def request(self, method, path, payload=None):
        url = "https://api.x.com" + path
        return self.transport(method, url, {"Authorization": oauth_header(
            method, url, self.credentials)}, payload)

    def identity(self):
        result = self.request("GET", "/2/users/me?user.fields=protected")
        user = result.get("data", {})
        if (result.get("errors") or user.get("username", "").lower() != HANDLE.lower()
                or not re.fullmatch(r"\d{1,20}", user.get("id", "")) or user.get("protected")):
            raise SafeStop("account_mismatch_or_not_public")
        return {"id": user["id"], "username": user["username"]}

    def timeline(self, user_id, day):
        start, end = bounds(day)
        query = {"max_results": 5, "start_time": start,
                 "tweet.fields": "created_at,entities,author_id"}
        if day < day_of(utc_now()):
            query["end_time"] = end
        params = urlencode(query)
        result = self.request("GET", f"/2/users/{user_id}/tweets?{params}")
        if result.get("errors") or result.get("meta", {}).get("next_token"):
            raise SafeStop("timeline_incomplete")
        posts = result.get("data", [])
        if not isinstance(posts, list):
            raise SafeStop("timeline_invalid")
        return posts

    def create(self, text):
        result = self.request("POST", "/2/tweets", {"text": text})
        post_id = result.get("data", {}).get("id", "")
        if result.get("errors") or not re.fullmatch(r"\d{1,20}", post_id):
            raise SafeStop("post_result_uncertain")
        return post_id

    def get_post(self, post_id):
        result = self.request("GET", f"/2/tweets/{post_id}?tweet.fields=created_at,entities,author_id")
        if result.get("errors") or not isinstance(result.get("data"), dict):
            raise SafeStop("post_readback_failed")
        return result["data"]


class Ledger:
    def __init__(self, token, transport=http):
        if not token:
            raise SafeStop("missing_ledger_credentials")
        self.transport = transport
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"}

    def request(self, method, path, payload=None):
        return self.transport(method, f"https://api.github.com/repos/{REPO}/{path}", self.headers, payload)

    def load(self):
        result = self.request("GET", f"contents/{STATE_PATH}?ref={BRANCH}")
        try:
            state = json.loads(base64.b64decode(result["content"]))
            if (state["version"] != 1 or state["handle"] != HANDLE
                    or not isinstance(state["days"], dict)
                    or not re.fullmatch(r"\d{1,20}", state["account_id"])):
                raise ValueError()
            for day, record in state["days"].items():
                if (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
                        or record["date"] != day or record["account_id"] != state["account_id"]
                        or record["status"] not in TERMINAL | {"reserved", "submitted"}):
                    raise ValueError()
                datetime.fromisoformat(day)
                if record["status"] in {"published", "submitted", "external_post"} and not re.fullmatch(
                        r"\d{1,20}", record["post_id"]):
                    raise ValueError()
            return state, result["sha"]
        except (KeyError, ValueError, TypeError):
            raise SafeStop("ledger_invalid") from None

    def save(self, state, sha):
        payload = {"branch": BRANCH, "message": "chore: record X publication state",
                   "content": base64.b64encode(json.dumps(state, ensure_ascii=False,
                       indent=2, sort_keys=True).encode()).decode()}
        if sha:
            payload["sha"] = sha
        result = self.request("PUT", f"contents/{STATE_PATH}", payload)
        return result["content"]["sha"]

    def initialize(self, user):
        try:
            state, _ = self.load()
            if state["account_id"] != user["id"]:
                raise SafeStop("ledger_account_mismatch")
            return {"status": "already_initialized", "account": user}
        except HttpFailure as exc:
            if exc.status != 404:
                raise
        # Explicit manual operation only. Never called by publish or schedule.
        try:
            self.request("GET", f"git/ref/heads/{BRANCH}")
        except HttpFailure as exc:
            if exc.status != 404:
                raise
            main = self.request("GET", "git/ref/heads/main")
            self.request("POST", "git/refs", {"ref": f"refs/heads/{BRANCH}",
                                               "sha": main["object"]["sha"]})
        state = {"version": 1, "handle": HANDLE, "account_id": user["id"], "days": {}}
        self.save(state, None)
        return {"status": "initialized", "account": user}


def post_urls(post):
    return [item.get("expanded_url", "") for item in post.get("entities", {}).get("urls", [])]


def expanded_text(post):
    text = post.get("text", "")
    for item in post.get("entities", {}).get("urls", []):
        if item.get("url") and item.get("expanded_url"):
            text = text.replace(item["url"], item["expanded_url"])
    return text


def matches(post, record):
    try:
        created = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
        return (post["author_id"] == record["account_id"] and day_of(created) == record["date"]
                and expanded_text(post) == record["text"])
    except (KeyError, ValueError):
        return False


def datahot_post(post):
    return any(urlsplit(url).hostname == HOST for url in post_urls(post)) or HOST in post.get("text", "")


def validate_queue(items, studies):
    known = {s["slug"]: s for s in studies}
    seen = set()
    for item in items:
        slug = item.get("slug", "")
        if not re.fullmatch(r"[a-z0-9-]{1,60}", slug) or slug not in known or slug in seen:
            raise SafeStop("queue_case_invalid")
        seen.add(slug)
        if not isinstance(item.get("step"), int) or not 1 <= item["step"] <= len(known[slug]["steps"]):
            raise SafeStop("queue_step_invalid")
        if item.get("source") not in [s["url"] for s in known[slug]["sources"]]:
            raise SafeStop("queue_source_invalid")
        if (not isinstance(item.get("body"), str) or "http" in item["body"]
                or "DataHot" not in item["body"] or "@" in item["body"]):
            raise SafeStop("queue_copy_invalid")
        # Conservative X weighted length, with a single t.co URL counted as 23.
        if sum(1 if ord(c) < 128 else 2 for c in item["body"]) + 25 > 280:
            raise SafeStop("queue_copy_too_long")
        if any(ord(c) < 32 and c != "\n" for c in item["body"]):
            raise SafeStop("queue_control_character")
        if item.get("historical") and "旧版" not in item["body"]:
            raise SafeStop("queue_version_missing")
        try:
            if (not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", item[k])
                        for k in ["reviewed_on", "valid_through"])
                    or datetime.fromisoformat(item["reviewed_on"]) > datetime.fromisoformat(item["valid_through"])):
                raise ValueError()
        except (KeyError, ValueError):
            raise SafeStop("queue_review_invalid") from None
    return items


def landing(item, transport=http):
    path = f'/cases/{item["slug"]}.html'
    url = f'https://{HOST}{path}?utm_source=x&utm_content=text#step-{item["step"]}'
    page = transport("GET", f"https://{HOST}{path}", raw=True)
    if f'id="step-{item["step"]}"' not in page or item["slug"] not in page:
        raise SafeStop("landing_not_ready")
    return path, url


def reconcile(x, ledger, state, sha, record):
    posts = ([x.get_post(record["post_id"])] if record.get("post_id") else
             x.timeline(record["account_id"], record["date"]))
    matched = [post for post in posts if matches(post, record)]
    if len(matched) != 1:
        raise SafeStop("uncertain_publication_needs_review_no_retry")
    record.update(status="published", post_id=matched[0]["id"],
                  verified_at=utc_now().isoformat(),
                  post_url=f'https://x.com/{HANDLE}/status/{matched[0]["id"]}')
    ledger.save(state, sha)
    return {**record, "status": "reconciled"}


def publish(x, ledger, items, *, now=utc_now, check_landing=landing):
    instant = now()
    day = day_of(instant)
    state, sha = ledger.load()  # Fail before any X call if missing/unreadable.
    for date, record in sorted(state["days"].items()):
        if record.get("status") not in TERMINAL:
            user = x.identity()
            if user["id"] != state["account_id"]:
                raise SafeStop("ledger_account_mismatch")
            return reconcile(x, ledger, state, sha, record)
    if day in state["days"]:
        record = state["days"][day]
        return {**record, "status": ("already_published" if record["status"] != "cancelled_before_post"
                                     else "cancelled_before_post")}
    used = {r.get("slug") for r in state["days"].values()}
    used.update(slug for r in state["days"].values() for slug in r.get("external_case_slugs", []))
    item = next((i for i in items if i["slug"] not in used and
                 i["reviewed_on"] <= day <= i["valid_through"]), None)
    if item is None:
        return {"status": "no_fresh_candidate", "date": day}
    user = x.identity()
    if user["id"] != state["account_id"]:
        raise SafeStop("ledger_account_mismatch")
    posts = x.timeline(user["id"], day)
    existing = [p for p in posts if datahot_post(p)]
    if existing:
        record = {"date": day, "account_id": user["id"], "status": "external_post",
                  "post_id": existing[0]["id"]}
        case_slugs = [urlsplit(u).path.removeprefix("/cases/").removesuffix(".html")
                      for p in existing for u in post_urls(p)
                      if urlsplit(u).hostname == HOST and re.fullmatch(r"/cases/[a-z0-9-]{1,60}\.html", urlsplit(u).path)]
        record["external_case_slugs"] = case_slugs
        state["days"][day] = record
        ledger.save(state, sha)
        return {**record, "status": "already_published"}
    path, url = check_landing(item)
    text = item["body"] + "\n\n" + url
    record = {"date": day, "account_id": user["id"], "handle": HANDLE,
              "status": "reserved", "slug": item["slug"], "page_path": path, "url": url,
              "text": text, "creative": "text", "copy_variant": "design_problem_first",
              "language_variant": "zh", "source": item["source"],
              "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
              "run_id": os.environ.get("GITHUB_RUN_ID", ""),
              "reserved_at": instant.isoformat()}
    state["days"][day] = record
    sha = ledger.save(state, sha)  # Atomic SHA compare-and-swap BEFORE the only POST.
    if day_of(now()) != day:
        record["status"] = "cancelled_before_post"
        ledger.save(state, sha)
        return {"status": "crossed_midnight_no_post", "date": day}
    try:
        post_id = x.create(text)  # Exactly one attempt, including on timeout/402/429/5xx.
    except SafeStop:
        # Durable reservation already exists, even if a result update cannot be saved.
        raise SafeStop("post_result_uncertain_no_retry") from None
    record.update(status="submitted", post_id=post_id)
    sha = ledger.save(state, sha)
    result = reconcile(x, ledger, state, sha, record)
    result["status"] = "published"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["audit", "initialize", "publish"], default="audit")
    args = parser.parse_args()
    event = os.environ.get("GITHUB_EVENT_NAME")
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or event not in {"workflow_dispatch", "schedule"}:
        raise SafeStop("trusted_main_workflow_required")
    if event == "schedule" and (args.mode != "publish" or os.environ.get("GROWTH_X_ENABLED") != "true"
                                or not scheduled_allowed(utc_now())):
        return {"status": "schedule_skipped"}
    names = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
    x = XClient(tuple(os.environ.get(n, "") for n in names))
    if args.mode == "audit":
        return {"status": "identity_verified", "account": x.identity(), "post_writes": 0}
    ledger = Ledger(os.environ.get("GITHUB_TOKEN", ""))
    if args.mode == "initialize":
        return ledger.initialize(x.identity())
    items = validate_queue(json.loads((ROOT / "x_growth_queue.json").read_text()),
                           json.loads((ROOT / "design_studies.json").read_text())["studies"])
    return publish(x, ledger, items)


if __name__ == "__main__":
    try:
        result = main()
    except SafeStop as exc:
        print(json.dumps({"status": "stopped", "reason": str(exc)}, ensure_ascii=False))
        sys.exit(1)
    except Exception:
        print(json.dumps({"status": "stopped", "reason": "unexpected_failure_no_retry"}))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False))
