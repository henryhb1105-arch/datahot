"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const feedback = require("../pipeline/assets/content-feedback.js");

test("feedback store is bounded, explicit and content-free", () => {
  const state = feedback.normalizeStore({ entries: {
    aaaaaaaaaaaa: { value: "useful", reason: "solid", topics: ["Data Agent", "Data Agent"], vendors: ["dbt"], body: "must drop" },
    "unsafe/id": { value: "useful", reason: "solid" },
    bbbbbbbbbbbb: { value: "maybe", reason: "solid" }
  }});
  assert.deepEqual(Object.keys(state.entries), ["aaaaaaaaaaaa"]);
  assert.deepEqual(state.entries.aaaaaaaaaaaa.topics, ["Data Agent"]);
  assert.equal(Object.hasOwn(state.entries.aaaaaaaaaaaa, "body"), false);
});

test("record keeps fit context but not article text", () => {
  const state = feedback.record({}, {
    event_id: "aaaaaaaaaaaa", topics: ["语义层"], vendors: ["Snowflake"],
    source: "Engineering Blog", body: "private article body"
  }, "not_useful", "irrelevant", "2026-08-28T06:00:00Z");
  assert.deepEqual(state.entries.aaaaaaaaaaaa, {
    value: "not_useful", reason: "irrelevant", topics: ["语义层"],
    vendors: ["Snowflake"], source: "Engineering Blog", ts: "2026-08-28T06:00:00Z"
  });
});
