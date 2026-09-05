"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const analytics = require("../pipeline/assets/analytics.js");

test("client keeps only the documented field whitelist", () => {
  const clean = analytics.sanitizeEvent({
    schema_version: 99,
    name: "search",
    site_id: "DataHot!",
    page: "home",
    event_id: "not-valid",
    category: "private-category",
    source: "Source\nName",
    filter: "data-agent",
    query_bucket: "4-8",
    result_count: 12,
    body: "article text must never leave",
    search_text: "a complete private query",
    api_key: "secret",
    email: "person@example.com",
    latitude: 31.2,
    acquisition_source: "bluesky",
    acquisition_format: "card",
  });
  assert.equal(clean.schema_version, 1);
  assert.equal(clean.site_id, "datahot");
  assert.equal(Object.hasOwn(clean, "event_id"), false);
  assert.equal(Object.hasOwn(clean, "category"), false);
  assert.equal(clean.source, "Source Name");
  for (const forbidden of ["body", "search_text", "api_key", "email", "latitude"]) {
    assert.equal(Object.hasOwn(clean, forbidden), false);
  }
  assert.deepEqual(Object.keys(clean).sort(), [
    "filter", "name", "page", "query_bucket", "result_count",
    "schema_version", "site_id", "source", "acquisition_source", "acquisition_format",
  ].sort());
});

test("acquisition attribution keeps only complete allowlisted pairs", () => {
  assert.deepEqual(
    analytics.acquisitionFromSearch("?utm_source=bluesky&utm_content=card&utm_campaign=private"),
    { source: "bluesky", format: "card" },
  );
  assert.deepEqual(
    analytics.acquisitionFromSearch("?utm_source=x&utm_content=text&secret=customer"),
    { source: "x", format: "text" },
  );
  assert.deepEqual(analytics.acquisitionFromSearch("?utm_source=bluesky"), { source: "", format: "" });
  assert.deepEqual(analytics.acquisitionFromSearch("?utm_source=email&utm_content=card"), { source: "", format: "" });
  const partial = analytics.sanitizeEvent({
    name: "page_view", site_id: "datahot", page: "detail", page_path: "/e/0123456789ab.html",
    acquisition_source: "bluesky",
  });
  assert.equal(Object.hasOwn(partial, "acquisition_source"), false);
  assert.equal(Object.hasOwn(partial, "acquisition_format"), false);
});

test("search values collapse to length buckets only", () => {
  assert.equal(analytics.queryBucket(""), "");
  assert.equal(analytics.queryBucket("SQL"), "1-3");
  assert.equal(analytics.queryBucket("semantic"), "4-8");
  assert.equal(analytics.queryBucket("private customer name"), "9+");
});

test("content feedback keeps only bounded enum signals", () => {
  const clean = analytics.sanitizeEvent({
    name: "content_feedback", event_id: "aaaaaaaaaaaa", action: "not_useful",
    feedback_reason: "marketing", body: "must drop", page: "detail", site_id: "datahot"
  });
  assert.equal(clean.action, "not_useful");
  assert.equal(clean.feedback_reason, "marketing");
  assert.equal(Object.hasOwn(clean, "body"), false);
  const invalid = analytics.sanitizeEvent({
    name: "content_feedback", event_id: "aaaaaaaaaaaa", action: "useful",
    feedback_reason: "free text", page: "detail", site_id: "datahot"
  });
  assert.equal(Object.hasOwn(invalid, "feedback_reason"), false);
});

test("share actions keep only bounded anonymous intent signals", () => {
  const clean = analytics.sanitizeEvent({
    name: "share_action", event_id: "aaaaaaaaaaaa", action: "native",
    page: "detail", site_id: "datahot", recipient: "private contact",
  });
  assert.equal(clean.action, "native");
  assert.equal(Object.hasOwn(clean, "recipient"), false);
  const invalid = analytics.sanitizeEvent({
    name: "share_action", event_id: "aaaaaaaaaaaa", action: "send_to_person",
    page: "detail", site_id: "datahot",
  });
  assert.equal(Object.hasOwn(invalid, "action"), false);
});

test("page classifier never includes full URLs", () => {
  assert.equal(analytics.pageFromPath("/datahot/"), "home");
  assert.equal(analytics.pageFromPath("/datahot/index.html"), "home");
  assert.equal(analytics.pageFromPath("/datahot/for-me.html"), "for-me");
  assert.equal(analytics.pageFromPath("/datahot/cases.html"), "cases");
  assert.equal(analytics.pageFromPath("/datahot/weekly.html"), "weekly");
  assert.equal(analytics.pageFromPath("/datahot/weekly/2026-W32.html"), "weekly");
  assert.equal(analytics.pageFromPath("/datahot/daily.html"), "daily");
  assert.equal(analytics.pageFromPath("/datahot/topics/data-agent.html"), "topic");
  assert.equal(analytics.pageFromPath("/datahot/classics.html"), "classics");
  assert.equal(analytics.pageFromPath("/datahot/e/0123456789ab.html"), "detail");
  assert.equal(analytics.pageFromPath("/unknown"), "other");
});

