ALTER TABLE events ADD COLUMN acquisition_source TEXT;
ALTER TABLE events ADD COLUMN acquisition_format TEXT;

CREATE INDEX IF NOT EXISTS idx_events_day_acquisition
ON events(day_cst, acquisition_source, acquisition_format);
