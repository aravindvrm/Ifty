# Ifty Product Specification

Version: 2026-03-04

## 1) Purpose and Scope

Ifty is a local-first institutional flow intelligence product that ingests SEC 13F and 13D/G filings, resolves holdings/events to a normalized security master, and serves analytics-oriented APIs/UI for:
- security-level institutional ownership analysis,
- institution-level portfolio and turnover analysis,
- market-wide flow/breadth monitoring,
- 13D/G event discovery.

In-scope:
- SEC ingestion, mapping, aggregation, universe curation.
- API + web app for dashboard/security/institution/feed/ops views.
- Scheduled incremental and feed pipelines.
- Internal/live validation workflows.

Out-of-scope:
- Trade execution, portfolio optimization, or order management.
- Full global security master beyond current SEC-sourced coverage.
- Real-time tick data.

## 2) System Architecture

## 2.1 Components

- Backend API: FastAPI app in `app/main.py`
- Route layer: `app/api/routes.py`
- CLI orchestrator: `app/cli.py`
- Ingestion services:
  - `Sec13FIngestionService` (`app/ingest/sec_13f.py`)
  - `Sec13DGIngestionService` (`app/ingest/sec_13dg.py`)
- Resolution services:
  - `SecurityResolverService` (`app/resolution/security_resolver.py`)
  - `TickerEnrichmentService` (`app/resolution/ticker_enrichment.py`)
  - CUSIP enrichment (`app/enrichment/cusip_to_ticker.py`)
- Aggregation service:
  - `AggregateRefreshService` (`app/analytics/aggregates.py`)
- Universe/feed services:
  - `ManagerUniverseService` (`app/pipeline/universe.py`)
  - `Daily13DGFeedUpdateService` (`app/pipeline/bo_feed.py`)
- Validation:
  - `app/validation/live_validation.py`

## 2.2 Deployment Model

- Local/Postgres-first default (`API_DB_URL` from `.env`).
- SQLite still supported for smoke/bootstrap paths.
- Frontend reads backend via `NEXT_PUBLIC_API_BASE_URL`.
- For Postgres, base schema is provisioned from `db/schema_postgres.sql`; runtime bootstrap (`init-db`) then applies seeds/index repairs/metadata.

## 2.3 Frontend Stack

- Next.js 15 App Router (`apps/web/app`)
- React 19
- Tailwind CSS
- Lucide icons
- `@nivo/treemap` for heatmap tiles

## 3) Data Flow

## 3.1 13F Flow

1. Discover filings by CIK/form
2. Upsert filing metadata into `filings`
3. Parse information-table rows into `holdings_13f`
4. Resolve to `security_id` via identifiers/aliases
5. Refresh aggregates (`agg_security_quarter`, `agg_manager_quarter`)
6. Refresh top institution universe (`manager_universe`)

## 3.2 13D/G Flow

1. Discover candidate CIKs (SEC index + optional universe)
2. Ingest forms (`SC 13D`, `SC 13G`, amendments)
3. Parse and upsert into `beneficial_ownership_events`
4. Sanitize low-quality labels
5. Resolve to `security_id`
6. Apply retention cleanup window (default from `RETENTION_13DG_DAYS`)

## 3.3 Incremental Update Path

`update-incremental` executes:
- universe refresh,
- scoped ingest,
- recent-quarter mapping resolution,
- optional ticker sync,
- aggregate refresh,
- post-refresh universe update,
- pipeline telemetry/logging + mapping coverage alerts.

## 4) Database Schema (Postgres)

Authoritative base DDL: `db/schema_postgres.sql`.
Runtime bootstrap additions/indexes: `app/db.py`.

## 4.1 Entity Master

### `issuers`
- PK: `issuer_id`
- Key columns: `issuer_name`, `lei`, `country_code`, `status`

### `securities`
- PK: `security_id`
- FK: `issuer_id -> issuers.issuer_id`
- Key columns: `instrument_type`, `security_name`, `share_class`, `primary_mic`, active window fields

### `security_identifiers`
- PK: `identifier_id`
- FK: `security_id -> securities.security_id`
- Key columns: `id_type`, `id_value`, `mic`, effective dates, `confidence`
- Important uniqueness:
  - `ux_identifiers_type_value` on `(id_type, id_value)`
  - version uniqueness by `(security_id, id_type, id_value, mic, valid_from)`

### `corporate_actions`
- PK: `action_id`
- FK: `security_id -> securities.security_id`
- Used for split adjustment (`action_type='SPLIT'`)

### `security_alias_links`
- PK: `link_id`
- FK: `from_security_id`, `to_security_id` -> `securities`
- Used for symbol/security continuity across ID changes

## 4.2 Institutions, Filings, Holdings

