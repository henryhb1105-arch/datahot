"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const forMe = require("../pipeline/assets/for-me.js");

function event(id, options = {}) {
  return {
    event_id: id,
    zh_title: options.title || id,
    zh_summary: "摘要",
    reason: "为什么重要",
    topics: options.topics || [],
    vendors: options.vendors || [],
    importance: options.importance || 50,
    heat: options.heat || 50,
    published: options.published || "2026-08-21T12:00:00+08:00",
    first_seen: options.firstSeen || "2026-08-21T13:00:00+08:00",
    items: [{ source: "Source" }],
  };
}

test("state is local, bounded and de-duplicated", () => {
  const state = forMe.normalizeState({
    topics: ["Data Agent", "Data Agent", " 语义层 "],
    vendors: ["Snowflake", "Snowflake"],
    dismissed: ["aaaaaaaaaaaa", "aaaaaaaaaaaa"],
    read: { aaaaaaaaaaaa: "2026-08-22T00:00:00Z", "unsafe/id": "x" },
    lastVisit: "not-a-date",
  });
  assert.deepEqual(state.topics, ["Data Agent", "语义层"]);
  assert.deepEqual(state.vendors, ["Snowflake"]);
  assert.deepEqual(state.dismissed, ["aaaaaaaaaaaa"]);
  assert.deepEqual(Object.keys(state.read), ["aaaaaaaaaaaa"]);
  assert.equal(state.lastVisit, "");
});

test("explicit follows outrank global popularity and explain the match", () => {
  const state = forMe.normalizeState({ topics: ["语义层"], vendors: [] });
  const matching = event("aaaaaaaaaaaa", { topics: ["语义层"], importance: 55, heat: 30 });
  const popular = event("bbbbbbbbbbbb", { topics: ["Data Agent"], importance: 99, heat: 99 });
  const ranked = forMe.rankEvents([popular, matching], state, Date.parse("2026-08-22T00:00:00Z"), true);
  assert.deepEqual(ranked.map((item) => item.event_id), ["aaaaaaaaaaaa"]);
  assert.deepEqual(forMe.matchReasons(matching, state), [{ kind: "topic", value: "语义层" }]);
});

test("quality, trend and personal fit remain independent ranking inputs", () => {
  const state = forMe.normalizeState({ topics: ["语义层"], vendors: [] });
  state.feedback = forMe.normalizeFeedbackStore({ entries: {
    aaaaaaaaaaaa: {
      value: "not_useful", reason: "irrelevant", topics: ["语义层"], vendors: [], source: "Source"
    }
  }});
  const rejected = event("aaaaaaaaaaaa", { topics: ["语义层"], importance: 99, heat: 99 });
  rejected.quality_score = 99; rejected.trend_score = 99;
  const useful = event("bbbbbbbbbbbb", { topics: ["语义层"], importance: 55, heat: 30 });
  useful.quality_score = 55; useful.trend_score = 30;
  const ranked = forMe.rankEvents([rejected, useful], state, Date.parse("2026-08-22T00:00:00Z"), true);
  assert.deepEqual(ranked.map((item) => item.event_id), ["bbbbbbbbbbbb", "aaaaaaaaaaaa"]);
  assert.equal(forMe.fitScore(rejected, state, state.feedback), 0);
  assert.ok(forMe.fitScore(useful, state, state.feedback) > 0);
});

test("new count uses ingestion time rather than an old publication date", () => {
  const olderArticleAddedToday = event("aaaaaaaaaaaa", {
    published: "2026-07-01T00:00:00Z",
    firstSeen: "2026-08-22T09:00:00Z",
  });
  assert.equal(forMe.isNewSince(olderArticleAddedToday, "2026-08-22T08:00:00Z"), true);
  assert.equal(forMe.isNewSince(olderArticleAddedToday, "2026-08-22T10:00:00Z"), false);
});

test("suggestions contain both topics and vendors with stable topic priority", () => {
  const suggestions = forMe.buildSuggestions([
    event("aaaaaaaaaaaa", { topics: ["语义层"], vendors: ["Snowflake"] }),
    event("bbbbbbbbbbbb", { topics: ["Data Agent"], vendors: ["Databricks"] }),
    event("cccccccccccc", { topics: ["Data Agent"], vendors: ["Snowflake"] }),
  ]);
  assert.deepEqual(suggestions.slice(0, 2).map((item) => item.value), ["Data Agent", "语义层"]);
  assert.ok(suggestions.some((item) => item.kind === "vendor" && item.value === "Snowflake"));
});
