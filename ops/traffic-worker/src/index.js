import { DASHBOARD_HTML, DASHBOARD_JS } from "./dashboard.js";
import { clearSessionCookie, createSessionCookie, LOGIN_HTML, passwordMatches, sessionAuthorized } from "./auth.js";
import { shanghaiDay, toStoredEvent, validateEvent } from "./schema.js";
import { addDays, buildDashboardSummary } from "./summary.js";

const MAX_BODY_BYTES = 32 * 1024;
const MAX_BATCH_EVENTS = 20;
const ADMIN_LOGIN_RATE_LIMIT_KEY = "datahot-admin-login";
const ADMIN_LOGIN_RATE_LIMIT_SECONDS = 60;

function json(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...extraHeaders,
    },
  });
}

function adminHeaders(contentType, extraHeaders = {}) {
  return {
    "Content-Type": contentType,
    "Cache-Control": "no-store, private",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    ...extraHeaders,
  };
}

function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin": env.PUBLIC_SITE_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function integerSetting(value, fallback, minimum, maximum) {
  const parsed = Number.parseInt(String(value || ""), 10);
  return Number.isFinite(parsed) ? Math.max(minimum, Math.min(maximum, parsed)) : fallback;
}

function resultRows(result) {
  return Array.isArray(result?.results) ? result.results : [];
}

async function writeIngestStats(env, values) {
  await env.DB.prepare(`
    INSERT INTO ingest_stats (
      day_cst, requests, received_events, accepted_events,
      duplicate_events, invalid_events, last_received_at
    ) VALUES (?, 1, ?, ?, ?, ?, ?)
    ON CONFLICT(day_cst) DO UPDATE SET
      requests = requests + 1,
      received_events = received_events + excluded.received_events,
      accepted_events = accepted_events + excluded.accepted_events,
      duplicate_events = duplicate_events + excluded.duplicate_events,
      invalid_events = invalid_events + excluded.invalid_events,
      last_received_at = excluded.last_received_at
  `).bind(
    values.day,
    values.received,
    values.accepted,
    values.duplicates,
    values.invalid,
    values.receivedAt,
  ).run();
}

