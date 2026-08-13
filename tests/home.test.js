"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const home = require("../pipeline/assets/home.js");
const detail = require("../pipeline/assets/detail.js");

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

test("home position belongs to the current history entry and matching filter state", () => {
  const state = { q: "", topic: "Data Agent", category: "", page: 3 };
  const historyState = home.historyStateWithSnapshot(
    { unrelated: "kept" }, state,
    { y: 1480, anchor: "00abc123def0", anchorOffset: 92 }
  );
  assert.equal(historyState.unrelated, "kept");
  assert.deepEqual(home.snapshotFromHistory(historyState, state), {
    version: 1,
    search: "?topic=Data+Agent&page=3",
    page: 3,
    y: 1480,
    anchor: "00abc123def0",
    anchorOffset: 92
  });
  assert.equal(home.snapshotFromHistory(historyState, { ...state, topic: "实时分析" }), null);
  assert.equal(home.snapshotFromHistory(null, state), null);
});

test("mobile back-to-top appears only after a meaningful scroll distance", () => {
  assert.equal(home.shouldShowBackToTop(720, 400), false);
  assert.equal(home.shouldShowBackToTop(721, 400), true);
  assert.equal(home.shouldShowBackToTop(1266, 844), false);
  assert.equal(home.shouldShowBackToTop(1267, 844), true);
});

test("home-top request is one-shot and safe when storage is unavailable", () => {
  const values = new Map([["datahotForceHomeTop", "1"]]);
  const sessionStorage = {
    getItem: (key) => values.get(key) || null,
    removeItem: (key) => values.delete(key)
  };
  assert.equal(home.consumeHomeTopRequest({ sessionStorage }), true);
  assert.equal(home.consumeHomeTopRequest({ sessionStorage }), false);
  assert.equal(home.consumeHomeTopRequest({
    get sessionStorage() { throw new Error("blocked"); }
  }), false);
});

test("scroll behavior honors reduced motion and modified clicks remain native", () => {
  assert.equal(home.preferredScrollBehavior({ matchMedia: () => ({ matches: false }) }), "smooth");
  assert.equal(home.preferredScrollBehavior({ matchMedia: () => ({ matches: true }) }), "auto");
  assert.equal(home.isPlainPrimaryClick({ button: 0 }), true);
  assert.equal(home.isPlainPrimaryClick({ button: 0, metaKey: true }), false);
  assert.equal(home.isPlainPrimaryClick({ button: 1 }), false);
});

test("detail return uses history only for a same-tab visit from the DataHot home page", () => {
  const current = "https://example.com/datahot/e/89e262591ce7.html";
  assert.equal(detail.shouldUseHistoryBack(
    "https://example.com/datahot/index.html?topic=Data+Agent&page=3", current, 4
  ), true);
  assert.equal(detail.shouldUseHistoryBack("https://example.com/datahot/", current, 2), true);
  assert.equal(detail.shouldUseHistoryBack("https://example.com/datahot/hot.html", current, 4), false);
  assert.equal(detail.shouldUseHistoryBack("https://outside.example/article", current, 4), false);
  assert.equal(detail.shouldUseHistoryBack("https://example.com/datahot/index.html", current, 1), false);
  assert.equal(detail.shouldUseHistoryBack("", current, 4), false);
});

