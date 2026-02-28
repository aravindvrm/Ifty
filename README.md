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
Use repo-root `.env` as the single backend config source (`API_DB_URL`, `SEC_USER_AGENT`).

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
`--limit` applies to matching target forms (e.g., `13F-HR`, `13F-HR/A`, `SC 13D`, `SC 13G`), not just the first N mixed `filings.recent` rows.

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

12. Bootstrap from a seed CIK list (initial population):
```bash
python -m app.cli ingest-cik-list --file seeds/ciks.sample.txt --limit 20 --include-13dg
python -m app.cli resolve-mappings
python -m app.cli sync-tickers --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000 --universe-only
python -m app.cli refresh-aggregates
python -m app.cli refresh-universe --top-n 300
```

13. Full initial seeding (auto-discover larger 13F manager universe):
```bash
python -m app.cli discover-13f-ciks --quarters 6 --max-ciks 0 --out seeds/ciks.discovered.txt
python -m app.cli ingest-cik-list --file seeds/ciks.discovered.txt --limit 40 --include-13dg
python -m app.cli resolve-mappings
python -m app.cli sync-tickers --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000 --universe-only
python -m app.cli refresh-aggregates
python -m app.cli refresh-universe --top-n 300
```
Or run:
```bash
make seed-full
```

13b. Seed explicitly by top 13F AUM proxy from SEC dataset (ingest only missing managers, optional prune):
```bash
python -m app.cli seed-top-aum --top-n 100 --limit 40 --include-13dg
```
Use `--dataset-url` to pin a specific SEC 13F ZIP, and `--no-prune` to skip deleting managers below threshold.

14. Move existing SQLite data to local Docker Postgres (no re-ingest):
```bash
# create a consistent snapshot first
sqlite3 data/app.db ".backup data/app.snapshot.db"

# start Postgres
make pg-up

# migrate snapshot into Postgres
make pg-migrate

# point API to Postgres
export API_DB_URL="postgresql+psycopg://flow:flow@127.0.0.1:5433/flowdb"
```

15. Resume only post-ingest stages in Postgres (no new SEC ingest):
```bash
make pg-resume-post
```

16. Efficient recurring update (incremental):
```bash
python -m app.cli update-incremental \
  --top-n 300 \
  --ingest-limit 20 \
  --resolve-quarters 6 \
  --recent-quarters 4 \
  --min-holders 3 \
  --min-total-value-usd 250000000 \
  --skip-sync-tickers \
  --log-file logs/incremental.jsonl
```
This updates active managers, resolves only recent report-date batches, and refreshes aggregates/universe.

Postgres shortcut:
```bash
make pg-incremental
```

Optional coverage alert thresholds:
- `--alert-min-13f-pct` (default `95.0`)
- `--alert-min-bo-pct` (default `95.0`)

17. Live analytics validation (internal consistency + optional third-party snapshot):
```bash
python -m app.cli validate-live \
  --sample-managers 10 \
  --sample-tickers 20 \
  --tolerance-pct 0.25 \
  --fail-on-error
```
Optional external comparison:
```bash
python -m app.cli validate-live --ticker AAPL --external-provider auto
```
External providers:
- `nasdaq` (institutional-holdings endpoint)
- `polygon` (shares outstanding + splits where available)
- `alphavantage` (shares outstanding)
- `auto` (tries Polygon first, then Alpha Vantage)

Rate-limit knobs:
- `NASDAQ_BURST_PER_SECOND` (default `0.5`)
- `POLYGON_BURST_PER_SECOND` (default `0.2`)
- `ALPHAVANTAGE_BURST_PER_SECOND` (default `0.08`)

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
- `python -m app.cli validate-live` (CLI audit command)

## Notes

- SEC endpoints require a valid `SEC_USER_AGENT` in `.env`.
- This MVP ingests SEC metadata and parses available 13F information-table XML into `holdings_13f`.
- 13D/G parsing currently extracts best-effort CUSIP and percent-owned from filing text.
- Resolver now maps `UNMAPPED` rows using effective-dated identifiers (`CUSIP` first, then `TICKER`) and alias fallback with confidence.
- Security page QoQ net change applies split factors from `corporate_actions` rows with `action_type='SPLIT'`.
- API request logging is verbose by design and captured in `api_request_log` for usage telemetry.
- Seed file support: `ingest-cik-list --file <path>` accepts `.txt` (one CIK per line) or `.csv` with a `cik` column.
- Discovery support: `discover-13f-ciks` scans recent SEC `master.idx` files for `13F-HR` / `13F-HR/A` filers and writes a deduplicated CIK list. Use `--max-ciks 0` for full coverage; capped runs are tie-aware and include all CIKs at the cutoff score.
- Scaling/retention runbook: `docs/postgres_scaling.md`.
