# Ifty (Institutional Flow Tracker)

Institutional ownership intelligence platform built on SEC 13F and 13D/G filings.

This repo contains:
- FastAPI backend (`app/`) for ingestion, mapping, analytics, and APIs.
- Next.js frontend (`apps/web/`) for dashboard, security/institution views, live 13D/G feed, and ops console.
- CLI pipeline (`python -m app.cli ...`) for seeding, incremental updates, retention, and validation.

## Current State (Audited)

The current app surface is:
- Dashboard (`/`) with Market Pulse KPIs, animated Top Movers columns, flow-distribution histogram, coverage/trust panel.
- Security directory/detail (`/security`, `/security/{ticker}`) with activity breakdown, institutional heatmap, active positions, and filtered 13D/G events.
- Institution directory/detail (`/institution`, `/institution/{id_or_cik}`) with portfolio metrics, buy/sell deltas, position heatmap.
- 13D/G feed explorer (`/feed`) with live filtering and quality-gated mapped results.
- Ops console (`/ops`) with job controls, universe status, pipeline run log, and API usage telemetry.

Legacy route aliases still resolve:
- `/manager`, `/manager/{managerKey}` -> institution routes
- `/screeners` -> dashboard

## Architecture

### Backend
- Framework: FastAPI (`app/main.py`)
- DB access: SQLAlchemy + psycopg
- Core API routes: `app/api/routes.py`
- Ingestion services:
  - `app/ingest/sec_13f.py`
  - `app/ingest/sec_13dg.py`
- Mapping/resolution:
  - `app/resolution/security_resolver.py`
  - `app/resolution/ticker_enrichment.py`
  - `app/enrichment/cusip_to_ticker.py`
- Aggregates:
  - `app/analytics/aggregates.py`
  - `app/analytics/splits.py`
- Operational pipelines:
  - `app/pipeline/universe.py`
  - `app/pipeline/bo_feed.py`
  - `app/pipeline/aum_seed.py`

### Frontend
- Framework: Next.js App Router (`apps/web/app`)
- Charting: `@nivo/treemap` (heatmaps)
- Global search: security + institution typeahead with keyboard navigation
- Live tape and feed views backed by `/feeds/13dg`

### Data Stores
- Primary: PostgreSQL (`API_DB_URL` default in `.env.example`)
- SQLite is still supported for local smoke/dev bootstraps.

## Repo Layout

- `app/`: backend API + ingestion + pipeline + CLI
- `apps/web/`: frontend
- `db/`: schema files (`schema.sql`, `schema_postgres.sql`)
- `scripts/`: migration scripts
- `seeds/`: CIK seed/discovery files
- `docs/`: runbooks + product spec

## Quick Start

### 1) Environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set at minimum:
- `SEC_USER_AGENT=Your Name your.email@example.com`
- `API_DB_URL=postgresql+psycopg://flow:flow@127.0.0.1:5433/flowdb` (or SQLite URL)

### 2) Start Postgres (recommended)

```bash
make pg-up
```

### 3) Provision schema

For a fresh Postgres database, apply schema first:

```bash
psql postgresql://flow:flow@127.0.0.1:5433/flowdb -f db/schema_postgres.sql
```

Then run bootstrap/seeds:

```bash
python -m app.cli init-db
```

### 4) Run backend API

```bash
uvicorn app.main:app --reload --port 8000
```

### 5) Run frontend

```bash
cd apps/web
npm install
npm run dev
```

Open:
- `http://localhost:3000`

## Pipeline Commands

### Initial seeding

Discover + ingest broad 13F universe:

```bash
python -m app.cli discover-13f-ciks --quarters 6 --max-ciks 0 --out seeds/ciks.discovered.txt
python -m app.cli ingest-cik-list --file seeds/ciks.discovered.txt --limit 40 --include-13dg
python -m app.cli resolve-mappings
python -m app.cli sync-tickers --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000 --universe-only
python -m app.cli refresh-aggregates
python -m app.cli refresh-universe --top-n 300
```

