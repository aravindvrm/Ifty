# Institutional Flow Tracker: MVP Ingestion + Resolution Workflow

This document defines how to ingest SEC filings and resolve them into a durable security master using SQLite.

## 1) Source-of-truth and API usage policy

- Ownership truth comes from SEC filings.
- Market metadata/corporate-action enrichment uses Polygon first, then yfinance fallback.
- Alpha Vantage is reserved for low-frequency backfills due to strict free-tier limits.

Initial `api_budgets` seed:

- `SEC`: `burst_per_second=8` (target below SEC 10 req/s policy), `max_per_minute=480`
- `POLYGON`: `max_per_minute=5`
- `AV`: `max_per_day=25`
- `YF`: no published SLA, use conservative local cap and aggressive cache

Rules:

1. Every outbound request checks token bucket by provider.
2. SEC requests must include compliant `User-Agent`.
3. Cache all enrichment responses by `(provider, endpoint, params_hash)` with TTL.
4. Never call secondary providers if data is already present and fresh.

## 2) Filing ingestion pipeline

### Stage A: Discover filings

1. Pull SEC submissions index for target CIK universe or recent forms stream.
2. Keep forms: `13F-HR`, `13F-HR/A`, `SC 13D`, `SC 13D/A`, `SC 13G`, `SC 13G/A`.
3. Upsert `filings` by `accession_no`.
4. Mark amendment relationships in `supersedes_filing_id` where detectable.

### Stage B: Parse filing content

1. For each new filing:
   - download primary filing doc
   - download/locate 13F information table (XML/text) if applicable
2. Parse into normalized row models:
   - 13F -> `holdings_13f`
   - 13D/G -> `beneficial_ownership_events`
3. Store raw identifiers (`cusip_raw`, `ticker_raw`, issuer raw text) for audit.

### Stage C: Resolve manager

1. Match by CIK into `managers`.
2. If missing, create manager row with raw filer name and normalized name.

### Stage D: Resolve security

Resolver priority (by report date):

1. Exact `CUSIP` match in `security_identifiers` where `id_type='CUSIP'` and date in `[valid_from, valid_to)`.
2. If no hit, CUSIP historical continuity via `security_alias_links`.
3. If still no hit, ticker+MIC+date match.
4. If multiple candidates remain, choose highest confidence and mark `MAPPED_LOW_CONF`.
5. If no candidate, create unresolved staging issue and keep row `UNMAPPED`.

Confidence suggestions:

- direct CUSIP/date hit: `1.0`
- CUSIP via alias continuity: `0.9`
- ticker+MIC date-valid hit: `0.75`
- ticker-only weak match: `<=0.5` and exclude from hard classification

### Stage E: Corporate-action reconciliation

Before QoQ classification:

1. Check corporate actions between prior quarter-end and current quarter-end.
2. Apply split factor normalization to comparable share units.
3. Traverse alias links to stitch old/new security identities where valid.
4. If continuity uncertain, classify as `possible_reclassification` not `new/exited`.

### Stage F: Aggregate refresh

Recompute:

- `agg_security_quarter`
- `agg_manager_quarter`

Prefer incremental refresh keyed by touched `security_id` / `manager_id` and report dates.

## 3) Classification logic for product features

## Security Page

### Top holders (13F)

Use latest report date and rank by `shares` or `value_usd_thousands`.

### Last 4 quarters net change by holder

For each manager-security pair:

- compute quarter-over-quarter `delta_shares_adj`
- ensure split-adjusted continuity

### Concentration: top 10 as % of total 13F ownership

For each security + quarter:

- `total_shares = sum(shares_adj)`
- `top10_shares = sum(top 10 manager shares_adj)`
- `top10_pct = top10_shares / total_shares`

## Manager Page

### Current top positions

Latest quarter holdings for manager, ranked by value.

### New positions / exits QoQ

`new_position`: present now, absent prior quarter, continuity checks passed.

