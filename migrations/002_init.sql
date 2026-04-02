-- v1.1 — colonna ua_kind (docs/DATA_MODEL.md)

CREATE TABLE fact_googlebot_daily_query_status_new (
  snapshot_date_utc TEXT NOT NULL,
  ua_kind TEXT NOT NULL CHECK (ua_kind IN ('googlebot', 'googlebot_image', 'googlebot_other')),
  has_query_string INTEGER NOT NULL CHECK (has_query_string IN (0, 1)),
  edge_response_status INTEGER NOT NULL,
  hits INTEGER NOT NULL,
  ingested_at TEXT NOT NULL,
  source_run_id INTEGER NOT NULL,
  PRIMARY KEY (snapshot_date_utc, ua_kind, has_query_string, edge_response_status),
  FOREIGN KEY (source_run_id) REFERENCES ingestion_runs(id)
);

INSERT INTO fact_googlebot_daily_query_status_new
  (snapshot_date_utc, ua_kind, has_query_string, edge_response_status, hits, ingested_at, source_run_id)
SELECT snapshot_date_utc, 'googlebot', has_query_string, edge_response_status, hits, ingested_at, source_run_id
FROM fact_googlebot_daily_query_status;

DROP TABLE fact_googlebot_daily_query_status;
ALTER TABLE fact_googlebot_daily_query_status_new RENAME TO fact_googlebot_daily_query_status;

CREATE INDEX idx_fact_date ON fact_googlebot_daily_query_status (snapshot_date_utc);
CREATE INDEX idx_fact_date_ua ON fact_googlebot_daily_query_status (snapshot_date_utc, ua_kind);
CREATE INDEX idx_fact_date_ua_bucket ON fact_googlebot_daily_query_status (snapshot_date_utc, ua_kind, has_query_string);
CREATE INDEX idx_fact_date_status ON fact_googlebot_daily_query_status (snapshot_date_utc, edge_response_status);
