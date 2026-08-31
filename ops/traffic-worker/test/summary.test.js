import assert from "node:assert/strict";
import test from "node:test";
import { buildDashboardSummary } from "../src/summary.js";

test("goal streak uses completed Shanghai days and excludes today", () => {
  const daily = [];
  for (let day = 10; day <= 23; day += 1) daily.push({ day: `2026-08-${day}`, pv: 20 + day, uv: 10 });
  daily.push({ day: "2026-08-24", pv: 8, uv: 4 });
  daily.push({ day: "2026-08-25", pv: 22, uv: 11 });
  daily.push({ day: "2026-08-26", pv: 23, uv: 12 });
  daily.push({ day: "2026-08-27", pv: 24, uv: 13 });
  daily.push({ day: "2026-08-28", pv: 1, uv: 1 });
  const result = buildDashboardSummary({
    daily,
    top_pages: [{ page_path: "/", pv: 10, uv: 7 }],
    referrers: [{ referrer: "direct", pv: 10, uv: 7 }],
    acquisition: [{ acquisition_source: "bluesky", acquisition_format: "card", pv: 4, uv: 3 }],
    bounds: { first_event_at: "2026-08-10T00:00:00Z", last_event_at: "2026-08-28T07:59:00Z" },
    quality: { received_events: 100, accepted_events: 95, duplicate_events: 3, invalid_events: 2 },
  }, {
    now: new Date("2026-08-28T08:00:00Z"), days: 30, targetUv: 10, targetDays: 14,
    measurementStart: "2026-08-10",
  });
  assert.equal(result.goal.current_streak_days, 3);
  assert.equal(result.goal.best_streak_days, 14);
  assert.equal(result.goal.achieved, true);
  assert.equal(result.headline.today.partial, true);
  assert.equal(result.headline.yesterday.uv, 13);
  assert.equal(result.quality.accepted_rate, 98);
  assert.match(result.measurement.exclusions, /自动化浏览器/);
  assert.deepEqual(result.acquisition, [{ source: "bluesky", format: "card", pv: 4, uv: 3 }]);
});

test("no events are reported as unavailable rather than invented zero traffic", () => {
  const result = buildDashboardSummary({ daily: [], top_pages: [], referrers: [], acquisition: [], bounds: {}, quality: {} }, {
    now: new Date("2026-08-28T08:00:00Z"), days: 7, measurementStart: "2026-08-29",
  });
  assert.equal(result.measurement.state, "waiting_for_first_event");
  assert.equal(result.headline.today.uv, null);
  assert.equal(result.headline.today.pv, null);
  assert.equal(result.quality.accepted_rate, null);
  assert.deepEqual(result.acquisition, []);
});
