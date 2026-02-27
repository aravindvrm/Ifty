#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQLITE_PATH="${1:-$ROOT_DIR/data/app.snapshot.db}"
PG_DSN="${2:-postgresql://flow:flow@flowtracker-postgres:5432/flowdb}"
NETWORK_NAME="${3:-13f-tracker_default}"
WORK_SQLITE="$ROOT_DIR/data/app.pgload.db"

if [[ ! -f "$SQLITE_PATH" ]]; then
  echo "SQLite source not found: $SQLITE_PATH" >&2
  exit 1
fi

echo "Migrating SQLite -> Postgres"
echo "  sqlite: $SQLITE_PATH"
echo "  dsn:    $PG_DSN"
echo "  net:    $NETWORK_NAME"

cp "$SQLITE_PATH" "$WORK_SQLITE"
# pgloader cannot translate SQLite expression index IFNULL(...) to Postgres.
# Keep source intact and drop only on working copy.
sqlite3 "$WORK_SQLITE" "DROP INDEX IF EXISTS ux_identifiers_version;"

docker run --rm \
  -e SBCL_DYNAMIC_SPACE_SIZE=4096 \
  --network "$NETWORK_NAME" \
  -v "$ROOT_DIR:/work" \
  dimitri/pgloader:latest \
  pgloader \
  "sqlite:///work/${WORK_SQLITE#$ROOT_DIR/}" \
  "$PG_DSN"

echo "Migration complete."
