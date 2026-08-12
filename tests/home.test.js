"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const home = require("../pipeline/assets/home.js");

function event(id, topic = "Agent", source = "Source") {
  return {
    event_id: id.toString(16).padStart(12, "0"), zh_title: `Title ${id}`,
    zh_summary: id === 2 ? "semantic layer" : "summary", reason: "reason",
    category: "platform", category_label: "平台", vendors: [], topics: [topic],
    heat: 50, star: false, published: "2026-08-11T12:00:00+08:00",
    first_seen: "2026-08-11T12:00:00+08:00", items: [{ source }]
  };
}

test("URL state preserves query, topic, category and page", () => {
  const state = home.stateFromSearch("?q=semantic&topic=组织人才&category=insight&page=3");
  assert.deepEqual(state, { q: "semantic", topic: "组织人才", category: "insight", page: 3 });
  assert.equal(home.searchForState(state), "?q=semantic&topic=%E7%BB%84%E7%BB%87%E4%BA%BA%E6%89%8D&category=insight&page=3");
  assert.equal(home.stateFromSearch("?category=unknown").category, "");
});

test("pagination and filtering operate on lite metadata", () => {
  const events = [event(1), event(2, "BI"), event(3, "BI")];
  const result = home.visibleEvents(events, { q: "semantic", topic: "BI", page: 1 }, 1);
  assert.equal(result.filtered.length, 1);
  assert.equal(result.visible[0].event_id, events[1].event_id);
  const page2 = home.visibleEvents(events, { q: "", topic: "BI", page: 2 }, 1);
  assert.equal(page2.visible.length, 2);
});

test("category and topic filters compose before progressive pagination", () => {
  const insight = event(10, "组织人才");
  insight.category = "insight";
  const otherInsight = event(11, "风险管理");
  otherInsight.category = "insight";
  const technical = event(12, "组织人才");
  const result = home.visibleEvents(
    [insight, otherInsight, technical],
    { q: "", topic: "组织人才", category: "insight", page: 1 },
    20
  );
  assert.deepEqual(result.filtered.map((item) => item.event_id), [insight.event_id]);
});

test("filter selection avoids incompatible empty category/topic combinations", () => {
  const fromSemantic = home.filterStateAfterSelection(
    { q: "", topic: "语义层", category: "", page: 2 },
    { category: "insight" }
  );
  assert.deepEqual(fromSemantic, { q: "", topic: "all", category: "insight", page: 1 });
  const withBusinessScene = home.filterStateAfterSelection(fromSemantic, { topic: "组织人才" });
  assert.deepEqual(withBusinessScene, { q: "", topic: "组织人才", category: "insight", page: 1 });
  const backToTechnical = home.filterStateAfterSelection(withBusinessScene, { topic: "语义层" });
  assert.deepEqual(backToTechnical, { q: "", topic: "语义层", category: "", page: 1 });
});

test("payload order is explicit and rendering escapes untrusted text", () => {
  const first = event(1); const second = event(2);
  first.zh_title = "<script>alert(1)</script>";
  const ordered = home.orderedEvents({ events: [first, second], home_event_ids: [second.event_id, first.event_id] });
  assert.equal(ordered[0].event_id, second.event_id);
  const html = home.renderTimeline(ordered);
  assert.doesNotMatch(html, /<script>alert/);
  assert.match(html, /&lt;script&gt;alert/);
});