test("smart detail return prevents the fallback link and goes back once", () => {
  const clickHandlers = [];
  let backCalls = 0;
  let prevented = false;
  const links = [0, 1, 2, 3].map(() => ({
    addEventListener: (name, handler) => { if (name === "click") clickHandlers.push(handler); }
  }));
  detail.boot({
    document: {
      referrer: "https://example.com/datahot/index.html?topic=Data+Agent&page=3",
      querySelectorAll: () => links
    },
    location: { href: "https://example.com/datahot/e/89e262591ce7.html" },
    history: { length: 3, back: () => { backCalls += 1; } }
  });
  assert.equal(clickHandlers.length, 4);
  clickHandlers[2]({ preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(backCalls, 1);
});

test("smart detail return preserves normal new-tab and modified clicks", () => {
  let clickHandler = null;
  let backCalls = 0;
  detail.boot({
    document: {
      referrer: "https://example.com/datahot/index.html?topic=Data+Agent",
      querySelectorAll: () => [{ addEventListener: (_name, handler) => { clickHandler = handler; } }]
    },
    location: { href: "https://example.com/datahot/e/89e262591ce7.html" },
    history: { length: 3, back: () => { backCalls += 1; } }
  });
  clickHandler({ metaKey: true, preventDefault: () => assert.fail("must not prevent") });
  clickHandler({ button: 1, preventDefault: () => assert.fail("must not prevent") });
  assert.equal(backCalls, 0);
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
  assert.match(html, /data-day-key="2026-08-11"/);
  assert.match(html, /data-date-base="8月11日"/);
});

test("dynamic cards keep one-line source metadata, combined featured heat and bookmark action", () => {
  const item = event(20, "Agent", "Google BigQuery Release Notes With A Very Long Name");
  item.star = true;
  item.heat = 59;
  item.source_badge = "RSS";
  const html = home.renderTimeline([item]);
  assert.match(html, /class="top card-meta"/);
  assert.match(html, /class="card-source"/);
  assert.match(html, /class="card-source-name">Google BigQuery Release Notes/);
  assert.match(html, /class="srcbadge">RSS<\/span>/);
  assert.match(html, /class="heatnum is-featured"[^>]*><svg[^>]*>.*精选 59<\/span>/);
  assert.match(html, /class="favbtn"[^>]*aria-label="收藏" aria-pressed="false"><svg/);
  assert.doesNotMatch(html, />☆<\/button>/);
  assert.doesNotMatch(html, /<span class="star">精选<\/span>/);
});

test("timeline grouping uses publication date before ingestion date", () => {
  const item = event(4);
  item.published = "2026-08-10T23:00:00+08:00";
  item.first_seen = "2026-08-11T09:00:00+08:00";
  const html = home.renderTimeline([item]);
  assert.match(html, /data-day-key="2026-08-10"/);
  assert.doesNotMatch(html, /data-day-key="2026-08-11"/);
});

test("filter failure view never presents stale results as filtered content", () => {
  assert.equal(home.hasActiveFilter({ q: "", topic: "all", category: "" }), false);
  assert.equal(home.hasActiveFilter({ q: "", topic: "Data Agent", category: "" }), true);
  const html = home.renderLoadFailure();
  assert.match(html, /筛选结果加载失败/);
  assert.match(html, /当前没有展示未筛选的旧内容/);
  assert.match(html, /data-filter-retry/);
  assert.match(html, /data-filter-clear/);
});

function failingHomeWindow() {
  const listeners = {};
  const elements = {
    homeDataConfig: { dataset: { pageSize: "20", total: "3", liteUrl: "data/latest-lite.json" } },
    timeline: {
      innerHTML: "STATIC UNFILTERED CONTENT",
      querySelectorAll: () => [],
      addEventListener: (name, handler) => { listeners[name] = handler; }
    },
    loadMore: { hidden: false, disabled: false, textContent: "加载更多（20/3）", addEventListener() {} },
    rCount: { textContent: "3" },
    q: { value: "", addEventListener() {}, focus() { this.focused = true; } },
    qClear: { style: {}, addEventListener() {} }
  };
  let rejectFetch = true;
  const win = {
    document: {
      getElementById: (id) => elements[id],
      querySelectorAll: () => [],
      addEventListener() {}
    },
    location: { search: "?topic=Data+Agent", pathname: "/datahot/index.html", hash: "" },
    history: { state: null, replaceState(state, _title, url) { this.state = state; this.url = url; } },
    fetch() {
      if (rejectFetch) return Promise.reject(new Error("offline"));
      const item = event(1, "Data Agent");
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ events: [item], home_event_ids: [item.event_id] }) });
    },
    setTimeout, clearTimeout,
    addEventListener() {},
    scrollY: 0,
    scrollTo() {},
    requestAnimationFrame(callback) { callback(); }
  };
  return { win, elements, listeners, allowFetch() { rejectFetch = false; } };
}

test("failed filtered request replaces static list and retry can recover", async () => {
  const fixture = failingHomeWindow();
  home.boot(fixture.win);
  await new Promise(setImmediate);
  assert.doesNotMatch(fixture.elements.timeline.innerHTML, /STATIC UNFILTERED CONTENT/);
  assert.match(fixture.elements.timeline.innerHTML, /筛选结果加载失败/);
  assert.equal(fixture.elements.loadMore.hidden, true);
  assert.equal(fixture.elements.rCount.textContent, "—");

  fixture.allowFetch();
  fixture.listeners.click({ target: { closest: (selector) => selector === "[data-filter-retry]" ? {} : null } });
  await new Promise(setImmediate);
  await new Promise(setImmediate);
  assert.match(fixture.elements.timeline.innerHTML, /Title 1/);
  assert.doesNotMatch(fixture.elements.timeline.innerHTML, /筛选结果加载失败/);
});

test("clear-filter recovery restores the known unfiltered first page", async () => {
  const fixture = failingHomeWindow();
  home.boot(fixture.win);
  await new Promise(setImmediate);
  fixture.listeners.click({ target: { closest: (selector) => selector === "[data-filter-clear]" ? {} : null } });
  assert.equal(fixture.elements.timeline.innerHTML, "STATIC UNFILTERED CONTENT");
  assert.equal(fixture.win.history.url, "/datahot/index.html");
  assert.equal(fixture.elements.rCount.textContent, "3");
  assert.equal(fixture.elements.q.focused, true);
});
