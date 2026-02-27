# Postgres Scaling Runbook

## Goals
- Keep resolver and aggregate jobs fast as `holdings_13f` grows.
- Avoid full-table maintenance during recurring updates.
- Bound storage growth for logs and stale snapshots.

## Baseline indexes
Ensure these exist (already created by app startup):

```sql
CREATE INDEX IF NOT EXISTS ix_13f_report_date ON holdings_13f (report_date);
CREATE INDEX IF NOT EXISTS ix_13f_security_report_date ON holdings_13f (security_id, report_date);
CREATE INDEX IF NOT EXISTS ix_ident_idtype_idvalue ON security_identifiers (id_type, id_value);
CREATE UNIQUE INDEX IF NOT EXISTS ux_identifiers_type_value ON security_identifiers (id_type, id_value);
```

## Recurring update path
Use incremental mode instead of full post-ingest reprocessing:

```bash
make pg-incremental
```

Equivalent CLI:

```bash
python -m app.cli update-incremental \
  --top-n 300 \
  --ingest-limit 20 \
  --resolve-quarters 6 \
  --recent-quarters 4 \
  --min-holders 3 \
  --min-total-value-usd 250000000 \
  --log-file logs/incremental.jsonl
```

## Table maintenance
Run weekly during low traffic:

```sql
VACUUM (ANALYZE) holdings_13f;
VACUUM (ANALYZE) beneficial_ownership_events;
VACUUM (ANALYZE) security_identifiers;
```

Optional monthly repack for heavy churn:

```sql
REINDEX INDEX CONCURRENTLY ix_13f_security_report_date;
REINDEX INDEX CONCURRENTLY ix_ident_idtype_idvalue;
```

## Retention policy
- `api_request_log`: keep last 180 days unless debugging.
- `pipeline_run_events`: keep last 365 days.
- Keep one SQLite backup snapshot in cloud storage, not multiple local copies.

Example cleanup:

```sql
DELETE FROM api_request_log
WHERE request_ts::timestamp < NOW() - INTERVAL '180 days';

DELETE FROM pipeline_run_events
WHERE event_ts < NOW() - INTERVAL '365 days';
```

## Optional partitioning plan (future)
If `holdings_13f` grows beyond tens of millions of rows, migrate to range partitioning by `report_date` quarter.

1. Create partitioned parent `holdings_13f_p` with same columns.
2. Create quarterly partitions (`FOR VALUES FROM ... TO ...`).
3. Backfill by quarter in batches.
4. Swap table names in a short maintenance window.
5. Recreate required indexes on each partition.

Do this only when query plans show sequential scans on large fractions of `holdings_13f` during incremental resolve/aggregate runs.
