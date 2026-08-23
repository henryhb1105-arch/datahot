const test = require("node:test");
const assert = require("node:assert/strict");
const favorites = require("../pipeline/assets/favorites.js");

function storage(seed = {}) {
  const values = { ...seed };
  return {
    getItem(key) { return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : null; },
    setItem(key, value) { values[key] = String(value); },
    values
  };
}

function record(id, savedAt, overrides = {}) {
  return {
    event_id: id,
    title: `标题 ${id}`,
    summary: `摘要 ${id}`,
    source: "测试信源",
    category: "agent",
    topics: ["Data Agent"],
    published: "2026-08-20T10:00:00+08:00",
    original_url: "https://example.com/article",
    saved_at: savedAt,
    ...overrides
  };
}

test("legacy id arrays migrate to versioned snapshots without losing membership", () => {
  const local = storage({ dh_favs: JSON.stringify(["aaaaaaaaaaaa", "bbbbbbbbbbbb"]) });
  const migrated = favorites.readRecords(local);
  assert.deepEqual(migrated.map((item) => item.event_id), ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]);
  assert.equal(migrated[0].title, "");

  const enriched = favorites.enrichRecords(migrated, [{
    event_id: "aaaaaaaaaaaa",
    zh_title: "旧收藏标题",
    zh_summary: "旧收藏摘要",
    category: "platform",
    topics: ["湖仓"],
    published: "2026-08-01T10:00:00+08:00",
    items: [{ source: "Databricks" }]
  }]);
  assert.equal(enriched[0].title, "旧收藏标题");
  assert.equal(enriched[1].title, "");
  assert.equal(favorites.writeRecords(local, enriched), true);
  assert.equal(JSON.parse(local.values.dh_favs_v2).version, 2);
  assert.deepEqual(JSON.parse(local.values.dh_favs), ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]);
});

test("saved snapshots remain renderable when the metadata index no longer contains the event", () => {
  const saved = record("aaaaaaaaaaaa", "2026-08-23T10:00:00+08:00");
  const retained = favorites.enrichRecords([saved], []);
  assert.equal(retained[0].title, saved.title);
  assert.equal(retained[0].summary, saved.summary);
  assert.match(favorites.renderCard(retained[0], new Date("2026-08-23T12:00:00+08:00")), /标题 aaaaaaaaaaaa/);
});

test("toggle, newest-first sorting, grouping and topic search form one retrieval loop", () => {
  const older = record("aaaaaaaaaaaa", "2026-07-01T10:00:00+08:00", { topics: ["湖仓"] });
  const newer = record("bbbbbbbbbbbb", "2026-08-23T10:00:00+08:00", { topics: ["Data Agent"] });
  assert.deepEqual(favorites.sortRecords([older, newer]).map((item) => item.event_id), ["bbbbbbbbbbbb", "aaaaaaaaaaaa"]);
  assert.deepEqual(
    favorites.groupRecords([older, newer], new Date("2026-08-23T12:00:00+08:00")).map((group) => group.label),
    ["今天", "更早"]
  );
  assert.deepEqual(favorites.filterRecords([older, newer], "bbbb", "").map((item) => item.event_id), ["bbbbbbbbbbbb"]);
  assert.deepEqual(favorites.filterRecords([older, newer], "", "湖仓").map((item) => item.event_id), ["aaaaaaaaaaaa"]);

  const removed = favorites.toggleRecords([older, newer], newer, new Date("2026-08-23T12:00:00+08:00"));
  assert.equal(removed.action, "remove");
  assert.deepEqual(removed.records.map((item) => item.event_id), ["aaaaaaaaaaaa"]);
  const restored = favorites.toggleRecords(removed.records, newer, new Date("2026-08-23T12:01:00+08:00"));
  assert.equal(restored.action, "add");
  assert.equal(restored.records.length, 2);
});

test("rendered favorite cards escape snapshot text and keep a direct remove action", () => {
  const item = record("aaaaaaaaaaaa", "2026-08-23T10:00:00+08:00", {
    title: '<script>alert("x")</script>',
    summary: "<img src=x onerror=alert(1)>"
  });
  const html = favorites.renderCard(item, new Date("2026-08-23T12:00:00+08:00"));
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /data-fav="aaaaaaaaaaaa"/);
  assert.match(html, /aria-label="取消收藏"/);
});
