import assert from "node:assert/strict";
import { createHash } from "node:crypto";
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
    ADMIN_PASSWORD_HASH: createHash("sha256").update("correct horse battery staple").digest("hex"),
    SESSION_SECRET: "test-session-secret-that-is-at-least-32-characters",
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

test("admin host redirects to login and fails closed for a wrong password", async () => {
  const environment = env();
  const denied = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/"), environment, {});
  assert.equal(denied.status, 303);
  assert.equal(denied.headers.get("Location"), "/login");

  const loginPage = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/login"), environment, {});
  assert.equal(loginPage.status, 200);
  assert.match(await loginPage.text(), /后台密码/);

  const rejected = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "password=wrong-password-value",
  }), environment, {});
  assert.equal(rejected.status, 401);
  assert.equal(rejected.headers.get("Set-Cookie"), null);
});

test("correct password creates a secure session that can access and leave the dashboard", async () => {
  const environment = env();
  const login = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ password: "correct horse battery staple" }),
  }), environment, {});
  assert.equal(login.status, 303);
  assert.equal(login.headers.get("Location"), "/");
  const setCookie = login.headers.get("Set-Cookie");
  assert.match(setCookie, /__Host-datahot_admin=/);
  assert.match(setCookie, /HttpOnly/);
  assert.match(setCookie, /Secure/);
  assert.match(setCookie, /SameSite=Strict/);

  const cookie = setCookie.split(";", 1)[0];
  const allowed = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/", {
    headers: { Cookie: cookie },
  }), environment, {});
  assert.equal(allowed.status, 200);
  assert.match(await allowed.text(), /DataHot 运营后台/);
  assert.equal(allowed.headers.get("X-Robots-Tag"), "noindex, nofollow, noarchive");

  const [cookieName, token] = cookie.split("=");
  const [expires, signature] = token.split(".");
  const tampered = `${cookieName}=${expires}.${signature.startsWith("A") ? "B" : "A"}${signature.slice(1)}`;
  const denied = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/api/dashboard", {
    headers: { Cookie: tampered },
  }), environment, {});
  assert.equal(denied.status, 401);

  const logout = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/logout", {
    method: "POST", headers: { Cookie: cookie },
  }), environment, {});
  assert.equal(logout.status, 303);
  assert.equal(logout.headers.get("Location"), "/login");
  assert.match(logout.headers.get("Set-Cookie"), /Max-Age=0/);
});

test("missing password secrets never produce an authenticated session", async () => {
  const environment = env();
  delete environment.ADMIN_PASSWORD_HASH;
  delete environment.SESSION_SECRET;
  const response = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ password: "correct horse battery staple" }),
  }), environment, {});
  assert.equal(response.status, 401);
  assert.equal(response.headers.get("Set-Cookie"), null);
});

test("admin login rejects oversized or unexpected request bodies", async () => {
  const environment = env();
  const wrongType = await handleRequest(new Request("https://admin.datahot.xiahongbin.com/login", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
  }), environment, {});
  assert.equal(wrongType.status, 400);

  const oversized = new Request("https://admin.datahot.xiahongbin.com/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", "Content-Length": "3000" },
    body: "password=irrelevant-value",
  });
  const response = await handleRequest(oversized, environment, {});
  assert.equal(response.status, 400);
});

test("local dashboard bypass is explicit and cannot be enabled by hostname alone", async () => {
  const environment = env();
  const denied = await handleRequest(new Request("http://localhost:8787/"), environment, {});
  assert.equal(denied.status, 404);
  environment.LOCAL_DEV = "true";
  const allowed = await handleRequest(new Request("http://localhost:8787/"), environment, {});
  assert.equal(allowed.status, 200);
});
