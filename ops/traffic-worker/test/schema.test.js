import assert from "node:assert/strict";
import test from "node:test";
import { safePagePath, shanghaiDay, toStoredEvent, validateEvent } from "../src/schema.js";

function uuid(number) {
  return `00000000-0000-4000-8000-${number.toString(16).padStart(12, "0")}`;
}

function event(extra = {}) {
  return {
    schema_version: 1,
    event_uuid: uuid(1),
    name: "page_view",
    ts: "2026-08-28T08:00:00.000Z",
    environment: "production",
    site_id: "datahot",
    page: "detail",
    page_path: "/e/0123456789ab.html",
    session_id: uuid(2),
    device_id: uuid(3),
    sequence: 1,
    viewport: "large",
    referrer: "social",
    ...extra,
  };
}

test("server accepts the public page view contract", () => {
  const input = event({ acquisition_source: "bluesky", acquisition_format: "card" });
  assert.deepEqual(validateEvent(input, { now: Date.parse("2026-08-28T08:01:00Z"), siteId: "datahot" }), []);
  const stored = toStoredEvent(input, "2026-08-28T08:01:00.000Z");
  assert.equal(stored.day_cst, "2026-08-28");
  assert.equal(stored.page_path, "/e/0123456789ab.html");
  assert.equal(stored.acquisition_source, "bluesky");
  assert.equal(stored.acquisition_format, "card");
  assert.equal(Object.hasOwn(stored, "query_bucket"), false);
});

test("server rejects private, stale, future, and unknown data", () => {
  assert.ok(validateEvent(event({ email: "person@example.com" }), { now: Date.parse("2026-08-28T08:01:00Z") }).includes("unknown_fields"));
  assert.ok(validateEvent(event({ page_path: "/account/person@example.com" }), { now: Date.parse("2026-08-28T08:01:00Z") }).includes("page_path_required"));
  assert.ok(validateEvent(event({ ts: "2026-08-25T08:00:00Z" }), { now: Date.parse("2026-08-28T08:01:00Z") }).includes("timestamp_stale"));
  assert.ok(validateEvent(event({ ts: "2026-08-28T09:00:00Z" }), { now: Date.parse("2026-08-28T08:01:00Z") }).includes("timestamp_future"));
  assert.ok(validateEvent(event({ acquisition_source: "bluesky" }), { now: Date.parse("2026-08-28T08:01:00Z") }).includes("acquisition_pair"));
  assert.ok(validateEvent(event({ acquisition_source: "email", acquisition_format: "card" }), { now: Date.parse("2026-08-28T08:01:00Z") }).includes("acquisition_source"));
});

test("server accepts only bounded share actions with a public event id", () => {
  const shared = event({ name: "share_action", event_id: "0123456789ab", action: "copy" });
  assert.deepEqual(validateEvent(shared, { now: Date.parse("2026-08-28T08:01:00Z") }), []);
  assert.ok(validateEvent(event({ name: "share_action", action: "copy" }), {
    now: Date.parse("2026-08-28T08:01:00Z"),
  }).includes("event_id_required"));
  assert.ok(validateEvent(event({ name: "share_action", event_id: "0123456789ab", action: "private_recipient" }), {
    now: Date.parse("2026-08-28T08:01:00Z"),
  }).includes("action"));
});

test("page paths and Shanghai calendar days are bounded", () => {
  assert.equal(safePagePath("/"), "/");
  assert.equal(safePagePath("/cases.html"), "/cases.html");
  assert.equal(safePagePath("/topics/data-agent.html"), "/topics/data-agent.html");
  assert.equal(safePagePath("/search.html?q=private"), "");
  assert.equal(safePagePath("/index.html/private"), "");
  assert.equal(shanghaiDay("2026-08-28T17:30:00Z"), "2026-08-29");
});

test("case page views keep X attribution without widening the privacy boundary", () => {
  for (const path of ["/cases/hex-threads.html", "/cases/compare.html"]) {
    const input = event({ page: "cases", page_path: path, acquisition_source: "x", acquisition_format: "text" });
    assert.deepEqual(validateEvent(input, { now: Date.parse("2026-08-28T08:01:00Z") }), []);
    assert.equal(toStoredEvent(input, "2026-08-28T08:01:00Z").page_path, path);
  }
  for (const path of [
    "/cases/hex-threads.html?private=1", "/cases/compare.html#private",
    "/cases/../account.html", "/cases/%2e%2e.html", "/cases/person@example.com.html",
    "/cases/customer/record.html", "/cases/Hex.html", "/cases/.html",
    "/cases/" + "a".repeat(61) + ".html",
  ]) assert.equal(safePagePath(path), "", path);
});
