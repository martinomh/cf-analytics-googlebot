-- Schema v1.0 — allineato a docs/DATA_MODEL.md

CREATE TABLE IF NOT EXISTS ingestion_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  target_date_utc TEXT NOT NULL,
  rows_written INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS fact_googlebot_daily_query_status (
  snapshot_date_utc TEXT NOT NULL,
  has_query_string INTEGER NOT NULL CHECK (has_query_string IN (0, 1)),
  edge_response_status INTEGER NOT NULL,
  hits INTEGER NOT NULL,
  ingested_at TEXT NOT NULL,
  source_run_id INTEGER NOT NULL,
  PRIMARY KEY (snapshot_date_utc, has_query_string, edge_response_status),
  FOREIGN KEY (source_run_id) REFERENCES ingestion_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_fact_date ON fact_googlebot_daily_query_status (snapshot_date_utc);
CREATE INDEX IF NOT EXISTS idx_fact_date_bucket ON fact_googlebot_daily_query_status (snapshot_date_utc, has_query_string);
CREATE INDEX IF NOT EXISTS idx_fact_date_status ON fact_googlebot_daily_query_status (snapshot_date_utc, edge_response_status);
