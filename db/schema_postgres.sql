CREATE TABLE IF NOT EXISTS issuers (
  issuer_id BIGINT PRIMARY KEY,
  issuer_name TEXT NOT NULL,
  lei TEXT,
  country_code TEXT,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_issuers_lei
ON issuers (lei)
WHERE lei IS NOT NULL;

CREATE TABLE IF NOT EXISTS securities (
  security_id BIGINT PRIMARY KEY,
  issuer_id BIGINT NOT NULL REFERENCES issuers (issuer_id),
  instrument_type TEXT NOT NULL,
  security_name TEXT,
  share_class TEXT,
  currency_code TEXT,
  country_of_issue TEXT,
  primary_mic TEXT,
  active_from TEXT,
  active_to TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_securities_issuer ON securities (issuer_id);
CREATE INDEX IF NOT EXISTS ix_securities_type ON securities (instrument_type);

CREATE TABLE IF NOT EXISTS security_identifiers (
  identifier_id BIGINT PRIMARY KEY,
  security_id BIGINT NOT NULL REFERENCES securities (security_id),
  id_type TEXT NOT NULL,
  id_value TEXT NOT NULL,
  mic TEXT,
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  source_system TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_identifiers_lookup
ON security_identifiers (id_type, id_value, mic, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS ix_identifiers_security
ON security_identifiers (security_id, id_type);
CREATE UNIQUE INDEX IF NOT EXISTS ux_identifiers_type_value
ON security_identifiers (id_type, id_value);
CREATE UNIQUE INDEX IF NOT EXISTS ux_identifiers_version
ON security_identifiers (security_id, id_type, id_value, COALESCE(mic, ''), valid_from);

CREATE TABLE IF NOT EXISTS corporate_actions (
  action_id BIGINT PRIMARY KEY,
  security_id BIGINT NOT NULL REFERENCES securities (security_id),
  action_type TEXT NOT NULL,
  ex_date TEXT,
  record_date TEXT,
  pay_date TEXT,
  split_factor_num INTEGER,
  split_factor_den INTEGER,
  details_json TEXT,
  source_system TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_corp_actions_security_date
ON corporate_actions (security_id, ex_date);

CREATE TABLE IF NOT EXISTS security_alias_links (
  link_id BIGINT PRIMARY KEY,
  from_security_id BIGINT NOT NULL REFERENCES securities (security_id),
  to_security_id BIGINT NOT NULL REFERENCES securities (security_id),
  link_type TEXT NOT NULL,
  effective_date TEXT NOT NULL,
  ratio_num DOUBLE PRECISION,
  ratio_den DOUBLE PRECISION,
  cash_component DOUBLE PRECISION,
  source_system TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_alias_from_date
ON security_alias_links (from_security_id, effective_date);
CREATE INDEX IF NOT EXISTS ix_alias_to_date
ON security_alias_links (to_security_id, effective_date);
CREATE UNIQUE INDEX IF NOT EXISTS ux_alias_edge
ON security_alias_links (from_security_id, to_security_id, link_type, effective_date);

CREATE TABLE IF NOT EXISTS managers (
  manager_id BIGINT PRIMARY KEY,
  cik TEXT,
  manager_name TEXT NOT NULL,
  normalized_name TEXT,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_managers_cik
ON managers (cik)
WHERE cik IS NOT NULL;

CREATE TABLE IF NOT EXISTS manager_universe (
  manager_id BIGINT PRIMARY KEY REFERENCES managers (manager_id),
  rank INTEGER NOT NULL,
  total_value_usd DOUBLE PRECISION,
  as_of_report_date TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'AGG_MANAGER_QUARTER',
  is_active INTEGER NOT NULL DEFAULT 1,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_manager_universe_rank
ON manager_universe (rank, is_active);

CREATE TABLE IF NOT EXISTS filings (
  filing_id BIGINT PRIMARY KEY,
  accession_no TEXT NOT NULL UNIQUE,
  form_type TEXT NOT NULL,
  cik TEXT,
  manager_id BIGINT REFERENCES managers (manager_id),
  filed_at TEXT NOT NULL,
  period_end_date TEXT,
  sec_url TEXT NOT NULL,
  is_amendment INTEGER NOT NULL DEFAULT 0,
  supersedes_filing_id BIGINT REFERENCES filings (filing_id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_filings_form_period
ON filings (form_type, period_end_date, filed_at);
CREATE INDEX IF NOT EXISTS ix_filings_manager_period
ON filings (manager_id, period_end_date);
CREATE INDEX IF NOT EXISTS ix_filings_form_filed_at
ON filings (form_type, filed_at);

CREATE TABLE IF NOT EXISTS holdings_13f (
  holding_13f_id BIGINT PRIMARY KEY,
  filing_id BIGINT NOT NULL REFERENCES filings (filing_id),
  manager_id BIGINT NOT NULL REFERENCES managers (manager_id),
  security_id BIGINT REFERENCES securities (security_id),
  report_date TEXT NOT NULL,
  issuer_name_raw TEXT,
  class_title_raw TEXT,
  cusip_raw TEXT,
  ticker_raw TEXT,
  value_usd_thousands DOUBLE PRECISION,
  shares DOUBLE PRECISION,
  share_type TEXT,
  option_type TEXT,
  investment_discretion TEXT,
  other_manager_text TEXT,
  voting_sole DOUBLE PRECISION,
  voting_shared DOUBLE PRECISION,
  voting_none DOUBLE PRECISION,
  row_hash TEXT NOT NULL,
  mapping_status TEXT NOT NULL DEFAULT 'UNMAPPED',
  mapping_confidence DOUBLE PRECISION,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_13f_manager_security_qtr
ON holdings_13f (manager_id, security_id, report_date);
CREATE INDEX IF NOT EXISTS ix_13f_security_qtr
ON holdings_13f (security_id, report_date);
CREATE INDEX IF NOT EXISTS ix_13f_report_date
ON holdings_13f (report_date);
CREATE UNIQUE INDEX IF NOT EXISTS ux_13f_row_dedup
ON holdings_13f (filing_id, row_hash);

CREATE TABLE IF NOT EXISTS beneficial_ownership_events (
  bo_event_id BIGINT PRIMARY KEY,
  filing_id BIGINT NOT NULL REFERENCES filings (filing_id),
  manager_id BIGINT REFERENCES managers (manager_id),
  security_id BIGINT REFERENCES securities (security_id),
  report_date TEXT,
  event_type TEXT NOT NULL,
  percent_beneficial_owned DOUBLE PRECISION,
  shares_beneficial_owned DOUBLE PRECISION,
  cusip_raw TEXT,
  issuer_name_raw TEXT,
  ticker_raw TEXT,
  details_json TEXT,
  mapping_status TEXT NOT NULL DEFAULT 'UNMAPPED',
  mapping_confidence DOUBLE PRECISION,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_bo_security_date
ON beneficial_ownership_events (security_id, report_date);
CREATE INDEX IF NOT EXISTS ix_bo_manager_date
ON beneficial_ownership_events (manager_id, report_date);
CREATE INDEX IF NOT EXISTS ix_bo_filing_id
ON beneficial_ownership_events (filing_id);

CREATE TABLE IF NOT EXISTS watchlists (
  watchlist_id TEXT PRIMARY KEY,
  owner_user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  watchlist_type TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_watchlists_owner
ON watchlists (owner_user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_watchlists_owner_name
ON watchlists (owner_user_id, LOWER(name));

CREATE TABLE IF NOT EXISTS watchlist_items (
  watchlist_item_id TEXT PRIMARY KEY,
  watchlist_id TEXT NOT NULL REFERENCES watchlists (watchlist_id) ON DELETE CASCADE,
  item_type TEXT NOT NULL,
  item_key TEXT NOT NULL,
  item_label TEXT,
  item_subtitle TEXT,
  metadata_json TEXT,
  added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_watchlist_items_unique
ON watchlist_items (watchlist_id, item_type, item_key);

CREATE INDEX IF NOT EXISTS ix_watchlist_items_watchlist
ON watchlist_items (watchlist_id, added_at DESC);

CREATE TABLE IF NOT EXISTS webhook_subscriptions (
  webhook_subscription_id TEXT PRIMARY KEY,
  owner_user_id TEXT NOT NULL,
  watchlist_id TEXT NOT NULL REFERENCES watchlists (watchlist_id) ON DELETE CASCADE,
  endpoint_url TEXT NOT NULL,
  endpoint_secret TEXT,
  include_13dg INTEGER NOT NULL DEFAULT 1,
  include_insider INTEGER NOT NULL DEFAULT 1,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_webhook_subscriptions_owner
ON webhook_subscriptions (owner_user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_webhook_subscriptions_owner_watchlist_endpoint
ON webhook_subscriptions (owner_user_id, watchlist_id, endpoint_url);

CREATE TABLE IF NOT EXISTS webhook_delivery_log (
  webhook_delivery_id TEXT PRIMARY KEY,
  webhook_subscription_id TEXT NOT NULL REFERENCES webhook_subscriptions (webhook_subscription_id) ON DELETE CASCADE,
  owner_user_id TEXT NOT NULL,
  event_source TEXT NOT NULL,
  event_key TEXT NOT NULL,
  event_ts TEXT,
  status TEXT NOT NULL,
  provider_message_id TEXT,
  http_status INTEGER,
  error_text TEXT,
  payload_json TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  delivered_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_webhook_delivery_owner_ts
ON webhook_delivery_log (owner_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_webhook_delivery_event
ON webhook_delivery_log (webhook_subscription_id, event_source, event_key, status, created_at DESC);

CREATE TABLE IF NOT EXISTS api_budgets (
  provider TEXT PRIMARY KEY,
  max_per_minute INTEGER,
  max_per_day INTEGER,
  burst_per_second INTEGER,
  notes TEXT,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_request_log (
  request_id BIGINT PRIMARY KEY,
  provider TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  request_ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status_code INTEGER,
  ok INTEGER NOT NULL,
  latency_ms INTEGER,
  cache_hit INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_api_log_provider_ts
ON api_request_log (provider, request_ts);

CREATE TABLE IF NOT EXISTS cusip_ticker_xwalk (
  cusip TEXT PRIMARY KEY,
  ticker TEXT,
  figi TEXT,
  name TEXT,
  mic TEXT,
  source TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
  first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_cusip_xwalk_ticker
ON cusip_ticker_xwalk (ticker);

CREATE TABLE IF NOT EXISTS pipeline_run_events (
  run_id TEXT NOT NULL,
  event_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT,
  metrics_json TEXT
);

CREATE INDEX IF NOT EXISTS ix_pipeline_events_run_ts
ON pipeline_run_events (run_id, event_ts);

CREATE TABLE IF NOT EXISTS agg_security_quarter (
  security_id BIGINT NOT NULL REFERENCES securities (security_id),
  report_date TEXT NOT NULL,
  holders_count INTEGER NOT NULL,
  total_shares DOUBLE PRECISION,
  total_value_usd DOUBLE PRECISION,
  top10_shares DOUBLE PRECISION,
  top10_pct DOUBLE PRECISION,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (security_id, report_date)
);

CREATE TABLE IF NOT EXISTS agg_manager_quarter (
  manager_id BIGINT NOT NULL REFERENCES managers (manager_id),
  report_date TEXT NOT NULL,
  positions_count INTEGER NOT NULL,
  total_value_usd DOUBLE PRECISION,
  top10_value_pct DOUBLE PRECISION,
  turnover_ratio DOUBLE PRECISION,
  new_positions_count INTEGER,
  exited_positions_count INTEGER,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (manager_id, report_date)
);