### `managers`
- PK: `manager_id`
- Key columns: `cik`, `manager_name`, `normalized_name`, `status`

### `manager_universe`
- PK/FK: `manager_id -> managers.manager_id`
- Tracks active top-N institution cohort by value/rank and as-of quarter

### `filings`
- PK: `filing_id`
- Unique: `accession_no`
- FK: `manager_id -> managers.manager_id`, `supersedes_filing_id -> filings.filing_id`
- Key columns: `form_type`, `cik`, `filed_at`, `period_end_date`, `sec_url`, amendment flags

### `holdings_13f`
- PK: `holding_13f_id`
- FK: `filing_id -> filings`, `manager_id -> managers`, `security_id -> securities`
- Key columns:
  - `report_date`, `cusip_raw`, `ticker_raw`, raw issuer/class fields
  - `value_usd_thousands`, `shares`, `option_type`
  - `mapping_status`, `mapping_confidence`, `row_hash`
- Critical dedupe index:
  - `ux_13f_row_dedup (filing_id, row_hash)`

### `beneficial_ownership_events`
- PK: `bo_event_id`
- FK: `filing_id -> filings`, optional `manager_id`, optional `security_id`
- Key columns:
  - `event_type` (`NEW_5PCT`, `EXIT_5PCT`, `AMENDMENT_UP`, `AMENDMENT_DOWN`, `OTHER`)
  - `percent_beneficial_owned`, `shares_beneficial_owned`
  - raw issuer/cusip/ticker labels + mapping status/confidence

## 4.3 Aggregates and Ops

### `agg_security_quarter`
- PK: `(security_id, report_date)`
- Stores quarterly holder count, shares/value totals, concentration (`top10_pct`)

### `agg_manager_quarter`
- PK: `(manager_id, report_date)`
- Stores positions count, total value, concentration, turnover, new/exited counts

### `api_budgets`
- Per-provider budget caps

### `api_request_log`
- Outbound API telemetry (provider, endpoint, status, latency, cache_hit)

### `cusip_ticker_xwalk`
- Optional enrichment xwalk from CUSIP to ticker/FIGI metadata

### `pipeline_run_events`
- Structured run/event logging for pipeline observability

### `app_bootstrap_meta`
- Runtime bootstrap metadata (`postgres_bootstrap_version`)

## 4.4 Key Access Paths / Index Notes

High-impact holdings indexes include:
- `ux_13f_row_dedup`
- `ix_13f_manager_security_qtr`
- `ix_13f_security_report_date`
- mapped/non-option partial indexes for security/manager/date scans
- filing/form date indexes on `filings`

Duplicate index remediation already applied:
- dropped duplicate `ix_13f_security_qtr` (kept `ix_13f_security_report_date`).

## 5) API Contract

All routes are implemented in `app/api/routes.py`.

## 5.1 Health and Operational APIs

| Method | Path | Purpose | Key Params |
|---|---|---|---|
| GET | `/health` | Liveness check | - |
| GET | `/ops/institution-universe` | Active top institutions | `limit_n` |
| GET | `/ops/manager-universe` | Alias of institution-universe | `limit_n` |
| GET | `/ops/api-usage` | API call telemetry summary/recent | `days`, `limit_n` |
| GET | `/ops/pipeline-runs/latest` | Latest pipeline timeline/status | - |

## 5.2 Ingestion/Job APIs

| Method | Path | Purpose | Key Params |
|---|---|---|---|
| POST | `/ingest/sec/13f` | Ingest 13F forms for one CIK | `cik`, `limit` |
| POST | `/ingest/sec/13dg` | Ingest 13D/G forms for one CIK | `cik`, `limit` |
| POST | `/jobs/resolve-mappings` | Resolve unmapped holdings/events | `limit` |
| POST | `/jobs/refresh-aggregates` | Rebuild aggregate tables | - |
| POST | `/jobs/sync-tickers` | Sync ticker identifiers from SEC datasets | `limit`, `recent_quarters`, `min_holders`, `min_total_value_usd`, `universe_only` |
| POST | `/jobs/refresh-universe` | Recompute top-N institution universe | `top_n` |
| POST | `/jobs/enrich-cusips` | CUSIP->ticker enrichment in scope | `provider`, `recent_quarters`, `top_n`, `limit_cusips` |
| POST | `/jobs/update-13dg-feed` | Daily 13D/G discovery+ingest+resolve+cleanup | `top_n`, `per_manager_limit`, `resolve_limit`, discovery/retention toggles |

## 5.3 Product Data APIs

