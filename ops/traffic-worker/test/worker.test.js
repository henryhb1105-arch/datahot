import assert from "node:assert/strict";
import test from "node:test";
import { handleIngest, handleRequest } from "../src/index.js";

function fakeDb(changes = 1) {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      return {
        bind(...args) {
          const statement = { sql, args, run: async () => ({ success: true, meta: { changes: 1 } }) };
          calls.push(statement);
          return statement;
        },
      };
    },
    async batch(statements) { return statements.map(() => ({ success: true, meta: { changes } })); },
  };
}

function env(db = fakeDb()) {
  return {
    DB: db,
    PUBLIC_SITE_ORIGIN: "https://datahot.xiahongbin.com",
    METRICS_HOST: "metrics.datahot.xiahongbin.com",
    ADMIN_HOST: "admin.datahot.xiahongbin.com",
    SITE_ID: "datahot",
    ADMIN_EMAIL: "owner@example.com",
  };
}

function uuid(number) { return `00000000-0000-4000-8000-${number.toString(16).padStart(12, "0")}`; }

function payload(now) {
  return {
    schema_version: 1,
    site_id: "datahot",
    events: [{
      schema_version: 1, event_uuid: uuid(1), name: "page_view", ts: now.toISOString(),
      environment: "production", site_id: "datahot", page: "home", page_path: "/",
      session_id: uuid(2), device_id: uuid(3), sequence: 1, viewport: "large", referrer: "direct",
    }],
  };
}

test("collector rejects non-production origins before touching storage", async () => {
  const db = fakeDb();
  const request = new Request("https://metrics.datahot.xiahongbin.com/v1/events", {
    method: "POST", headers: { Origin: "https://evil.example", "Content-Type": "text/plain" }, body: "{}",
  });
  const response = await handleIngest(request, env(db), new Date("2026-08-28T08:00:00Z"));
  assert.equal(response.status, 403);
  assert.equal(db.calls.length, 0);
});

test("collector accepts a bounded valid batch and reports duplicates", async () => {
  const now = new Date("2026-08-28T08:00:00Z");
  const db = fakeDb(0);
  const request = new Request("https://metrics.datahot.xiahongbin.com/v1/events", {
    method: "POST",
    headers: { Origin: "https://datahot.xiahongbin.com", "Content-Type": "text/plain;charset=UTF-8" },
    body: JSON.stringify(payload(now)),
  });
  const response = await handleIngest(request, env(db), now);
  assert.equal(response.status, 202);
  assert.deepEqual(await response.json(), { accepted: 0, rejected: 0, duplicate: 1 });
  assert.ok(db.calls.some((call) => call.sql.includes("INSERT OR IGNORE INTO events")));
  assert.ok(db.calls.some((call) => call.sql.includes("INSERT INTO ingest_stats")));
});

test("admin host fails closed without Access and serves with matching identity", async () => {
  const environment = env();
  const denied = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/"), environment, {});
  assert.equal(denied.status, 403);
  const allowed = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/"), environment, {
    access: { getIdentity: async () => ({ email: "owner@example.com" }) },
  });
  assert.equal(allowed.status, 200);
  assert.match(await allowed.text(), /DataHot 运营后台/);
  assert.equal(allowed.headers.get("X-Robots-Tag"), "noindex, nofollow, noarchive");
});

test("local dashboard bypass is explicit and cannot be enabled by hostname alone", async () => {
  const environment = env();
  const denied = await handleRequest(new Request("http://localhost:8787/"), environment, {});
  assert.equal(denied.status, 404);
  environment.LOCAL_DEV = "true";
  const allowed = await handleRequest(new Request("http://localhost:8787/"), environment, {});
  assert.equal(allowed.status, 200);
});