`exit_position`: absent now, present prior quarter, continuity checks passed.

### Turnover / concentration metrics

Turnover proxy:

`(sum(abs(delta_position_value)) / 2) / avg(total_portfolio_value_t, total_portfolio_value_t-1)`

Concentration:

`top10_value_pct = sum(top 10 position values) / total portfolio value`

## Screeners

### Most accumulated this quarter

Two rank variants:

1. `net_holder_count = holders_added - holders_exited`
2. `net_shares = sum(delta_shares_adj)` across managers

### New 13D/G filers or new 5% holders

From `beneficial_ownership_events`:

- filter `event_type='NEW_5PCT'` for selected quarter window
- dedupe by `(manager_id, security_id)` newest filing in window

## 4) SQL templates (SQLite)

### Latest quarter top holders for one security

```sql
WITH latest AS (
  SELECT MAX(report_date) AS report_date
  FROM holdings_13f
  WHERE security_id = :security_id
),
rows AS (
  SELECT h.manager_id, m.manager_name, h.shares, h.value_usd_thousands
  FROM holdings_13f h
  JOIN managers m ON m.manager_id = h.manager_id
  JOIN latest l ON l.report_date = h.report_date
  WHERE h.security_id = :security_id
    AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
)
SELECT *
FROM rows
ORDER BY shares DESC
LIMIT 100;
```

### Net holder count screener (quarter-over-quarter)

```sql
WITH q AS (
  SELECT :curr_q AS curr_q, :prev_q AS prev_q
),
curr AS (
  SELECT security_id, manager_id
  FROM holdings_13f, q
  WHERE report_date = q.curr_q
    AND mapping_status = 'MAPPED'
  GROUP BY security_id, manager_id
),
prev AS (
  SELECT security_id, manager_id
  FROM holdings_13f, q
  WHERE report_date = q.prev_q
    AND mapping_status = 'MAPPED'
  GROUP BY security_id, manager_id
),
adds AS (
  SELECT c.security_id, COUNT(*) AS added
  FROM curr c
  LEFT JOIN prev p
    ON p.security_id = c.security_id
   AND p.manager_id = c.manager_id
  WHERE p.manager_id IS NULL
  GROUP BY c.security_id
),
drops AS (
  SELECT p.security_id, COUNT(*) AS dropped
  FROM prev p
  LEFT JOIN curr c
    ON c.security_id = p.security_id
   AND c.manager_id = p.manager_id
  WHERE c.manager_id IS NULL
  GROUP BY p.security_id
)
SELECT s.security_id,
       COALESCE(a.added, 0) - COALESCE(d.dropped, 0) AS net_holder_count
FROM securities s
LEFT JOIN adds a ON a.security_id = s.security_id
LEFT JOIN drops d ON d.security_id = s.security_id
ORDER BY net_holder_count DESC
LIMIT :limit_n;
```

## 5) Data quality controls

1. Preserve raw filing fields in holdings/events tables.
2. Track mapping confidence and status; do not silently coerce weak matches.
3. Treat amendments carefully:
   - prefer latest amendment chain leaf for canonical quarter snapshot
   - keep superseded records for audit
4. Build unresolved queue:
   - rows with `UNMAPPED` or confidence `< 0.75`
   - manual review can insert/update `security_identifiers` or alias links

## 6) Suggested implementation order

1. Implement schema and migration bootstrap.
2. Implement SEC discovery/parser workers for 13F + 13D/G.
3. Implement resolver with effective-dated identifier logic.
4. Implement aggregate refresh jobs and screener SQL.
5. Add enrichment adapters (Polygon, yfinance, Alpha Vantage) with request budgeting.
6. Expose API endpoints for:
   - `GET /security/{ticker}`
   - `GET /manager/{cik_or_id}`
   - `GET /screeners/accumulation`
   - `GET /screeners/new-5pct-holders`

