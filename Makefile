SHELL := /bin/bash

.PHONY: init-db smoke-import smoke-health api-test web-install web-dev pipeline-run incremental-run seed-ingest discover-ciks seed-full pg-up pg-down pg-reset pg-migrate pg-status pg-resume-post pg-incremental

init-db:
	source .venv/bin/activate && SEC_USER_AGENT="$${SEC_USER_AGENT:-Aravind V aravindvrm@gmail.com}" python -m app.cli init-db

smoke-import:
	source .venv/bin/activate && \
	export SEC_USER_AGENT="$${SEC_USER_AGENT:-Aravind V aravindvrm@gmail.com}" && \
	python -c "import app; import app.main; print('import ok')"

smoke-health:
	bash -lc 'set -euo pipefail; \
	source .venv/bin/activate; \
	export SEC_USER_AGENT="$${SEC_USER_AGENT:-Aravind V aravindvrm@gmail.com}"; \
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

incremental-run:
	. .venv/bin/activate && python -m app.cli update-incremental --top-n 300 --ingest-limit 20 --resolve-quarters 6 --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000 --skip-sync-tickers

seed-ingest:
	. .venv/bin/activate && python -m app.cli ingest-cik-list --file seeds/ciks.sample.txt --limit 20

discover-ciks:
	. .venv/bin/activate && python -m app.cli discover-13f-ciks --quarters 6 --max-ciks 0 --out seeds/ciks.discovered.txt

seed-full:
	. .venv/bin/activate && export SEC_USER_AGENT='Aravind V aravindvrm@gmail.com' && \
	python -m app.cli discover-13f-ciks --quarters 6 --max-ciks 0 --out seeds/ciks.discovered.txt && \
	python -m app.cli ingest-cik-list --file seeds/ciks.discovered.txt --limit 40 --include-13dg && \
	python -m app.cli resolve-mappings && \
	python -m app.cli sync-tickers --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000 --universe-only && \
	python -m app.cli refresh-aggregates && \
	python -m app.cli refresh-universe --top-n 300

seed-top-aum:
	. .venv/bin/activate && python -m app.cli seed-top-aum --top-n 100 --limit 40 --include-13dg

pg-up:
	docker compose -f docker-compose.postgres.yml up -d postgres

pg-down:
	docker compose -f docker-compose.postgres.yml down

pg-reset:
	docker compose -f docker-compose.postgres.yml down -v
	docker compose -f docker-compose.postgres.yml up -d postgres

pg-status:
	docker compose -f docker-compose.postgres.yml ps

pg-migrate:
	bash -lc 'set -euo pipefail; \
	until docker exec flowtracker-postgres pg_isready -U flow -d flowdb >/dev/null 2>&1; do sleep 2; done; \
	source .venv/bin/activate; \
	python scripts/migrate_sqlite_to_postgres.py --sqlite data/app.snapshot.db --pg-dsn postgresql://flow:flow@127.0.0.1:5433/flowdb'

pg-resume-post:
	bash -lc 'set -euo pipefail; \
	export API_DB_URL="postgresql+psycopg://flow:flow@127.0.0.1:5433/flowdb"; \
	export SEC_USER_AGENT="$${SEC_USER_AGENT:-Aravind V aravindvrm@gmail.com}"; \
	source .venv/bin/activate; \
	python -m app.cli resume-post-ingest --batch-size 200000 --max-batches 100 --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000 --top-n 300 --log-file logs/post_ingest.jsonl'

pg-incremental:
	bash -lc 'set -euo pipefail; \
	export API_DB_URL="postgresql+psycopg://flow:flow@127.0.0.1:5433/flowdb"; \
	export SEC_USER_AGENT="$${SEC_USER_AGENT:-Aravind V aravindvrm@gmail.com}"; \
	source .venv/bin/activate; \
	python -m app.cli update-incremental --top-n 300 --ingest-limit 20 --resolve-quarters 6 --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000 --log-file logs/incremental.jsonl'
