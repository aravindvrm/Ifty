SHELL := /bin/bash

.PHONY: init-db smoke-import smoke-health api-test web-install web-dev pipeline-run

init-db:
	source .venv/bin/activate && SEC_USER_AGENT='Codex Test codex@example.com' python -m app.cli init-db

smoke-import:
	source .venv/bin/activate && \
	export SEC_USER_AGENT='Codex Test codex@example.com' && \
	python -c "import app; import app.main; print('import ok')"

smoke-health:
	bash -lc 'set -euo pipefail; \
	source .venv/bin/activate; \
	export SEC_USER_AGENT="Codex Test codex@example.com"; \
	TO=""; \
	if command -v timeout >/dev/null 2>&1; then TO=$$(command -v timeout); \
	elif command -v gtimeout >/dev/null 2>&1; then TO=$$(command -v gtimeout); \
	fi; \
	if [ -z "$$TO" ]; then \
	  echo "timeout/gtimeout not found. Install coreutils to run smoke-health."; \
	  exit 1; \
	fi; \
	LOG=/tmp/flow_uvicorn.log; rm -f $$LOG; \
	$$TO 8s uvicorn app.main:app --port 8001 --log-level debug >$$LOG 2>&1 & \
	PID=$$!; \
	sleep 1; \
	if ! curl -sS http://127.0.0.1:8001/health; then \
	  cat $$LOG; \
	  wait $$PID || true; \
	  exit 1; \
	fi; \
	wait $$PID; \
	RC=$$?; \
	if [ $$RC -ne 124 ] && [ $$RC -ne 0 ]; then \
	  cat $$LOG; \
	  exit $$RC; \
	fi'

api-test:
	cd apps/api && ../../.venv/bin/python -m pytest -q

web-install:
	cd apps/web && npm install

web-dev:
	cd apps/web && npm run dev

pipeline-run:
	. .venv/bin/activate && python -m app.cli pipeline-run --top-n 300 --ingest-limit 20 --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000
