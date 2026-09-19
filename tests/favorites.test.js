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

test("lightweight and full events keep the original URL through save and Markdown export", () => {
  for (const source of [
    { original_url: "https://hex.tech/blog/context-studio/", items: [{ source: "Hex" }] },
    { items: [{ source: "Hex", link: "https://hex.tech/blog/context-studio/" }] }
  ]) {
    const local = storage();
    const snapshot = favorites.eventSnapshot({ event_id: "aaaaaaaaaaaa", zh_title: "Context Studio", ...source });
    favorites.writeRecords(local, [snapshot]);
    const saved = favorites.readRecords(local);
    assert.equal(saved[0].original_url, "https://hex.tech/blog/context-studio/");
    assert.match(favorites.exportMarkdown(saved, favorites.readLibrary(local)), /原文：<https:\/\/hex.tech\/blog\/context-studio\/>/);
  }
});

test("source-link backfill preserves titled snapshots, saved dates, projects and notes", () => {
  const local = storage();
  const saved = record("aaaaaaaaaaaa", "2026-09-19T00:00:00Z", { original_url: "" });
  const library = favorites.normalizeLibrary({ projects: [{ id: "p_project1", name: "语义研究" }], entries: {
    aaaaaaaaaaaa: { project_id: "p_project1", note: "验证口径\n检查权限" }
  }});
  favorites.writeLibrary(local, library);
  favorites.writeRecords(local, favorites.enrichRecords([saved], [{
    event_id: saved.event_id, zh_title: "索引更新后的标题", original_url: "https://example.com/original",
    items: [{ source: "更新后的信源" }]
  }]));
  const restored = favorites.readRecords(local)[0];
  assert.equal(restored.title, saved.title);
  assert.equal(restored.source, saved.source);
  assert.equal(restored.saved_at, saved.saved_at);
  assert.equal(restored.original_url, "https://example.com/original");
  assert.deepEqual(favorites.readLibrary(local), library);
  const markdown = favorites.exportMarkdown([restored], favorites.readLibrary(local));
  assert.match(markdown, /原文：<https:\/\/example.com\/original>/);
  assert.match(markdown, /项目：语义研究/);
  assert.match(markdown, /> 验证口径\n> 检查权限/);
});

test("snapshots and exports reject malformed or credential-bearing original URLs", () => {
  for (const url of ["javascript:alert(1)", "https://", "https://[bad", "https://user:password@example.com",
    "https://exa mple.com", "https://example.com/\npath", "https://example.com/\\path", "https://example.com/" + "a".repeat(2000)]) {
    const item = record("aaaaaaaaaaaa", "", { original_url: url });
    assert.equal(favorites.normalizeRecord(item).original_url, "");
    assert.doesNotMatch(favorites.exportMarkdown([item], favorites.normalizeLibrary({})), /原文：/);
  }
});

test("design-study favorites retain their safe route without a news event", () => {
  const item = record("aaaaaaaaaaaa", "2026-09-05T01:00:00Z", { detail_path: "cases/metabase-metabot.html" });
  const local = storage();
  favorites.writeRecords(local, [item]);
  const restored = favorites.enrichRecords(favorites.readRecords(local), []);
  assert.match(favorites.renderCard(restored[0]), /href="cases\/metabase-metabot.html"/);
  for (const path of ["https://evil.test", "//evil.test", "../admin.html", "cases/../../private", "cases/x.html?x=1", "cases/a.html\" onclick=\"x"]) {
    const unsafe = favorites.normalizeRecord({ ...item, detail_path: path });
    assert.equal(unsafe.detail_path, "");
    assert.match(favorites.renderCard(unsafe), /href="e\/aaaaaaaaaaaa.html"/);
  }
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

test("projects and notes survive legacy favorite writes and project removal", () => {
  const local = storage();
  const library = favorites.normalizeLibrary({ projects:[{id:"p_project1",name:"Agent 调研"}], entries:{
    aaaaaaaaaaaa:{project_id:"p_project1",note:"口径问题\n下一步验证"}
  }});
  assert.equal(favorites.writeLibrary(local, library), true);
  favorites.writeRecords(local, [record("aaaaaaaaaaaa", "2026-09-19T00:00:00Z")]);
  assert.equal(favorites.readLibrary(local).entries.aaaaaaaaaaaa.note, "口径问题\n下一步验证");
  const removed = favorites.removeProject(library, "p_project1");
  assert.equal(removed.entries.aaaaaaaaaaaa.project_id, "");
  assert.equal(removed.entries.aaaaaaaaaaaa.note, library.entries.aaaaaaaaaaaa.note);
  assert.equal(favorites.readRecords(local).length, 1);
  const failing = {setItem(){throw new Error("quota");}};
  assert.equal(favorites.writeLibrary(failing, library), false);
});

test("project search includes notes and unassigned filter keeps records", () => {
  const library = favorites.normalizeLibrary({projects:[{id:"p_project1",name:"评测"}],entries:{
    aaaaaaaaaaaa:{project_id:"p_project1",note:"待做配对实验"}
  }});
  const records = [record("aaaaaaaaaaaa",""),record("bbbbbbbbbbbb","")];
  assert.equal(favorites.filterLibrary(records,library,"p_project1","配对","").length,1);
  assert.deepEqual(favorites.filterLibrary(records,library,"unassigned","","").map(r=>r.event_id),["bbbbbbbbbbbb"]);
  const html = favorites.renderCard(records[0],new Date(),library);
  assert.match(html,/data-project-note="aaaaaaaaaaaa"/);
  assert.match(html,/p_project1" selected/);
});

test("Markdown export carries stable case links, source and literal personal notes", () => {
  const library = favorites.normalizeLibrary({projects:[{id:"p_project1",name:"Agent 调研"}],entries:{
    aaaaaaaaaaaa:{project_id:"p_project1",note:"<script>\n# 仍是笔记"}
  }});
  const item = record("aaaaaaaaaaaa","",{detail_path:"cases/metabase-metabot.html",title:"指标 [口径]"});
  const markdown = favorites.exportMarkdown([item],library,"Agent 调研",new Date("2026-09-19T00:00:00Z"));
  assert.match(markdown,/https:\/\/datahot.xiahongbin.com\/cases\/metabase-metabot.html/);
  assert.match(markdown,/原文：<https:\/\/example.com\/article>/);
  assert.ok(markdown.includes("指标 \\[口径\\]"));
  assert.ok(markdown.includes("> \\<script\\>\n> \\# 仍是笔记"));
  assert.doesNotMatch(markdown,/<script>/);
});

test("versioned favorite client resolves toast link from nested pages", () => {
  const document = {querySelector(){return {src:"https://datahot.xiahongbin.com/favorites.js?v=123"};},baseURI:"https://datahot.xiahongbin.com/products/hex.html"};
  assert.equal(favorites.favoritesUrl(document),"https://datahot.xiahongbin.com/favorites.html");
});
