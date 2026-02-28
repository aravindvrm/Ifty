from pathlib import Path
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

POSTGRES_BOOTSTRAP_VERSION = "2026-02-28.1"


def _ensure_sqlite_parent_exists(db_url: str) -> None:
    if not db_url.startswith("sqlite:///"):
        return
    db_path = db_url.replace("sqlite:///", "", 1)
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    _ensure_sqlite_parent_exists(settings.api_db_url)
    if settings.api_db_url.startswith("sqlite:///"):
        return create_engine(settings.api_db_url, future=True)
    return create_engine(
        settings.api_db_url,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
        connect_args={"options": f"-c statement_timeout={settings.db_statement_timeout_ms}"},
    )


SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, class_=Session)


def get_db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def ensure_schema_and_seed(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        # Postgres path: schema is expected to be provisioned via migration tooling.
        # Seed defaults only if the target table exists.
        with engine.begin() as conn:
            # Bootstrap/repair can run long on large datasets; do not inherit request timeout.
            conn.execute(text("SET LOCAL statement_timeout = 0"))
            table_exists = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = 'api_budgets'
                    LIMIT 1
                    """
                )
            ).first()
            if not table_exists:
                return
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS app_bootstrap_meta (
                      key TEXT PRIMARY KEY,
                      value TEXT NOT NULL,
                      updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            applied_version = conn.execute(
                text(
                    """
                    SELECT value
                    FROM app_bootstrap_meta
                    WHERE key = 'postgres_bootstrap_version'
                    LIMIT 1
                    """
                )
            ).scalar()
            if applied_version == POSTGRES_BOOTSTRAP_VERSION:
                return
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS cusip_ticker_xwalk (
                      cusip TEXT PRIMARY KEY,
                      ticker TEXT,
                      figi TEXT,
                      name TEXT,
                      mic TEXT,
                      source TEXT NOT NULL,
                      confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                      first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      last_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_cusip_xwalk_ticker
                    ON cusip_ticker_xwalk (ticker)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS pipeline_run_events (
                      run_id TEXT NOT NULL,
                      event_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      stage TEXT NOT NULL,
                      status TEXT NOT NULL,
                      message TEXT,
                      metrics_json TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_pipeline_events_run_ts
                    ON pipeline_run_events (run_id, event_ts)
                    """
                )
            )
            # Keep one canonical row per (id_type, id_value) before enforcing uniqueness.
            conn.execute(
                text(
                    """
                    WITH ranked AS (
                      SELECT
                        identifier_id,
                        ROW_NUMBER() OVER (
                          PARTITION BY id_type, id_value
                          ORDER BY
                            confidence DESC,
                            CASE WHEN valid_to IS NULL THEN 0 ELSE 1 END,
                            valid_from DESC,
                            identifier_id DESC
                        ) AS rn
                      FROM security_identifiers
                    )
                    DELETE FROM security_identifiers si
                    USING ranked r
                    WHERE si.identifier_id = r.identifier_id
                      AND r.rn > 1
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_identifiers_type_value
                    ON security_identifiers (id_type, id_value)
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_13f_report_date ON holdings_13f (report_date)"))
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_13f_manager_report_date
                    ON holdings_13f (manager_id, report_date)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_13f_cusip_norm_mapped_nonopt
                    ON holdings_13f (UPPER(REPLACE(REPLACE(TRIM(cusip_raw), '-', ''), ' ', '')))
                    WHERE cusip_raw IS NOT NULL
                      AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                      AND option_type IS NULL
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_13f_security_report_date
                    ON holdings_13f (security_id, report_date)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_13f_security_report_date_mapped_nonopt
                    ON holdings_13f (security_id, report_date)
                    WHERE mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                      AND option_type IS NULL
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_13f_filing_id
                    ON holdings_13f (filing_id)
                    """
                )
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_ident_idtype_idvalue ON security_identifiers (id_type, id_value)")
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_ident_cusip_norm
                    ON security_identifiers (UPPER(REPLACE(REPLACE(TRIM(id_value), '-', ''), ' ', '')))
                    WHERE id_type = 'CUSIP'
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_ident_ticker_upper
                    ON security_identifiers (UPPER(id_value))
                    WHERE id_type = 'TICKER'
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO api_budgets (provider, max_per_minute, max_per_day, burst_per_second, notes, updated_at)
                    VALUES
                      ('SEC', 480, NULL, 8, 'Keep below SEC 10 req/s policy; always send compliant User-Agent.', CURRENT_TIMESTAMP),
                      ('POLYGON', 5, NULL, NULL, 'Free tier: 5 requests/minute.', CURRENT_TIMESTAMP),
                      ('AV', NULL, 25, NULL, 'Free tier: reserve for low-frequency backfills.', CURRENT_TIMESTAMP),
                      ('YF', 30, NULL, NULL, 'Unofficial source; local conservative cap with caching.', CURRENT_TIMESTAMP),
                      ('OPENFIGI', 20, NULL, NULL, 'CUSIP to ticker enrichment budget.', CURRENT_TIMESTAMP)
                    ON CONFLICT(provider) DO UPDATE SET
                      max_per_minute = excluded.max_per_minute,
                      max_per_day = excluded.max_per_day,
                      burst_per_second = excluded.burst_per_second,
                      notes = excluded.notes,
                      updated_at = CURRENT_TIMESTAMP
                    """
                )
            )
            id_cols = [
                ("issuers", "issuer_id"),
                ("securities", "security_id"),
                ("security_identifiers", "identifier_id"),
                ("corporate_actions", "action_id"),
                ("security_alias_links", "link_id"),
                ("managers", "manager_id"),
                ("filings", "filing_id"),
                ("holdings_13f", "holding_13f_id"),
                ("beneficial_ownership_events", "bo_event_id"),
                ("api_request_log", "request_id"),
            ]
            for table, col in id_cols:
                seq = f"{table}_{col}_seq"
                conn.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq}"))
                conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} SET DEFAULT nextval('{seq}')"))
                conn.execute(
                    text(
                        f"""
                        SELECT setval(
                          '{seq}',
                          COALESCE((SELECT MAX({col}) FROM {table}), 1),
                          true
                        )
                        """
                    )
                )
            conn.execute(
                text(
                    """
                    INSERT INTO app_bootstrap_meta (key, value, updated_at)
                    VALUES ('postgres_bootstrap_version', :version, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE
                    SET value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {"version": POSTGRES_BOOTSTRAP_VERSION},
            )
        return

    root = Path(__file__).resolve().parent.parent
    schema_sql = (root / "db" / "schema.sql").read_text(encoding="utf-8")
    seed_sql = (root / "db" / "seed_api_budgets.sql").read_text(encoding="utf-8")
    with engine.begin() as conn:
        raw = conn.connection
        raw.executescript(schema_sql)
        raw.executescript(seed_sql)
