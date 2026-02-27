PRAGMA foreign_keys = ON;

-- Issuer/company entity. One issuer can have many tradable securities.
CREATE TABLE IF NOT EXISTS issuers (
  issuer_id INTEGER PRIMARY KEY,
  issuer_name TEXT NOT NULL,
  lei TEXT,
  country_code TEXT,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_issuers_lei
ON issuers (lei)
WHERE lei IS NOT NULL;

-- Tradable instrument/share class entity.
CREATE TABLE IF NOT EXISTS securities (
  security_id INTEGER PRIMARY KEY,
  issuer_id INTEGER NOT NULL REFERENCES issuers (issuer_id),
  instrument_type TEXT NOT NULL, -- EQUITY, ADR, ETF, BOND, OPTION...
  security_name TEXT,
  share_class TEXT,
  currency_code TEXT,
  country_of_issue TEXT,
  primary_mic TEXT,              -- exchange MIC
  active_from TEXT,              -- ISO date
  active_to TEXT,                -- ISO date
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_securities_issuer
ON securities (issuer_id);

CREATE INDEX IF NOT EXISTS ix_securities_type
ON securities (instrument_type);

-- Effective-dated identifier crosswalk.
CREATE TABLE IF NOT EXISTS security_identifiers (
  identifier_id INTEGER PRIMARY KEY,
  security_id INTEGER NOT NULL REFERENCES securities (security_id),
  id_type TEXT NOT NULL,        -- CUSIP, TICKER, ISIN, FIGI, POLYGON, AV, YF
  id_value TEXT NOT NULL,
  mic TEXT,                     -- needed to disambiguate ticker collisions
  valid_from TEXT NOT NULL,     -- ISO date
  valid_to TEXT,                -- nullable = open-ended
  source_system TEXT NOT NULL,  -- SEC, POLYGON, MANUAL...
  confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_identifiers_lookup
ON security_identifiers (id_type, id_value, mic, valid_from, valid_to);

CREATE INDEX IF NOT EXISTS ix_identifiers_security
ON security_identifiers (security_id, id_type);
CREATE UNIQUE INDEX IF NOT EXISTS ux_identifiers_type_value
ON security_identifiers (id_type, id_value);

-- This prevents exact duplicate version rows.
CREATE UNIQUE INDEX IF NOT EXISTS ux_identifiers_version
ON security_identifiers (security_id, id_type, id_value, IFNULL(mic, ''), valid_from);

-- Corporate action events attached to a security.
CREATE TABLE IF NOT EXISTS corporate_actions (
  action_id INTEGER PRIMARY KEY,
  security_id INTEGER NOT NULL REFERENCES securities (security_id),
  action_type TEXT NOT NULL,      -- SPLIT, TICKER_CHANGE, CUSIP_CHANGE, MERGER, SPINOFF, DELIST
  ex_date TEXT,
  record_date TEXT,
  pay_date TEXT,
  split_factor_num INTEGER,       -- 2 in a 2-for-1
  split_factor_den INTEGER,       -- 1 in a 2-for-1
  details_json TEXT,              -- action-specific payload
  source_system TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_corp_actions_security_date
ON corporate_actions (security_id, ex_date);

-- Explicit links across old/new security records when continuity exists.
CREATE TABLE IF NOT EXISTS security_alias_links (
  link_id INTEGER PRIMARY KEY,
  from_security_id INTEGER NOT NULL REFERENCES securities (security_id),
  to_security_id INTEGER NOT NULL REFERENCES securities (security_id),
  link_type TEXT NOT NULL,       -- TICKER_CHANGE, CUSIP_CHANGE, MERGER, SPINOFF, REORG
  effective_date TEXT NOT NULL,
  ratio_num REAL,                -- optional continuity ratio
  ratio_den REAL,
  cash_component REAL,
  source_system TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_alias_from_date
ON security_alias_links (from_security_id, effective_date);

CREATE INDEX IF NOT EXISTS ix_alias_to_date
ON security_alias_links (to_security_id, effective_date);

CREATE UNIQUE INDEX IF NOT EXISTS ux_alias_edge
ON security_alias_links (from_security_id, to_security_id, link_type, effective_date);

-- Manager/master filer table.
CREATE TABLE IF NOT EXISTS managers (
  manager_id INTEGER PRIMARY KEY,
  cik TEXT,                      -- SEC filer CIK
  manager_name TEXT NOT NULL,
  normalized_name TEXT,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_managers_cik
ON managers (cik)
WHERE cik IS NOT NULL;

-- Ranked universe of managers to track operationally.
CREATE TABLE IF NOT EXISTS manager_universe (
  manager_id INTEGER PRIMARY KEY REFERENCES managers (manager_id),
  rank INTEGER NOT NULL,
  total_value_usd REAL,
  as_of_report_date TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'AGG_MANAGER_QUARTER',
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_manager_universe_rank
ON manager_universe (rank, is_active);

-- Filing header table for 13F, 13D, 13G, NPORT.
CREATE TABLE IF NOT EXISTS filings (
  filing_id INTEGER PRIMARY KEY,
  accession_no TEXT NOT NULL UNIQUE,
  form_type TEXT NOT NULL,       -- 13F-HR, 13F-HR/A, SC 13D, SC 13G, NPORT-P
  cik TEXT,
  manager_id INTEGER REFERENCES managers (manager_id),
  filed_at TEXT NOT NULL,
  period_end_date TEXT,          -- report period date
  sec_url TEXT NOT NULL,
  is_amendment INTEGER NOT NULL DEFAULT 0 CHECK (is_amendment IN (0, 1)),
  supersedes_filing_id INTEGER REFERENCES filings (filing_id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_filings_form_period
ON filings (form_type, period_end_date, filed_at);

CREATE INDEX IF NOT EXISTS ix_filings_manager_period
ON filings (manager_id, period_end_date);

-- Raw holdings rows from 13F filings (one row per info table line).
CREATE TABLE IF NOT EXISTS holdings_13f (
  holding_13f_id INTEGER PRIMARY KEY,
  filing_id INTEGER NOT NULL REFERENCES filings (filing_id),
  manager_id INTEGER NOT NULL REFERENCES managers (manager_id),
  security_id INTEGER REFERENCES securities (security_id),
  report_date TEXT NOT NULL,     -- usually same as filing period end
  issuer_name_raw TEXT,
  class_title_raw TEXT,
  cusip_raw TEXT,
  ticker_raw TEXT,
  value_usd_thousands REAL,      -- SEC 13F field is in thousands
  shares REAL,
  share_type TEXT,               -- SH, PRN...
  option_type TEXT,              -- CALL/PUT/null
  investment_discretion TEXT,
  other_manager_text TEXT,
  voting_sole REAL,
  voting_shared REAL,
  voting_none REAL,
  row_hash TEXT NOT NULL,        -- deterministic hash of parsed row
  mapping_status TEXT NOT NULL DEFAULT 'UNMAPPED', -- MAPPED, MAPPED_LOW_CONF, UNMAPPED
  mapping_confidence REAL CHECK (mapping_confidence >= 0.0 AND mapping_confidence <= 1.0),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_13f_manager_security_qtr
ON holdings_13f (manager_id, security_id, report_date);

CREATE INDEX IF NOT EXISTS ix_13f_security_qtr
ON holdings_13f (security_id, report_date);
CREATE INDEX IF NOT EXISTS ix_13f_report_date
ON holdings_13f (report_date);

CREATE UNIQUE INDEX IF NOT EXISTS ux_13f_row_dedup
ON holdings_13f (filing_id, row_hash);

-- Parsed 13D/13G ownership events.
CREATE TABLE IF NOT EXISTS beneficial_ownership_events (
  bo_event_id INTEGER PRIMARY KEY,
  filing_id INTEGER NOT NULL REFERENCES filings (filing_id),
  manager_id INTEGER REFERENCES managers (manager_id),
  security_id INTEGER REFERENCES securities (security_id),
  report_date TEXT NOT NULL,
  event_type TEXT NOT NULL,      -- NEW_5PCT, AMENDMENT_UP, AMENDMENT_DOWN, EXIT_5PCT, OTHER
  percent_beneficial_owned REAL,
  shares_beneficial_owned REAL,
  cusip_raw TEXT,
  issuer_name_raw TEXT,
  ticker_raw TEXT,
  details_json TEXT,
  mapping_status TEXT NOT NULL DEFAULT 'UNMAPPED',
  mapping_confidence REAL CHECK (mapping_confidence >= 0.0 AND mapping_confidence <= 1.0),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_bo_security_date
ON beneficial_ownership_events (security_id, report_date);

CREATE INDEX IF NOT EXISTS ix_bo_manager_date
ON beneficial_ownership_events (manager_id, report_date);

-- Source-specific API budget and request tracking.
CREATE TABLE IF NOT EXISTS api_budgets (
  provider TEXT PRIMARY KEY,      -- SEC, POLYGON, AV, YF
  max_per_minute INTEGER,
  max_per_day INTEGER,
  burst_per_second INTEGER,
  notes TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_request_log (
  request_id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  request_ts TEXT NOT NULL DEFAULT (datetime('now')),
  status_code INTEGER,
  ok INTEGER NOT NULL CHECK (ok IN (0, 1)),
  latency_ms INTEGER,
  cache_hit INTEGER NOT NULL DEFAULT 0 CHECK (cache_hit IN (0, 1))
);

CREATE INDEX IF NOT EXISTS ix_api_log_provider_ts
ON api_request_log (provider, request_ts);

-- CUSIP -> ticker enrichment cache (provider-fed crosswalk).
CREATE TABLE IF NOT EXISTS cusip_ticker_xwalk (
  cusip TEXT PRIMARY KEY,
  ticker TEXT,
  figi TEXT,
  name TEXT,
  mic TEXT,
  source TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0.0 AND confidence <= 1.0),
  first_seen TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_cusip_xwalk_ticker
ON cusip_ticker_xwalk (ticker);

-- Pipeline observability events.
CREATE TABLE IF NOT EXISTS pipeline_run_events (
  run_id TEXT NOT NULL,
  event_ts TEXT NOT NULL DEFAULT (datetime('now')),
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT,
  metrics_json TEXT
);

CREATE INDEX IF NOT EXISTS ix_pipeline_events_run_ts
ON pipeline_run_events (run_id, event_ts);

-- Materialized-like cache tables (rebuilt by jobs) for fast UI reads.
CREATE TABLE IF NOT EXISTS agg_security_quarter (
  security_id INTEGER NOT NULL REFERENCES securities (security_id),
  report_date TEXT NOT NULL,
  holders_count INTEGER NOT NULL,
  total_shares REAL,
  total_value_usd REAL,
  top10_shares REAL,
  top10_pct REAL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (security_id, report_date)
);

CREATE TABLE IF NOT EXISTS agg_manager_quarter (
  manager_id INTEGER NOT NULL REFERENCES managers (manager_id),
  report_date TEXT NOT NULL,
  positions_count INTEGER NOT NULL,
  total_value_usd REAL,
  top10_value_pct REAL,
  turnover_ratio REAL,
  new_positions_count INTEGER,
  exited_positions_count INTEGER,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (manager_id, report_date)
);