test("page path keeps only public relative routes and drops query data", () => {
  assert.equal(analytics.safePagePath("/datahot/?private=1"), "/");
  assert.equal(analytics.safePagePath("/e/0123456789ab.html?utm_source=test"), "/e/0123456789ab.html");
  assert.equal(analytics.safePagePath("/topics/data-agent.html#section"), "/topics/data-agent.html");
  assert.equal(analytics.safePagePath("/cases.html?product=agent"), "/cases.html");
  assert.equal(analytics.safePagePath("/account/person@example.com"), "");
  const clean = analytics.sanitizeEvent({
    name: "page_view", site_id: "datahot", page: "detail",
    page_path: "/e/0123456789ab.html?secret=1"
  });
  assert.equal(clean.page_path, "/e/0123456789ab.html");
});

test("minimum event model is explicitly enumerated", () => {
  for (const name of [
    "list_exposure", "detail_click", "outbound_click", "favorite_toggle",
    "content_feedback", "share_action", "search", "filter", "weekly_brief_click", "daily_brief_click", "session_start", "page_view",
  ]) assert.ok(analytics.eventNames.includes(name));
  assert.equal(typeof analytics.observeList, "function");
});

test("every design study and comparison route survives the client-to-worker contract", async () => {
  const { validateEvent, toStoredEvent } = await import("../ops/traffic-worker/src/schema.js");
  const { studies } = require("../pipeline/design_studies.json");
  const paths = ["/cases/compare.html", ...studies.map((study) => `/cases/${study.slug}.html`)];
  for (const path of paths) {
    for (const prefix of ["", "/datahot"]) {
      assert.equal(analytics.pageFromPath(prefix + path), "cases");
      const input = analytics.sanitizeEvent({
        name: "page_view", site_id: "datahot", environment: "production",
        page: analytics.pageFromPath(prefix + path),
        page_path: prefix + path + "?utm_source=x&utm_content=text&private=must-drop#step-2",
        acquisition_source: "x", acquisition_format: "text",
        event_uuid: "00000000-0000-4000-8000-000000000001",
        session_id: "00000000-0000-4000-8000-000000000002",
        device_id: "00000000-0000-4000-8000-000000000003",
        ts: "2026-09-05T01:00:00Z", sequence: 1, viewport: "large", referrer: "social",
      });
      assert.equal(input.page_path, path);
      assert.deepEqual(validateEvent(input, { now: Date.parse("2026-09-05T01:01:00Z") }), []);
      const stored = toStoredEvent(input, "2026-09-05T01:01:00Z");
      assert.equal(stored.page_path, path);
      assert.equal(stored.page, "cases");
      assert.equal(stored.acquisition_source, "x");
      assert.equal(stored.acquisition_format, "text");
      assert.equal(JSON.stringify(stored).includes("must-drop"), false);
    }
  }
});

test("case routes cannot admit private paths or unbounded slugs", () => {
  for (const path of [
    "/cases/../account.html", "/cases/%2e%2e.html", "/cases/person@example.com.html",
    "/cases/customer/record.html", "/cases/Hex.html", "/cases/.html",
    "/cases/" + "a".repeat(61) + ".html", "https://datahot.xiahongbin.com/cases/hex-threads.html",
  ]) {
    assert.equal(analytics.safePagePath(path), "", path);
    assert.equal(analytics.pageFromPath(path), "other", path);
  }
});

test("automated browsers never create identifiers or send events", () => {
  let storageTouches = 0;
  let sends = 0;
  const storage = {
    getItem() { storageTouches += 1; throw new Error("automation must not read storage"); },
    setItem() { storageTouches += 1; throw new Error("automation must not write storage"); },
    removeItem() { storageTouches += 1; throw new Error("automation must not mutate storage"); },
  };
  const attributes = {
    "data-enabled": "true",
    "data-endpoint": "https://metrics.datahot.xiahongbin.com/v1/events",
    "data-site-id": "datahot",
    "data-environment": "production",
    "data-production-host": "datahot.xiahongbin.com",
  };
  const document = {
    body: { dataset: {} },
    querySelector(selector) {
      if (selector === 'meta[name="datahot-analytics"]') {
        return { getAttribute(name) { return attributes[name] || ""; } };
      }
      return null;
    },
    querySelectorAll() { return []; },
    addEventListener() {},
    getElementById() { return null; },
  };
  const win = {
    document,
    navigator: {
      webdriver: true,
      sendBeacon() { sends += 1; return true; },
    },
    localStorage: storage,
    sessionStorage: storage,
    location: {
      hostname: "datahot.xiahongbin.com",
      pathname: "/",
      search: "",
      origin: "https://datahot.xiahongbin.com",
      href: "https://datahot.xiahongbin.com/",
    },
    crypto: { randomUUID() { throw new Error("automation must not create IDs"); } },
    addEventListener() {},
    setTimeout() { throw new Error("automation must not schedule sends"); },
    clearTimeout() {},
  };

  assert.doesNotThrow(() => analytics.boot(win));
  assert.equal(storageTouches, 0);
  assert.equal(sends, 0);
});
