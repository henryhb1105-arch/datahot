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
    "schema_version", "site_id", "source",
  ].sort());
});

test("search values collapse to length buckets only", () => {
  assert.equal(analytics.queryBucket(""), "");
  assert.equal(analytics.queryBucket("SQL"), "1-3");
  assert.equal(analytics.queryBucket("semantic"), "4-8");
  assert.equal(analytics.queryBucket("private customer name"), "9+");
});

test("page classifier never includes full URLs", () => {
  assert.equal(analytics.pageFromPath("/datahot/"), "home");
  assert.equal(analytics.pageFromPath("/datahot/index.html"), "home");
  assert.equal(analytics.pageFromPath("/datahot/for-me.html"), "for-me");
  assert.equal(analytics.pageFromPath("/datahot/weekly.html"), "weekly");
  assert.equal(analytics.pageFromPath("/datahot/weekly/2026-W32.html"), "weekly");
  assert.equal(analytics.pageFromPath("/datahot/daily.html"), "weekly");
  assert.equal(analytics.pageFromPath("/datahot/topics/data-agent.html"), "topic");
  assert.equal(analytics.pageFromPath("/datahot/e/0123456789ab.html"), "detail");
  assert.equal(analytics.pageFromPath("/unknown"), "other");
});

test("minimum event model is explicitly enumerated", () => {
  for (const name of [
    "list_exposure", "detail_click", "outbound_click", "favorite_toggle",
    "search", "filter", "weekly_brief_click", "daily_brief_click", "session_start",
  ]) assert.ok(analytics.eventNames.includes(name));
  assert.equal(typeof analytics.observeList, "function");
});
