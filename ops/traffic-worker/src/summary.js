import { shanghaiDay } from "./schema.js";

function addDays(day, amount) {
  const date = new Date(`${day}T00:00:00.000Z`);
  date.setUTCDate(date.getUTCDate() + amount);
  return date.toISOString().slice(0, 10);
}

function daysBetween(start, end) {
  const days = [];
  for (let day = start; day <= end; day = addDays(day, 1)) days.push(day);
  return days;
}

function asNumber(value) {
  return Number(value || 0);
}

export function buildDashboardSummary(raw, options = {}) {
  const now = options.now || new Date();
  const days = Math.max(7, Math.min(90, Number(options.days || 30)));
  const targetUv = Math.max(1, Number(options.targetUv || 10));
  const targetDays = Math.max(1, Number(options.targetDays || 14));
  const today = shanghaiDay(now);
  const start = addDays(today, -(days - 1));
  const measurementStart = String(options.measurementStart || today);
  const values = new Map((raw.daily || []).map((row) => [row.day, { pv: asNumber(row.pv), uv: asNumber(row.uv) }]));
  const hasMeasuredEvent = Boolean(raw.bounds?.first_event_at);
  const daily = daysBetween(start, today).map((day) => {
    const measured = hasMeasuredEvent && day >= measurementStart;
    const value = values.get(day);
    return {
      day,
      pv: measured ? asNumber(value?.pv) : null,
      uv: measured ? asNumber(value?.uv) : null,
      complete: day < today && measured,
      target_met: day < today && measured ? asNumber(value?.uv) >= targetUv : null,
    };
  });
  const completed = daily.filter((row) => row.complete);
  const goalEnd = addDays(today, -1);
  const goalDaily = hasMeasuredEvent && measurementStart <= goalEnd
    ? daysBetween(measurementStart, goalEnd).map((day) => ({ day, uv: asNumber(values.get(day)?.uv) }))
    : [];
  let streak = 0;
  let bestStreak = 0;
  for (const row of goalDaily) {
    streak = row.uv >= targetUv ? streak + 1 : 0;
    bestStreak = Math.max(bestStreak, streak);
  }
  const last7 = completed.slice(-7);
  const yesterday = completed.at(-1) || null;
  const todayRow = daily.at(-1);
  const sevenDayAverageUv = last7.length
    ? Math.round((last7.reduce((sum, row) => sum + row.uv, 0) / last7.length) * 10) / 10
    : null;
  const firstEventAt = raw.bounds?.first_event_at || null;
  const lastEventAt = raw.bounds?.last_event_at || null;
  const staleHours = lastEventAt ? (now.getTime() - Date.parse(lastEventAt)) / 3_600_000 : null;
  const collectionState = !firstEventAt ? "waiting_for_first_event" : staleHours > 24 ? "stale" : "collecting";
  const quality = raw.quality || {};
  const received = asNumber(quality.received_events);
  const invalid = asNumber(quality.invalid_events);
  const duplicate = asNumber(quality.duplicate_events);
  const accepted = asNumber(quality.accepted_events);
  const valid = accepted + duplicate;
  return {
    generated_at: now.toISOString(),
    timezone: "Asia/Shanghai",
    range_days: days,
    measurement_start_date: measurementStart,
    measurement: {
      state: collectionState,
      first_event_at: firstEventAt,
      last_event_at: lastEventAt,
      measured_uv_definition: "当日产生合法 page_view 的 30 天随机设备 ID 去重数",
      exclusions: "GPC、DNT、主动退出、测试域名、机器人未执行脚本及非法事件不计入",
    },
    goal: {
      daily_uv_target: targetUv,
      required_streak_days: targetDays,
      current_streak_days: streak,
      best_streak_days: bestStreak,
      remaining_days: bestStreak >= targetDays ? 0 : Math.max(0, targetDays - streak),
      achieved: bestStreak >= targetDays,
      qualifying_days_total: goalDaily.filter((row) => row.uv >= targetUv).length,
    },
    headline: {
      today: { day: todayRow.day, pv: todayRow.pv, uv: todayRow.uv, partial: true },
      yesterday,
      seven_day_average_uv: sevenDayAverageUv,
    },
    daily,
    top_pages: (raw.top_pages || []).map((row) => ({ page_path: row.page_path, pv: asNumber(row.pv), uv: asNumber(row.uv) })),
    referrers: (raw.referrers || []).map((row) => ({ referrer: row.referrer, pv: asNumber(row.pv), uv: asNumber(row.uv) })),
    quality: {
      requests: asNumber(quality.requests),
      received_events: received,
      accepted_events: accepted,
      duplicate_events: duplicate,
      invalid_events: invalid,
      accepted_rate: received ? Math.round((valid / received) * 10000) / 100 : null,
    },
  };
}

export { addDays };