| Method | Path | Purpose | Key Params |
|---|---|---|---|
| GET | `/home/overview` | Dashboard aggregate payload | `quarters_n`, `top_n`, flow histogram params |
| GET | `/security/search` | Security search | `q`, `limit_n` |
| GET | `/security/{ticker}` | Security detail analytics | `ticker` |
| GET | `/security/{ticker}/events` | Security-specific 13D/G events | `limit_n`, `new_5pct_only`, `start_date`, `end_date` |
| GET | `/feeds/13dg` | Global 13D/G feed explorer | date window + event/form/filter params |
| GET | `/institution/{manager_key}` | Institution detail analytics (`manager_id` or CIK) | `manager_key` |
| GET | `/manager/{manager_key}` | Alias to institution endpoint | `manager_key` |

## 5.4 Legacy Screener APIs

| Method | Path | Purpose | Key Params |
|---|---|---|---|
| GET | `/screeners/accumulation` | QoQ accumulation ranking | `curr_q`, `prev_q`, `limit_n` |
| GET | `/screeners/new-5pct-holders` | New 5% events window | `start_date`, `end_date`, `limit_n` |
| GET | `/screeners/accumulation-history` | Historical accumulation time series | `limit_n` |

## 6) Frontend Specification

## 6.1 Route Map

| Route | Status | Description |
|---|---|---|
| `/` | active | Market Pulse dashboard |
| `/feed` | active | 13D/G feed explorer (search + filters) |
| `/security` | active | Security directory search |
| `/security/[ticker]` | active | Security analytics detail |
| `/institution` | active | Institution directory |
| `/institution/[institutionKey]` | active | Institution analytics detail |
| `/ops` | active | Operational console |
| `/manager` | redirect | Redirects to `/institution` |
| `/manager/[managerKey]` | redirect | Redirects to `/institution/[managerKey]` |
| `/screeners` | redirect | Redirects to `/` |

## 6.2 Global UX Contracts

- Dark, high-contrast UI shell with collapsible sidebar.
- Top live tape fed by mapped/high-quality 13D/G events.
- Global search supports both securities and institutions with keyboard navigation.
- Route transitions show a custom loading state (`apps/web/app/loading.tsx`).
- Heatmap visualizations use Nivo treemap renderer with delta color coding.

## 6.3 Data Fetch Contracts

- API base: `NEXT_PUBLIC_API_BASE_URL` (fallback `http://127.0.0.1:8000`)
- Request timeout: 15s client-side in `apps/web/lib/api.ts`
- `no-store` fetch policy for fresh operational analytics.

## 7) CLI Contract

Primary command groups (`python -m app.cli`):
- bootstrap/init: `init-db`, `ingest-cik-list`, `discover-13f-ciks`, `seed-top-aum`
- ingest/update: `ingest-13f`, `ingest-13dg`, `ingest-universe`, `update-incremental`, `update-13dg-feed`
- mapping/enrichment: `resolve-mappings`, `sync-tickers`, `enrich-cusips`
- analytics/universe: `refresh-aggregates`, `refresh-universe`, `resume-post-ingest`
- maintenance: `cleanup-13dg`
- validation: `validate-live`

## 8) Configuration

Source: `.env` via `app/config.py`.

Key settings:
- DB/API:
  - `API_DB_URL`
  - `NEXT_PUBLIC_API_BASE_URL`
  - pool/timeouts (`DB_POOL_SIZE`, `DB_STATEMENT_TIMEOUT_MS`, ...)
- SEC:
  - `SEC_USER_AGENT` (required for SEC access)
  - `SEC_BURST_PER_SECOND`
- External validation/enrichment:
  - `POLY_KEY`, `AV_KEY`, `OPENFIGI_API_KEY`
  - rate controls (`NASDAQ_BURST_PER_SECOND`, `POLYGON_BURST_PER_SECOND`, `ALPHAVANTAGE_BURST_PER_SECOND`)
- Feed retention:
  - `RETENTION_13DG_DAYS`
- CORS:
  - `API_CORS_ORIGINS`

## 9) Non-Functional Requirements

- SEC-compliant User-Agent and rate limiting for ingestion.
- DB statement timeout defaults to protect API latency.
- Partial indexes and mapped/non-option filters for heavy access paths.
- Pipeline events + API request logs support operability and debugging.

## 10) Known Constraints / Risks

- Storage footprint is dominated by `holdings_13f` snapshots and indexes.
- Historical depth and top-N universe size have direct cost/performance impact.
- 13D/G text parsing quality varies by filing format; sanitation and mapping confidence controls are required.
- Some external validation providers have strict free-tier quotas.

## 11) Operational Recommendations

- Use Postgres for real dataset operation; SQLite for smoke/local-only workflows.
- Prefer `update-incremental` and `update-13dg-feed` over full reseeds.
- Keep 13D/G retention bounded (default rolling window).
- Periodically review index usage and prune true duplicates/unused paths conservatively.
