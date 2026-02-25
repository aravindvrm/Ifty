# Institutional Flow Tracker (MVP backend)

## Quick start

1. Install dependencies (example):
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. Copy env and set values:
```bash
cp .env.example .env
```

3. Initialize SQLite schema:
```bash
python -m app.cli init-db
```

4. Run API:
```bash
uvicorn app.main:app --reload --port 8000
```

5. Trigger 13F discovery+ingestion for one manager CIK:
```bash
python -m app.cli ingest-13f --cik 0001067983 --limit 20
```

6. Trigger 13D/G discovery+ingestion for one manager CIK:
```bash
python -m app.cli ingest-13dg --cik 0001067983 --limit 20
```

7. Resolve unmapped holdings/events into `security_id`:
```bash
python -m app.cli resolve-mappings
```

8. Refresh aggregate tables used for analytics screens:
```bash
python -m app.cli refresh-aggregates
```

9. Sync ticker identifiers for active/high-interest securities:
```bash
python -m app.cli sync-tickers --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000 --universe-only
```

10. Refresh manager universe (Top-N):
```bash
python -m app.cli refresh-universe --top-n 300
```

11. Run full scoped automated pipeline:
```bash
python -m app.cli pipeline-run --top-n 300 --ingest-limit 20 --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000
```

## Frontend (Next.js)

Web app location: `apps/web`

1. Install dependencies:
```bash
cd apps/web
npm install
```

2. Start dev server:
```bash
npm run dev
```

3. Open:
- `http://localhost:3000`
- Security page: `/security/AAPL`
- Manager page: `/manager/1`
- Screeners: `/screeners`
- Ops console: `/ops`

## Smoke tests

From repo root (`/Users/avrm/Documents/Repos/Codex/13F-tracker`):

```bash
make smoke-import
make init-db
make smoke-health
```

Notes:

- `smoke-health` uses `timeout`/`gtimeout` and avoids `pkill`.
- If your environment blocks local socket bind (sandbox restriction), run the same command on your host shell.

## API endpoints (current)

- `GET /health`
- `POST /ingest/sec/13f?cik=...&limit=...`
- `POST /ingest/sec/13dg?cik=...&limit=...`
- `POST /jobs/sync-tickers?limit=...&recent_quarters=...&min_holders=...&min_total_value_usd=...&universe_only=...`
- `POST /jobs/resolve-mappings?limit=...`
- `POST /jobs/refresh-aggregates`
- `POST /jobs/refresh-universe?top_n=...`
- `GET /security/{ticker}`
- `GET /security/{ticker}/events`
- `GET /security/search?q=...`
- `GET /manager/{manager_key}` (`manager_id` or `cik`)
- `GET /screeners/accumulation?curr_q=YYYY-MM-DD&prev_q=YYYY-MM-DD`
- `GET /screeners/accumulation-history?limit_n=...`
- `GET /screeners/new-5pct-holders?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
- `GET /ops/manager-universe?limit_n=...`
- `GET /ops/api-usage?days=...&limit_n=...`

## Notes

- SEC endpoints require a valid `SEC_USER_AGENT` in `.env`.
- This MVP ingests SEC metadata and parses available 13F information-table XML into `holdings_13f`.
- 13D/G parsing currently extracts best-effort CUSIP and percent-owned from filing text.
- Resolver now maps `UNMAPPED` rows using effective-dated identifiers (`CUSIP` first, then `TICKER`) and alias fallback with confidence.
- Security page QoQ net change applies split factors from `corporate_actions` rows with `action_type='SPLIT'`.
- API request logging is verbose by design and captured in `api_request_log` for usage telemetry.
