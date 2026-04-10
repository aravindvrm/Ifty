#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs/cron"
mkdir -p "$LOG_DIR"

cd "$ROOT_DIR"
source .venv/bin/activate

{
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] feed_13dg start"
  python -m app.cli update-13dg-feed \
    --top-n "${DG_TOP_N:-300}" \
    --per-manager-limit "${DG_PER_MANAGER_LIMIT:-20}" \
    --resolve-limit "${DG_RESOLVE_LIMIT:-6}" \
    --index-discovery-mode "${DG_DISCOVERY_MODE:-daily}" \
    --discovery-days "${DG_DISCOVERY_DAYS:-21}"
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] feed_13dg done"
} >> "$LOG_DIR/13dg_feed.log" 2>&1
