#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import sqlite3
from pathlib import Path

import psycopg

TABLES_IN_ORDER = [
    "issuers",
    "securities",
    "security_identifiers",
    "corporate_actions",
    "security_alias_links",
    "managers",
    "manager_universe",
    "filings",
    "holdings_13f",
    "beneficial_ownership_events",
    "api_budgets",
    "api_request_log",
    "agg_security_quarter",
    "agg_manager_quarter",
]

PK_COLUMNS = {
    "issuers": "issuer_id",
    "securities": "security_id",
    "security_identifiers": "identifier_id",
    "corporate_actions": "action_id",
    "security_alias_links": "link_id",
    "managers": "manager_id",
    "filings": "filing_id",
    "holdings_13f": "holding_13f_id",
    "beneficial_ownership_events": "bo_event_id",
    "api_request_log": "request_id",
}


def _columns_sqlite(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(r[1]) for r in rows]


def _copy_table(sqlite_conn: sqlite3.Connection, pg_conn: psycopg.Connection, table: str, batch_size: int) -> int:
    cols = _columns_sqlite(sqlite_conn, table)
    if not cols:
        return 0

    col_sql = ", ".join(cols)
    select_sql = f"SELECT {col_sql} FROM {table}"
    cur = sqlite_conn.execute(select_sql)
    total = 0
    with pg_conn.cursor() as pg_cur:
        with pg_cur.copy(f"COPY {table} ({col_sql}) FROM STDIN WITH (FORMAT csv)") as copy:
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                buf = io.StringIO()
                writer = csv.writer(buf, lineterminator="\n")
                for row in rows:
                    writer.writerow(row)
                copy.write(buf.getvalue())
                total += len(rows)
    pg_conn.commit()
    return total


def _create_schema(pg_conn: psycopg.Connection, schema_path: Path) -> None:
    sql = schema_path.read_text(encoding="utf-8")
    with pg_conn.cursor() as cur:
        cur.execute(sql)
    pg_conn.commit()


def _truncate_all(pg_conn: psycopg.Connection) -> None:
    sql = "TRUNCATE TABLE " + ", ".join(reversed(TABLES_IN_ORDER)) + " RESTART IDENTITY CASCADE"
    with pg_conn.cursor() as cur:
        cur.execute(sql)
    pg_conn.commit()


def _set_sequences(pg_conn: psycopg.Connection) -> None:
    with pg_conn.cursor() as cur:
        for table, pk_col in PK_COLUMNS.items():
            cur.execute(f"SELECT COALESCE(MAX({pk_col}), 1) FROM {table}")
            max_id = int(cur.fetchone()[0] or 1)
            cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table, pk_col))
            seq_name = cur.fetchone()[0]
            if seq_name:
                cur.execute("SELECT setval(%s, %s, true)", (seq_name, max_id))
    pg_conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite DB into Postgres.")
    parser.add_argument("--sqlite", default="data/app.snapshot.db")
    parser.add_argument("--pg-dsn", default="postgresql://flow:flow@127.0.0.1:5433/flowdb")
    parser.add_argument("--schema", default="db/schema_postgres.sql")
    parser.add_argument("--batch-size", type=int, default=10000)
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite source not found: {sqlite_path}")

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = None

    with psycopg.connect(args.pg_dsn, autocommit=False) as pg_conn:
        _create_schema(pg_conn, Path(args.schema))
        _truncate_all(pg_conn)
        for table in TABLES_IN_ORDER:
            count = _copy_table(sqlite_conn, pg_conn, table, args.batch_size)
            print(f"{table}: {count}")
        _set_sequences(pg_conn)

    sqlite_conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    main()