Or:

```bash
make seed-full
```

### Top-AUM scoped seed

```bash
python -m app.cli seed-top-aum --top-n 100 --limit 40 --include-13dg
```

### Incremental recurring update (13F + optional 13D/G)

```bash
python -m app.cli update-incremental \
  --top-n 300 \
  --ingest-limit 20 \
  --resolve-quarters 6 \
  --recent-quarters 4 \
  --min-holders 3 \
  --min-total-value-usd 250000000 \
  --log-file logs/incremental.jsonl
```

### Daily 13D/G feed update + cleanup

```bash
python -m app.cli update-13dg-feed \
  --per-manager-limit 20 \
  --resolve-limit 6 \
  --index-discovery-mode daily \
  --discovery-days 21
```

### Daily Form 4 insider feed update

```bash
# 0 = process all discovered filings for scanned days
python -m app.cli update-form4-feed --days 14 --max-filings 0
```

### Cron Scheduling (recommended)

Use the provided scripts:
- `scripts/cron_form4_feed.sh`
- `scripts/cron_13dg_feed.sh`

Example crontab (Form 4 every 30m, 13D/G daily at 02:10 local time):

```cron
*/30 * * * * /Users/avrm/Documents/Repos/Codex/13F-tracker/scripts/cron_form4_feed.sh
10 2 * * * /Users/avrm/Documents/Repos/Codex/13F-tracker/scripts/cron_13dg_feed.sh
```

Optional runtime overrides via env vars:
- Form 4 script: `FORM4_DAYS`, `FORM4_MAX_FILINGS`
- 13D/G script: `DG_TOP_N`, `DG_PER_MANAGER_LIMIT`, `DG_RESOLVE_LIMIT`, `DG_DISCOVERY_MODE`, `DG_DISCOVERY_DAYS`

### Validation

```bash
python -m app.cli validate-live --sample-managers 10 --sample-tickers 20 --tolerance-pct 0.25
```

Optional external snapshot checks:

```bash
python -m app.cli validate-live --ticker AAPL --external-provider auto
```

## API Surface (Current)

### System / Ops
- `GET /health`
- `GET /ops/institution-universe` (alias: `/ops/manager-universe`)
- `GET /ops/api-usage`
- `GET /ops/pipeline-runs/latest`

### Ingestion / Jobs
- `POST /ingest/sec/13f`
- `POST /ingest/sec/13dg`
- `POST /jobs/resolve-mappings`
- `POST /jobs/refresh-aggregates`
- `POST /jobs/sync-tickers`
- `POST /jobs/refresh-universe`
- `POST /jobs/enrich-cusips`
- `POST /jobs/update-13dg-feed`
- `POST /jobs/update-form4-feed`

### Product APIs
- `GET /home/overview`
- `GET /security/search`
- `GET /security/{ticker}`
- `GET /security/{ticker}/events`
- `GET /feeds/13dg`
- `GET /institution/{manager_key}` (alias: `/manager/{manager_key}`)

### Legacy screener APIs (still available)
- `GET /screeners/accumulation`
- `GET /screeners/new-5pct-holders`
- `GET /screeners/accumulation-history`

For full endpoint parameters and response contracts, see:
- [`docs/product_spec.md`](docs/product_spec.md)

## Testing / Smoke

From repo root:

```bash
make smoke-import
make init-db
make smoke-health
make api-test
```

## Notes

- SEC ingestion requires compliant `SEC_USER_AGENT`.
- Rate limiting is enforced via provider token-bucket controls.
- 13D/G feed pipeline includes label sanitation and retention cleanup.
- `holdings_13f` is the dominant storage footprint; index strategy matters materially for performance and DB size.

## Documentation

- Product spec: [`docs/product_spec.md`](docs/product_spec.md)
- Ingestion workflow notes: [`docs/ingestion_workflow.md`](docs/ingestion_workflow.md)
- Postgres scaling runbook: [`docs/postgres_scaling.md`](docs/postgres_scaling.md)
