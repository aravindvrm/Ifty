#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
source .venv/bin/activate

load_dotenv() {
  local env_file="$1"
  [[ -f "$env_file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    [[ "$line" == *"="* ]] || continue
    local key="${line%%=*}"
    local value="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    export "$key=$value"
  done < "$env_file"
}

load_dotenv "$ROOT_DIR/.env"

if [[ -z "${DEMO_REMOTE_DB_URL:-}" ]]; then
  echo "DEMO_REMOTE_DB_URL is required."
  echo "Example: export DEMO_REMOTE_DB_URL='postgresql+psycopg://postgres:...@db.<project>.supabase.co:5432/postgres?sslmode=require'"
  exit 1
fi

LOCAL_DB_STMT_TIMEOUT_MS="${DEMO_LOCAL_DB_STATEMENT_TIMEOUT_MS:-0}"

run_cli() {
  DB_STATEMENT_TIMEOUT_MS="$LOCAL_DB_STMT_TIMEOUT_MS" "$@"
}

if [[ "${DEMO_RUN_LOCAL_INCREMENTAL:-0}" == "1" ]]; then
  incr_cmd=(
    python -m app.cli update-incremental
    --top-n "${DEMO_INCREMENTAL_TOP_N:-${DEMO_TOP_N:-75}}"
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
  run_cli "${incr_cmd[@]}"
fi

if [[ "${DEMO_RUN_LOCAL_UPDATES:-1}" == "1" ]]; then
  run_cli python -m app.cli update-13dg-feed \
    --top-n "${DG_TOP_N:-300}" \
    --per-manager-limit "${DG_PER_MANAGER_LIMIT:-20}" \
    --resolve-limit "${DG_RESOLVE_LIMIT:-6}" \
    --index-discovery-mode "${DG_DISCOVERY_MODE:-daily}" \
    --discovery-days "${DG_DISCOVERY_DAYS:-21}"

  run_cli python -m app.cli update-form4-feed \
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

run_cli "${cmd[@]}"
