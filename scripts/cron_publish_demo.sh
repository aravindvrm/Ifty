#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs/cron"
mkdir -p "$LOG_DIR"

cd "$ROOT_DIR"
source .venv/bin/activate

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

if [[ -z "${DEMO_REMOTE_DB_URL:-}" ]]; then
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] publish_demo skipped: DEMO_REMOTE_DB_URL not set" >> "$LOG_DIR/publish_demo.log"
  exit 0
fi

{
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] publish_demo start"
  export DEMO_RUN_LOCAL_INCREMENTAL="${DEMO_RUN_LOCAL_INCREMENTAL:-1}"
  export DEMO_RUN_LOCAL_UPDATES="${DEMO_RUN_LOCAL_UPDATES:-1}"
  "$ROOT_DIR/scripts/push_demo_subset.sh"
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] publish_demo done"
} >> "$LOG_DIR/publish_demo.log" 2>&1

