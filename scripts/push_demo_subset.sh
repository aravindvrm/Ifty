#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
source .venv/bin/activate

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

if [[ -z "${DEMO_REMOTE_DB_URL:-}" ]]; then
  echo "DEMO_REMOTE_DB_URL is required."
  echo "Example: export DEMO_REMOTE_DB_URL='postgresql+psycopg://postgres:...@db.<project>.supabase.co:5432/postgres?sslmode=require'"
  exit 1
fi

if [[ "${DEMO_RUN_LOCAL_INCREMENTAL:-0}" == "1" ]]; then
  incr_cmd=(
    python -m app.cli update-incremental
    --top-n "${DEMO_INCREMENTAL_TOP_N:-300}"
    --ingest-limit "${DEMO_INCREMENTAL_INGEST_LIMIT:-20}"
    --resolve-quarters "${DEMO_INCREMENTAL_RESOLVE_QUARTERS:-6}"
    --recent-quarters "${DEMO_INCREMENTAL_RECENT_QUARTERS:-4}"
    --min-holders "${DEMO_INCREMENTAL_MIN_HOLDERS:-3}"
    --min-total-value-usd "${DEMO_INCREMENTAL_MIN_TOTAL_VALUE_USD:-250000000}"
  )
  if [[ "${DEMO_INCREMENTAL_INCLUDE_13DG:-1}" == "1" ]]; then
    incr_cmd+=(--include-13dg)
  fi
  if [[ "${DEMO_INCREMENTAL_SKIP_SYNC_TICKERS:-1}" == "1" ]]; then
    incr_cmd+=(--skip-sync-tickers)
  fi
  "${incr_cmd[@]}"
fi

if [[ "${DEMO_RUN_LOCAL_UPDATES:-1}" == "1" ]]; then
  python -m app.cli update-13dg-feed \
    --top-n "${DG_TOP_N:-300}" \
    --per-manager-limit "${DG_PER_MANAGER_LIMIT:-20}" \
    --resolve-limit "${DG_RESOLVE_LIMIT:-6}" \
    --index-discovery-mode "${DG_DISCOVERY_MODE:-daily}" \
    --discovery-days "${DG_DISCOVERY_DAYS:-21}"

  python -m app.cli update-form4-feed \
    --days "${FORM4_DAYS:-14}" \
    --max-filings "${FORM4_MAX_FILINGS:-0}"
fi

cmd=(
  python -m app.cli push-demo-subset
  --target-db-url "${DEMO_REMOTE_DB_URL}"
  --top-n "${DEMO_TOP_N:-75}"
  --quarters "${DEMO_QUARTERS:-2}"
  --bo-keep-days "${DEMO_BO_KEEP_DAYS:-180}"
  --insider-keep-days "${DEMO_INSIDER_KEEP_DAYS:-120}"
  --batch-size "${DEMO_SYNC_BATCH_SIZE:-5000}"
)
if [[ "${DEMO_COMPACT_HOLDINGS:-1}" != "1" ]]; then
  cmd+=(--no-compact-holdings)
fi
if [[ "${DEMO_SKIP_SCHEMA_INIT:-0}" == "1" ]]; then
  cmd+=(--skip-schema-init)
fi
if [[ "${DEMO_DRY_RUN:-0}" == "1" ]]; then
  cmd+=(--dry-run)
fi

"${cmd[@]}"
