CREATE TABLE IF NOT EXISTS events (
  event_uuid TEXT PRIMARY KEY,
  occurred_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  day_cst TEXT NOT NULL,
  name TEXT NOT NULL,
  page TEXT NOT NULL,
  page_path TEXT,
  event_id TEXT,
  device_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  referrer TEXT NOT NULL,
  viewport TEXT NOT NULL,
  category TEXT,
  source TEXT,
  action TEXT,
  feedback_reason TEXT
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_events_day_name ON events(day_cst, name);
CREATE INDEX IF NOT EXISTS idx_events_day_device ON events(day_cst, device_id);
CREATE INDEX IF NOT EXISTS idx_events_day_path ON events(day_cst, page_path);
CREATE INDEX IF NOT EXISTS idx_events_received ON events(received_at);

CREATE TABLE IF NOT EXISTS ingest_stats (
  day_cst TEXT PRIMARY KEY,
  requests INTEGER NOT NULL DEFAULT 0,
  received_events INTEGER NOT NULL DEFAULT 0,
  accepted_events INTEGER NOT NULL DEFAULT 0,
  duplicate_events INTEGER NOT NULL DEFAULT 0,
  invalid_events INTEGER NOT NULL DEFAULT 0,
  last_received_at TEXT NOT NULL
) WITHOUT ROWID;
