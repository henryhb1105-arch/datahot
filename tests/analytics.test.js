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

test("page classifier never includes full URLs", () => {
  assert.equal(analytics.pageFromPath("/datahot/"), "home");
  assert.equal(analytics.pageFromPath("/datahot/index.html"), "home");
  assert.equal(analytics.pageFromPath("/datahot/for-me.html"), "for-me");
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
    "content_feedback", "search", "filter", "weekly_brief_click", "daily_brief_click", "session_start", "page_view",
  ]) assert.ok(analytics.eventNames.includes(name));
  assert.equal(typeof analytics.observeList, "function");
});
