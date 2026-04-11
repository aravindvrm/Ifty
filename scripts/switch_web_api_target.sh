#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_ENV_FILE="$ROOT_DIR/apps/web/.env.local"

usage() {
  cat <<'EOF'
Usage:
  scripts/switch_web_api_target.sh local
  scripts/switch_web_api_target.sh render [https://your-render-url]
  scripts/switch_web_api_target.sh custom <https://api-url>

What it changes:
  - apps/web/.env.local: API_BASE_URL
  - apps/web/.env.local: NEXT_PUBLIC_API_BASE_URL

Supabase OAuth env vars are untouched.
EOF
}

upsert_env_var() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp
  tmp="$(mktemp)"

  awk -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    $0 ~ ("^" key "=") {
      print key "=" value
      found = 1
      next
    }
    { print }
    END {
      if (!found) print key "=" value
    }
  ' "$file" > "$tmp"

  mv "$tmp" "$file"
}

MODE="${1:-}"
TARGET_URL="${2:-}"

if [[ -z "$MODE" ]]; then
  usage
  exit 1
fi

if [[ ! -f "$WEB_ENV_FILE" ]]; then
  touch "$WEB_ENV_FILE"
fi

case "$MODE" in
  local)
    TARGET_URL="http://127.0.0.1:8000"
    ;;
  render)
    if [[ -z "$TARGET_URL" ]]; then
      TARGET_URL="${RENDER_API_BASE_URL:-https://ifty.onrender.com}"
    fi
    ;;
  custom)
    if [[ -z "$TARGET_URL" ]]; then
      echo "custom mode requires a URL."
      usage
      exit 1
    fi
    ;;
  *)
    echo "Unknown mode: $MODE"
    usage
    exit 1
    ;;
esac

TARGET_URL="${TARGET_URL%/}"
if [[ ! "$TARGET_URL" =~ ^https?:// ]]; then
  echo "Invalid URL: $TARGET_URL"
  exit 1
fi

upsert_env_var "$WEB_ENV_FILE" "API_BASE_URL" "$TARGET_URL"
upsert_env_var "$WEB_ENV_FILE" "NEXT_PUBLIC_API_BASE_URL" "$TARGET_URL"

echo "Updated $WEB_ENV_FILE"
echo "  API_BASE_URL=$TARGET_URL"
echo "  NEXT_PUBLIC_API_BASE_URL=$TARGET_URL"