export async function handleIngest(request, env, now = new Date()) {
  const cors = corsHeaders(env);
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors });
  }
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405, cors);
  if (request.headers.get("Origin") !== env.PUBLIC_SITE_ORIGIN) return json({ error: "origin_not_allowed" }, 403, cors);
  if (!String(request.headers.get("Content-Type") || "").toLowerCase().startsWith("text/plain")) {
    return json({ error: "content_type" }, 415, cors);
  }
  const declaredLength = Number(request.headers.get("Content-Length") || 0);
  if (declaredLength > MAX_BODY_BYTES) return json({ error: "payload_too_large" }, 413, cors);
  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES) return json({ error: "payload_too_large" }, 413, cors);
  let payload;
  try { payload = JSON.parse(body); } catch { return json({ error: "invalid_json" }, 400, cors); }
  const topFields = payload && typeof payload === "object" ? Object.keys(payload) : [];
  if (!payload || Array.isArray(payload) || payload.schema_version !== 1 || payload.site_id !== env.SITE_ID ||
      topFields.some((field) => !["schema_version", "site_id", "events"].includes(field)) || !Array.isArray(payload.events)) {
    return json({ error: "invalid_batch" }, 400, cors);
  }
  if (payload.events.length < 1 || payload.events.length > MAX_BATCH_EVENTS) return json({ error: "batch_size" }, 400, cors);

  const receivedAt = now.toISOString();
  const valid = [];
  let invalid = 0;
  for (const event of payload.events) {
    const errors = validateEvent(event, { now: now.getTime(), siteId: env.SITE_ID });
    if (errors.length) invalid += 1;
    else valid.push(toStoredEvent(event, receivedAt));
  }

  let accepted = 0;
  if (valid.length) {
    const statements = valid.map((event) => env.DB.prepare(`
      INSERT OR IGNORE INTO events (
        event_uuid, occurred_at, received_at, day_cst, name, page, page_path,
        event_id, device_id, session_id, referrer, viewport, category, source,
        action, feedback_reason, acquisition_source, acquisition_format
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      event.event_uuid, event.occurred_at, event.received_at, event.day_cst,
      event.name, event.page, event.page_path, event.event_id, event.device_id,
      event.session_id, event.referrer, event.viewport, event.category,
      event.source, event.action, event.feedback_reason,
      event.acquisition_source, event.acquisition_format,
    ));
    const results = await env.DB.batch(statements);
    accepted = results.reduce((total, result) => total + Number(result?.meta?.changes || 0), 0);
  }
  const duplicates = valid.length - accepted;
  await writeIngestStats(env, {
    day: shanghaiDay(now),
    received: payload.events.length,
    accepted,
    duplicates,
    invalid,
    receivedAt,
  });
  return json({ accepted, rejected: invalid, duplicate: duplicates }, 202, cors);
}

async function adminAuthorized(request, env) {
  const hostname = new URL(request.url).hostname;
  if (env.LOCAL_DEV === "true" && ["127.0.0.1", "localhost", env.METRICS_HOST].includes(hostname)) return true;
  if (hostname !== env.ADMIN_HOST) return false;
  return sessionAuthorized(request, env);
}

async function adminLoginRateLimitState(env) {
  const limiter = env.ADMIN_LOGIN_RATE_LIMITER;
  if (!limiter || typeof limiter.limit !== "function") return "unavailable";
  try {
    const result = await limiter.limit({ key: ADMIN_LOGIN_RATE_LIMIT_KEY });
    return result?.success === true ? "allowed" : "limited";
  } catch {
    return "unavailable";
  }
}

export async function loadDashboardData(env, days, now = new Date()) {
  const rangeDays = [7, 30, 90].includes(Number(days)) ? Number(days) : 30;
  const today = shanghaiDay(now);
  const start = addDays(today, -(rangeDays - 1));
  const measurementStart = env.MEASUREMENT_START_DATE || today;
  const goalStart = measurementStart > addDays(today, -89) ? measurementStart : addDays(today, -89);
  const queryStart = goalStart < start ? goalStart : start;
  const [dailyResult, pagesResult, referrersResult, acquisitionResult, bounds, quality] = await Promise.all([
    env.DB.prepare(`
      SELECT day_cst AS day,
             SUM(CASE WHEN name = 'page_view' THEN 1 ELSE 0 END) AS pv,
             COUNT(DISTINCT CASE WHEN name = 'page_view' THEN device_id END) AS uv
      FROM events WHERE day_cst >= ? GROUP BY day_cst ORDER BY day_cst
    `).bind(queryStart).all(),
    env.DB.prepare(`
      SELECT page_path, COUNT(*) AS pv, COUNT(DISTINCT device_id) AS uv
      FROM events
      WHERE name = 'page_view' AND day_cst >= ? AND page_path IS NOT NULL
      GROUP BY page_path ORDER BY uv DESC, pv DESC, page_path LIMIT 12
    `).bind(start).all(),
    env.DB.prepare(`
      SELECT referrer, COUNT(*) AS pv, COUNT(DISTINCT device_id) AS uv
      FROM events WHERE name = 'page_view' AND day_cst >= ?
      GROUP BY referrer ORDER BY uv DESC, pv DESC
    `).bind(start).all(),
    env.DB.prepare(`
      SELECT acquisition_source, COALESCE(acquisition_format, 'unknown') AS acquisition_format,
             COUNT(*) AS pv, COUNT(DISTINCT device_id) AS uv
      FROM events
      WHERE name = 'page_view' AND day_cst >= ? AND acquisition_source IS NOT NULL
      GROUP BY acquisition_source, acquisition_format
      ORDER BY uv DESC, pv DESC, acquisition_source, acquisition_format
    `).bind(start).all(),
    env.DB.prepare("SELECT MIN(received_at) AS first_event_at, MAX(received_at) AS last_event_at FROM events WHERE name = 'page_view'").first(),
    env.DB.prepare(`
      SELECT COALESCE(SUM(requests), 0) AS requests,
             COALESCE(SUM(received_events), 0) AS received_events,
             COALESCE(SUM(accepted_events), 0) AS accepted_events,
             COALESCE(SUM(duplicate_events), 0) AS duplicate_events,
             COALESCE(SUM(invalid_events), 0) AS invalid_events
      FROM ingest_stats WHERE day_cst >= ?
    `).bind(start).first(),
  ]);
  return buildDashboardSummary({
    daily: resultRows(dailyResult),
    top_pages: resultRows(pagesResult),
    referrers: resultRows(referrersResult),
    acquisition: resultRows(acquisitionResult),
    bounds: bounds || {},
    quality: quality || {},
  }, {
    now,
    days: rangeDays,
    targetUv: integerSetting(env.TARGET_DAILY_UV, 10, 1, 100_000),
    targetDays: integerSetting(env.TARGET_STREAK_DAYS, 14, 1, 365),
    measurementStart,
  });
}

async function handleAdmin(request, env) {
  const url = new URL(request.url);
  const local = env.LOCAL_DEV === "true";
  const authorized = await adminAuthorized(request, env);

  if (!local && url.pathname === "/login") {
    if (request.method === "GET") {
      if (authorized) return new Response(null, { status: 303, headers: adminHeaders("text/plain; charset=utf-8", { Location: "/" }) });
      return new Response(LOGIN_HTML(), { headers: adminHeaders("text/html; charset=utf-8") });
    }
    if (request.method === "POST") {
      const contentType = String(request.headers.get("Content-Type") || "").toLowerCase();
      const declaredLength = Number(request.headers.get("Content-Length") || 0);
      if (!contentType.startsWith("application/x-www-form-urlencoded") || declaredLength > 2048) {
        return new Response("Invalid request", { status: 400, headers: adminHeaders("text/plain; charset=utf-8") });
      }
      const rateLimitState = await adminLoginRateLimitState(env);
      if (rateLimitState === "unavailable") {
        return new Response("Authentication is temporarily unavailable", {
          status: 503,
          headers: adminHeaders("text/plain; charset=utf-8", { "Retry-After": String(ADMIN_LOGIN_RATE_LIMIT_SECONDS) }),
        });
      }
      if (rateLimitState === "limited") {
        return new Response("Too many login attempts", {
          status: 429,
          headers: adminHeaders("text/plain; charset=utf-8", { "Retry-After": String(ADMIN_LOGIN_RATE_LIMIT_SECONDS) }),
        });
      }
      const body = await request.text();
      if (new TextEncoder().encode(body).byteLength > 2048) {
        return new Response("Invalid request", { status: 400, headers: adminHeaders("text/plain; charset=utf-8") });
      }
      const password = new URLSearchParams(body).get("password") || "";
      if (!await passwordMatches(password, env.ADMIN_PASSWORD_HASH)) {
        return new Response(LOGIN_HTML("密码不正确，请重试。"), { status: 401, headers: adminHeaders("text/html; charset=utf-8") });
      }
      try {
        const cookie = await createSessionCookie(env);
        return new Response(null, { status: 303, headers: adminHeaders("text/plain; charset=utf-8", { Location: "/", "Set-Cookie": cookie }) });
      } catch {
        return new Response("Authentication is not configured", { status: 503, headers: adminHeaders("text/plain; charset=utf-8") });
      }
    }
    return new Response("Method not allowed", { status: 405, headers: adminHeaders("text/plain; charset=utf-8", { Allow: "GET, POST" }) });
  }

  if (!authorized) {
    if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/assets/")) {
      return new Response("Authentication required", { status: 401, headers: adminHeaders("text/plain; charset=utf-8") });
    }
    return new Response(null, { status: 303, headers: adminHeaders("text/plain; charset=utf-8", { Location: "/login" }) });
  }

  if (!local && url.pathname === "/logout") {
    if (request.method !== "POST") return new Response("Method not allowed", { status: 405, headers: adminHeaders("text/plain; charset=utf-8", { Allow: "POST" }) });
    return new Response(null, { status: 303, headers: adminHeaders("text/plain; charset=utf-8", { Location: "/login", "Set-Cookie": clearSessionCookie() }) });
  }

  if (request.method !== "GET") return new Response("Method not allowed", { status: 405, headers: adminHeaders("text/plain; charset=utf-8", { Allow: "GET" }) });
  if (url.pathname === "/" || url.pathname === "/index.html") {
    return new Response(DASHBOARD_HTML, { headers: adminHeaders("text/html; charset=utf-8") });
  }
  if (url.pathname === "/assets/dashboard.js") {
    return new Response(DASHBOARD_JS, { headers: adminHeaders("text/javascript; charset=utf-8") });
  }
  if (url.pathname === "/api/dashboard") {
    const data = await loadDashboardData(env, url.searchParams.get("days"));
    return new Response(JSON.stringify(data), { headers: adminHeaders("application/json; charset=utf-8") });
  }
  return new Response("Not found", { status: 404, headers: adminHeaders("text/plain; charset=utf-8") });
}

export async function handleRequest(request, env, ctx) {
  const url = new URL(request.url);
  const local = env.LOCAL_DEV === "true";
  if ((url.hostname === env.METRICS_HOST || local) && url.pathname === "/v1/events") return handleIngest(request, env);
  if (url.hostname === env.METRICS_HOST && url.pathname === "/healthz" && request.method === "GET") {
    return json({ ok: true, service: "datahot-traffic" });
  }
  if (url.hostname === env.ADMIN_HOST || local) return handleAdmin(request, env);
  return new Response("Not found", { status: 404 });
}

export default {
  fetch: handleRequest,
  async scheduled(_controller, env) {
    const retentionDays = integerSetting(env.RETENTION_DAYS, 90, 30, 365);
    const cutoff = new Date(Date.now() - retentionDays * 86_400_000).toISOString();
    const statsCutoff = shanghaiDay(new Date(Date.now() - Math.max(120, retentionDays) * 86_400_000));
    await env.DB.batch([
      env.DB.prepare("DELETE FROM events WHERE occurred_at < ?").bind(cutoff),
      env.DB.prepare("DELETE FROM ingest_stats WHERE day_cst < ?").bind(statsCutoff),
    ]);
  },
};
