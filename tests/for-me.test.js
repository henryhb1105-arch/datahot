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

test("personal scoring overrides fixed global direction priority while dismissals remain authoritative", () => {
  const rows = [0, 1, 2, 3, 4, 5].map(priority => ({
    ...event(String(priority + 1).repeat(12), { vendors: ["Vendor"], heat: priority * 19 }),
    focus: { priority, practical: false },
  }));
  const state = forMe.normalizeState({ vendors: ["Vendor"], dismissed: [rows[0].event_id] });
  const unrelated = { ...rows[0], event_id: "ffffffffffff", vendors: ["Other"] };
  const ranked = forMe.rankEvents([unrelated, ...rows.slice().reverse()], state, Date.now(), true);
  assert.deepEqual(ranked.map(e => e.focus.priority), [5, 4, 3, 2, 1]);
});

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

test("one product provides an exact feed while old topic preferences survive", () => {
  const old = forMe.normalizeState({ topics: ["语义层"], vendors: ["Snowflake"] });
  assert.deepEqual(old.products, []);
  assert.deepEqual(old.topics, ["语义层"]);
  const state = forMe.normalizeState({ products: ["hex", "hex", "../bad"] });
  assert.deepEqual(state.products, ["hex"]);
  const target = { ...event("aaaaaaaaaaaa"), product_ids: ["hex"] };
  const unrelated = event("bbbbbbbbbbbb", { vendors: ["Hex"] });
  assert.deepEqual(forMe.rankEvents([unrelated, target], state, Date.now(), true).map(e => e.event_id), ["aaaaaaaaaaaa"]);
  assert.deepEqual(forMe.matchReasons(target, state), [{ kind: "product", value: "hex" }]);
  assert.deepEqual(forMe.buildSuggestions([], [{id:"hex",name:"Hex"}])[0], {kind:"product",value:"hex",label:"Hex"});
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

test("ranking computes each score once without mutating events", () => {
  let calls = 0;
  const rows = Array.from({length: 80}, (_, i) => {
    const row = event(String(i).padStart(12, "0"));
    Object.defineProperty(row, "quality_score", {get() { calls++; return 50; }});
    return row;
  });
  const original = rows.slice();
  const ranked = forMe.rankEvents(rows, forMe.normalizeState({}), Date.now(), false);
  assert.equal(calls, rows.length);
  assert.equal(ranked.length, rows.length);
  assert.deepEqual(rows, original);
});

const today = Date.parse("2026-10-18T07:00:00Z");
test("work choices produce different leading recommendations and bounded migrated state", () => {
  const agent = event("aaaaaaaaaaaa", {title: "Agent 工具调用评测", published: "2026-10-18T00:00:00Z"});
  const platform = event("bbbbbbbbbbbb", {title: "湖仓成本与迁移", published: "2026-10-18T00:00:00Z"});
  for (const [task, expected] of [["agent", agent], ["platform", platform]]) {
    const state = forMe.normalizeState({tasks: [task, task, "invalid"], topics: ["语义层"]});
    assert.deepEqual(state.tasks, [task]);
    assert.deepEqual(state.topics, ["语义层"]);
    assert.equal(forMe.rankEvents([agent, platform], state, today, true)[0], expected);
    assert.equal(forMe.matchReasons(expected, state)[0].kind, "task");
  }
});
test("sections keep read and stale stories out of today's picks and do not duplicate cards", () => {
  const state = forMe.normalizeState({tasks:["agent"], read:{aaaaaaaaaaaa:"2026-10-18"}});
  const read = event("aaaaaaaaaaaa", {title:"Agent tools", published:"2026-10-18T00:00:00Z"});
  const old = event("bbbbbbbbbbbb", {title:"Agent实践", published:"2026-08-01T00:00:00Z"});
  const fresh = event("cccccccccccc", {title:"Agent评测", published:"2026-10-17T00:00:00Z"});
  const result = forMe.sections([read, old, fresh], state, today, "2026-10-18T00:00:00Z");
  assert.deepEqual(result.must, [fresh]); assert.deepEqual(result.work, [old]);
  const ids = [...result.must,...result.updates,...result.work,...result.discovery].map(e=>e.event_id);
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(forMe.sections([read, old],state,today, "2026-10-18T00:00:00Z").must.length,0);
});

test("generic engineering design tradeoffs do not imply product design relevance", () => {
  const state = forMe.normalizeState({tasks:["design"]});
  const training = {...event("aaaaaaaaaaaa", {title:"Qwen训练性能优化"}),zh_summary:"讨论性能测量、实现细节与设计权衡",reason:"对产品设计有启发"};
  assert.deepEqual(forMe.taskReasons(training,state),[]);
  assert.equal(forMe.taskReasons({...training,zh_title:"AI产品设计中的交互与界面"},state).length,1);
});

test('section ranking equals the public ranking filtered by relevance, with one stable personalization decision', () => {
  const events = require('./fixtures/reading-intents.json');
  const affinity = require('../pipeline/assets/content-affinity');
  const now = Date.parse('2026-10-18T08:00:00Z');
  for (const options of [{}, {topics:['Data Agent'], tasks:['agent']}, {reading:{enabled:true,entries:{'64843a2454f2':[now],'7175222a4aa1':[now]}}}]) {
    const state = forMe.normalizeState(options);
    state.reading = options.reading || {enabled:true,entries:{}};
    state.affinity = affinity.profile(events,state,now);
    const personalized = state.topics.length > 0 || Object.keys(state.affinity.matches).length > 0;
    const expected = forMe.rankEvents(events,state,now,personalized);
    const grouped = forMe.sections(events,state,now,null);
    assert.deepEqual(grouped.ranked,expected);
  }
});

test('exhausted follows keep discovery unread, recent and distinct without changing preferences', () => {
  const now = Date.parse('2026-10-20T00:00:00Z');
  const matched = event('aaaaaaaaaaaa',{vendors:['Cube'],published:'2026-10-19T00:00:00Z'});
  const discovery = event('bbbbbbbbbbbb',{vendors:['Other'],published:'2026-10-19T00:00:00Z'});
  const hidden = {...discovery,event_id:'cccccccccccc'};
  const old = {...discovery,event_id:'dddddddddddd',published:'2020-01-01T00:00:00Z'};
  const state = forMe.normalizeState({vendors:['Cube'],read:{[matched.event_id]:'2026-10-20'},dismissed:[hidden.event_id]});
  const before = JSON.stringify(state);
  const grouped = forMe.sections([matched,discovery,hidden,old],state,now,null);
  assert.equal(grouped.must.length + grouped.updates.length + grouped.work.length,0);
  assert.deepEqual(grouped.discovery,[discovery]);
  assert.equal(JSON.stringify(state),before);
  const exhausted = forMe.sections([matched,hidden,old],state,now,null);
  assert.equal(exhausted.discovery.length,0);
});

test("server promotion decisions suppress thin announcements while legacy and insufficient-body records stay available", () => {
  const low = { ...event("low"), promotion_suppressed: true };
  const legacy = event("legacy");
  const insufficient = { ...event("partial"), promotion_suppressed: false, information_value: { status: "insufficient_body" } };
  const state = forMe.normalizeState({});
  assert.deepEqual(new Set(forMe.rankEvents([low, legacy, insufficient], state, Date.now(), false).map(e => e.event_id)), new Set(["legacy", "partial"]));
  assert.equal(forMe.rankEvents([{ ...low, promotion_suppressed: false }], state, Date.now(), false).length, 1);
});
