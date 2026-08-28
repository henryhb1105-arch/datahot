import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { createSessionCookie, passwordMatches, sessionAuthorized } from "../src/auth.js";

const env = { SESSION_SECRET: "test-session-secret-that-is-at-least-32-characters" };

test("password verification compares only a strong password against its SHA-256 secret", async () => {
  const password = "correct horse battery staple";
  const hash = createHash("sha256").update(password).digest("hex");
  assert.equal(await passwordMatches(password, hash), true);
  assert.equal(await passwordMatches("incorrect password value", hash), false);
  assert.equal(await passwordMatches("short", hash), false);
  assert.equal(await passwordMatches(password, "not-a-hash"), false);
});

test("signed sessions expire after twelve hours and reject tampering", async () => {
  const issuedAt = new Date("2026-08-28T08:00:00Z");
  const setCookie = await createSessionCookie(env, issuedAt);
  const cookie = setCookie.split(";", 1)[0];
  const request = new Request("https://admin.datahot.xiahongbin.com/", { headers: { Cookie: cookie } });
  assert.equal(await sessionAuthorized(request, env, new Date("2026-08-28T19:59:59Z")), true);
  assert.equal(await sessionAuthorized(request, env, new Date("2026-08-28T20:00:00Z")), false);

  const [cookieName, token] = cookie.split("=");
  const [expires, signature] = token.split(".");
  const tampered = `${cookieName}=${expires}.${signature.startsWith("A") ? "B" : "A"}${signature.slice(1)}`;
  const tamperedRequest = new Request("https://admin.datahot.xiahongbin.com/", { headers: { Cookie: tampered } });
  assert.equal(await sessionAuthorized(tamperedRequest, env, new Date("2026-08-28T09:00:00Z")), false);
});
