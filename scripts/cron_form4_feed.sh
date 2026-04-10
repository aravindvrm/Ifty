#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs/cron"
mkdir -p "$LOG_DIR"

cd "$ROOT_DIR"
source .venv/bin/activate

{
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] form4_feed start"
  python -m app.cli update-form4-feed \
    --days "${FORM4_DAYS:-7}" \
    --max-filings "${FORM4_MAX_FILINGS:-0}"
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] form4_feed done"
} >> "$LOG_DIR/form4_feed.log" 2>&1
