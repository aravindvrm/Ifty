#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs/cron"
mkdir -p "$LOG_DIR"

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
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] publish_demo skipped: DEMO_REMOTE_DB_URL not set" >> "$LOG_DIR/publish_demo.log"
  exit 0
fi

{
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] publish_demo start"
  export DEMO_RUN_LOCAL_INCREMENTAL="${DEMO_RUN_LOCAL_INCREMENTAL:-1}"
  export DEMO_RUN_LOCAL_UPDATES="${DEMO_RUN_LOCAL_UPDATES:-1}"
  export DEMO_LOCAL_DB_STATEMENT_TIMEOUT_MS="${DEMO_LOCAL_DB_STATEMENT_TIMEOUT_MS:-0}"
  "$ROOT_DIR/scripts/push_demo_subset.sh"
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] publish_demo done"
} >> "$LOG_DIR/publish_demo.log" 2>&1
