export const EVENT_NAMES = new Set([
  "session_start", "page_view", "list_exposure", "detail_click", "outbound_click",
  "favorite_toggle", "content_feedback", "share_action", "search", "filter",
  "weekly_brief_click", "daily_brief_click",
]);

export const ALLOWED_FIELDS = new Set([
  "schema_version", "event_uuid", "name", "ts", "environment", "site_id",
  "page", "page_path", "event_id", "category", "source", "session_id", "device_id",
  "sequence", "viewport", "referrer", "action", "filter", "query_bucket",
  "result_count", "feedback_reason", "acquisition_source", "acquisition_format",
]);

const REQUIRED_FIELDS = new Set([
  "schema_version", "event_uuid", "name", "ts", "environment", "site_id",
  "page", "session_id", "device_id", "sequence", "viewport", "referrer",
]);
const PAGES = new Set(["home", "for-me", "cases", "weekly", "daily", "topics", "topic", "classics", "hot", "favorites", "sources", "detail", "privacy", "other"]);
const CATEGORIES = new Set(["agent", "platform", "bi", "product", "insight", ""]);
const REFERRERS = new Set(["direct", "internal", "search", "social", "other"]);
const VIEWPORTS = new Set(["small", "medium", "large"]);
const ACQUISITION_SOURCES = new Set(["bluesky", "x", ""]);
const ACQUISITION_FORMATS = new Set(["card", "text", ""]);
const EVENT_ID_REQUIRED = new Set(["list_exposure", "detail_click", "outbound_click", "favorite_toggle", "content_feedback", "share_action"]);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const EVENT_ID_RE = /^[a-f0-9]{12}$/;
const PAGE_PATH_RE = /^\/(?:|(?:index|for-me|cases|weekly|daily|topics|classics|hot|favorites|sources|privacy)\.html|topics\/[a-z0-9-]{1,60}\.html|weekly\/\d{4}-W\d{2}\.html|e\/[a-f0-9]{12}\.html)$/;
const SAFE_TEXT_RE = /^[^\u0000-\u001f\u007f]*$/;

export function shanghaiDay(value) {
  return new Date(new Date(value).getTime() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

export function safePagePath(value) {
  const path = String(value || "");
  return path.length <= 160 && PAGE_PATH_RE.test(path) ? path : "";
}

export function validateEvent(event, options = {}) {
  const errors = [];
  const now = Number(options.now ?? Date.now());
  const siteId = String(options.siteId || "datahot");
  if (!event || typeof event !== "object" || Array.isArray(event)) return ["not_object"];
  if (Object.keys(event).some((field) => !ALLOWED_FIELDS.has(field))) errors.push("unknown_fields");
  if ([...REQUIRED_FIELDS].some((field) => !Object.hasOwn(event, field))) errors.push("missing_fields");
  if (event.schema_version !== 1) errors.push("schema_version");
  if (!EVENT_NAMES.has(event.name)) errors.push("event_name");
  for (const field of ["event_uuid", "session_id", "device_id"]) {
    if (!UUID_RE.test(String(event[field] || ""))) errors.push(field);
  }
  const occurredAt = Date.parse(String(event.ts || ""));
  if (!Number.isFinite(occurredAt)) errors.push("timestamp");
  else {
    if (occurredAt > now + 10 * 60 * 1000) errors.push("timestamp_future");
    if (occurredAt < now - 48 * 60 * 60 * 1000) errors.push("timestamp_stale");
  }
  if (event.environment !== "production") errors.push("environment");
  if (event.site_id !== siteId) errors.push("site_id");
  if (!PAGES.has(event.page)) errors.push("page");
  const pagePath = safePagePath(event.page_path);
  if (event.name === "page_view" && !pagePath) errors.push("page_path_required");
  else if (event.page_path && !pagePath) errors.push("page_path");
  const eventId = String(event.event_id || "");
  if (EVENT_ID_REQUIRED.has(event.name) && !EVENT_ID_RE.test(eventId)) errors.push("event_id_required");
  else if (eventId && !EVENT_ID_RE.test(eventId)) errors.push("event_id");
  if (!CATEGORIES.has(String(event.category || ""))) errors.push("category");
  for (const [field, limit] of [["source", 80], ["filter", 40]]) {
    const value = String(event[field] || "");
    if (value.length > limit || !SAFE_TEXT_RE.test(value)) errors.push(field);
  }
  if (!Number.isInteger(event.sequence) || event.sequence < 1 || event.sequence > 1_000_000) errors.push("sequence");
  if (!VIEWPORTS.has(event.viewport)) errors.push("viewport");
  if (!REFERRERS.has(event.referrer)) errors.push("referrer");
  if (!ACQUISITION_SOURCES.has(String(event.acquisition_source || ""))) errors.push("acquisition_source");
  if (!ACQUISITION_FORMATS.has(String(event.acquisition_format || ""))) errors.push("acquisition_format");
  if (Boolean(event.acquisition_source) !== Boolean(event.acquisition_format)) errors.push("acquisition_pair");
  if (event.action && ![
    "add", "remove", "useful", "not_useful",
    "open", "copy", "native", "poster", "save",
  ].includes(event.action)) errors.push("action");
  if (event.query_bucket && !["1-3", "4-8", "9+"].includes(event.query_bucket)) errors.push("query_bucket");
  if (event.name === "favorite_toggle" && !["add", "remove"].includes(event.action)) errors.push("action_required");
  if (event.name === "content_feedback" && !["useful", "not_useful"].includes(event.action)) errors.push("action_required");
  if (event.name === "share_action" && !["open", "copy", "native", "poster", "save"].includes(event.action)) errors.push("action_required");
  if (event.feedback_reason && !["solid", "relevant", "novel", "source_discovery", "irrelevant", "shallow", "marketing", "duplicate", "body_quality"].includes(event.feedback_reason)) errors.push("feedback_reason");
  if (event.name === "search" && !["1-3", "4-8", "9+"].includes(event.query_bucket)) errors.push("query_bucket_required");
  if (Object.hasOwn(event, "result_count") && (!Number.isInteger(event.result_count) || event.result_count < 0 || event.result_count > 100_000)) errors.push("result_count");
  return [...new Set(errors)];
}

export function toStoredEvent(event, receivedAt) {
  return {
    event_uuid: event.event_uuid,
    occurred_at: new Date(event.ts).toISOString(),
    received_at: receivedAt,
    day_cst: shanghaiDay(event.ts),
    name: event.name,
    page: event.page,
    page_path: safePagePath(event.page_path) || null,
    event_id: event.event_id || null,
    device_id: event.device_id,
    session_id: event.session_id,
    referrer: event.referrer,
    viewport: event.viewport,
    category: event.category || null,
    source: event.source || null,
    action: event.action || null,
    feedback_reason: event.feedback_reason || null,
    acquisition_source: event.acquisition_source || null,
    acquisition_format: event.acquisition_format || null,
  };
}
