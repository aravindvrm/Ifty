from datetime import UTC, date, datetime, timedelta
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.analytics.aggregates import AggregateRefreshService
from app.clients.sec_client import SecClient
from app.dependencies import get_db, get_sec_client
from app.ingest.sec_13f import Sec13FIngestionService
from app.ingest.sec_13dg import Sec13DGIngestionService
from app.pipeline.universe import ManagerUniverseService
from app.resolution.security_resolver import SecurityResolverService
from app.resolution.ticker_enrichment import TickerEnrichmentService
from app.enrichment.cusip_to_ticker import CusipToTickerEnrichmentService, NoopCusipProvider, OpenFigiCusipProvider
from app.clients.rate_limit import ProviderRateLimiter
from app.config import get_settings

router = APIRouter()


def _split_factor_between(db: Session, security_id: int, prev_date: str, curr_date: str) -> float:
    rows = db.execute(
        text(
            """
            SELECT split_factor_num, split_factor_den
            FROM corporate_actions
            WHERE security_id = :security_id
              AND action_type = 'SPLIT'
              AND ex_date > :prev_date
              AND ex_date <= :curr_date
            ORDER BY ex_date ASC
            """
        ),
        {"security_id": security_id, "prev_date": prev_date, "curr_date": curr_date},
    ).mappings().all()
    factor = 1.0
    for row in rows:
        num = float(row["split_factor_num"] or 1.0)
        den = float(row["split_factor_den"] or 1.0)
        if den != 0:
            factor *= num / den
    return factor


def _lookup_active_security_by_ticker(db: Session, ticker: str):
    return db.execute(
        text(
            """
            SELECT
              si.security_id,
              si.id_value AS ticker,
              COALESCE(si.mic, '') AS mic,
              COALESCE(s.security_name, i.issuer_name, '') AS security_name
            FROM security_identifiers si
            JOIN securities s ON s.security_id = si.security_id
            LEFT JOIN issuers i ON i.issuer_id = s.issuer_id
            WHERE si.id_type = 'TICKER'
              AND UPPER(si.id_value) = UPPER(:ticker)
              AND date('now') >= date(si.valid_from)
              AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
              AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
            ORDER BY si.valid_from DESC
            LIMIT 1
            """
        ),
        {"ticker": ticker},
    ).mappings().first()


def _previous_quarter_end(period_end_date: str) -> str | None:
    try:
        dt = date.fromisoformat(period_end_date)
    except ValueError:
        return None
    if dt.month <= 3:
        return f"{dt.year - 1}-12-31"
    if dt.month <= 6:
        return f"{dt.year}-03-31"
    if dt.month <= 9:
        return f"{dt.year}-06-30"
    return f"{dt.year}-09-30"


def _resolve_security_scope_ids(db: Session, ticker: str) -> list[int]:
    seed_rows = db.execute(
        text(
            """
            SELECT DISTINCT si.security_id
            FROM security_identifiers si
            JOIN securities s ON s.security_id = si.security_id
            WHERE si.id_type = 'TICKER'
              AND UPPER(si.id_value) = UPPER(:ticker)
              AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
            """
        ),
        {"ticker": ticker},
    ).all()
    seed_ids = [int(x[0]) for x in seed_rows if x and x[0] is not None]
    if not seed_ids:
        return []

    scope_ids = set(seed_ids)

    alias_rows = db.execute(
        text(
            """
            SELECT from_security_id, to_security_id
            FROM security_alias_links
            WHERE from_security_id IN :seed_ids
               OR to_security_id IN :seed_ids
            """
        ).bindparams(bindparam("seed_ids", expanding=True)),
        {"seed_ids": seed_ids},
    ).all()
    for from_security_id, to_security_id in alias_rows:
        if from_security_id is not None:
            scope_ids.add(int(from_security_id))
        if to_security_id is not None:
            scope_ids.add(int(to_security_id))

    base_scope = sorted(scope_ids)
    cusip_rows = db.execute(
        text(
            """
            SELECT DISTINCT UPPER(REPLACE(REPLACE(TRIM(si.id_value), '-', ''), ' ', '')) AS cusip
            FROM security_identifiers si
            WHERE si.id_type = 'CUSIP'
              AND si.security_id IN :scope_ids
              AND si.id_value IS NOT NULL
              AND TRIM(si.id_value) <> ''
            """
        ).bindparams(bindparam("scope_ids", expanding=True)),
        {"scope_ids": base_scope},
    ).all()
    cusips = {str(x[0]) for x in cusip_rows if x and x[0]}

    if not cusips:
        fallback_cusips = db.execute(
            text(
                """
                SELECT DISTINCT UPPER(REPLACE(REPLACE(TRIM(h.cusip_raw), '-', ''), ' ', '')) AS cusip
                FROM holdings_13f h
                WHERE h.security_id IN :scope_ids
                  AND h.cusip_raw IS NOT NULL
                  AND TRIM(h.cusip_raw) <> ''
                  AND h.option_type IS NULL
                  AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                LIMIT 64
                """
            ).bindparams(bindparam("scope_ids", expanding=True)),
            {"scope_ids": base_scope},
        ).all()
        cusips = {str(x[0]) for x in fallback_cusips if x and x[0]}

    if not cusips:
        return sorted(scope_ids)

    by_identifier_rows = db.execute(
        text(
            """
            SELECT DISTINCT si.security_id
            FROM security_identifiers si
            JOIN securities s ON s.security_id = si.security_id
            WHERE si.id_type = 'CUSIP'
              AND UPPER(REPLACE(REPLACE(TRIM(si.id_value), '-', ''), ' ', '')) IN :cusips
              AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
            """
        ).bindparams(bindparam("cusips", expanding=True)),
        {"cusips": sorted(cusips)},
    ).all()
    for row in by_identifier_rows:
        if row and row[0] is not None:
            scope_ids.add(int(row[0]))

    recent_dates = [
        str(x[0])
        for x in db.execute(
            text(
                """
                SELECT DISTINCT report_date
                FROM holdings_13f
                WHERE mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                  AND option_type IS NULL
                ORDER BY report_date DESC
                LIMIT 8
                """
            )
        ).all()
    ]
    if recent_dates:
        by_holding_rows = db.execute(
            text(
                """
                SELECT DISTINCT h.security_id
                FROM holdings_13f h
                JOIN securities s ON s.security_id = h.security_id
                WHERE h.security_id IS NOT NULL
                  AND h.option_type IS NULL
                  AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                  AND UPPER(REPLACE(REPLACE(TRIM(h.cusip_raw), '-', ''), ' ', '')) IN :cusips
                  AND h.report_date IN :recent_dates
                  AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
                """
            ).bindparams(bindparam("cusips", expanding=True), bindparam("recent_dates", expanding=True)),
            {"cusips": sorted(cusips), "recent_dates": recent_dates},
        ).all()
        for row in by_holding_rows:
            if row and row[0] is not None:
                scope_ids.add(int(row[0]))

    return sorted(scope_ids)


def _value_to_usd_multiplier(db: Session) -> float:
    """
    Detect whether holdings_13f.value_usd_thousands is stored in USD or in USD-thousands.

    Heuristic:
    - If AVG(value / shares) is close to normal share prices, values are already USD.
    - If AVG(value / shares) is tiny, values are USD-thousands and need * 1000.
    """
    avg_value_per_share = db.execute(
        text(
            """
            SELECT AVG(vps)
            FROM (
              SELECT
                COALESCE(value_usd_thousands, 0) / NULLIF(COALESCE(shares, 0), 0) AS vps
              FROM holdings_13f
              WHERE security_id IS NOT NULL
                AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                AND option_type IS NULL
                AND COALESCE(value_usd_thousands, 0) > 0
                AND COALESCE(shares, 0) > 0
              ORDER BY holding_13f_id DESC
              LIMIT 4000
            ) q
            """
        )
    ).scalar()
    if avg_value_per_share is None:
        return 1000.0
    avg_vps = float(avg_value_per_share or 0.0)
    return 1.0 if avg_vps >= 2.0 else 1000.0


def _raw_value_to_usd_thousands(raw_value: float, value_to_usd_multiplier: float) -> float:
    return (raw_value * value_to_usd_multiplier) / 1000.0


def _manager_filing_row(
    db: Session,
    manager_id: int,
    before_period_end_date: str | None = None,
    require_mapped_positions: bool = True,
):
    filters = [
        "f.manager_id = :manager_id",
        "f.form_type IN ('13F-HR', '13F-HR/A')",
        "f.period_end_date IS NOT NULL",
    ]
    params: dict[str, object] = {"manager_id": manager_id}
    if before_period_end_date is not None:
        filters.append("f.period_end_date < :before_period_end_date")
        params["before_period_end_date"] = before_period_end_date
    if require_mapped_positions:
        filters.append(
            """
            EXISTS (
              SELECT 1
              FROM holdings_13f h
              WHERE h.filing_id = f.filing_id
                AND h.security_id IS NOT NULL
                AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                AND h.option_type IS NULL
            )
            """
        )
    return db.execute(
        text(
            f"""
            SELECT
              f.filing_id,
              f.period_end_date,
              f.filed_at,
              f.form_type,
              f.accession_no
            FROM filings f
            WHERE {' AND '.join(filters)}
            ORDER BY
              f.period_end_date DESC,
              COALESCE(f.filed_at, '') DESC,
              COALESCE(f.is_amendment, 0) DESC,
              f.accession_no DESC
            LIMIT 1
            """
        ),
        params,
    ).mappings().first()


def _manager_prior_comparison_filing(
    db: Session,
    manager_id: int,
    latest_period_end_date: str,
    curr_positions_count: int,
    curr_total_raw_value: float,
):
    target_prev_period_end = _previous_quarter_end(latest_period_end_date)
    if not target_prev_period_end:
        return None
    min_rows = max(1, int(curr_positions_count * 0.20))
    min_total_raw = curr_total_raw_value * 0.20 if curr_total_raw_value > 0 else 0.0
    candidate = db.execute(
        text(
            """
            WITH prior AS (
              SELECT
                f.filing_id,
                f.period_end_date,
                f.filed_at,
                f.form_type,
                f.accession_no,
                COUNT(h.holding_13f_id) AS mapped_rows,
                COALESCE(SUM(COALESCE(h.value_usd_thousands, 0)), 0) AS total_raw
              FROM filings f
              LEFT JOIN holdings_13f h
                ON h.filing_id = f.filing_id
               AND h.security_id IS NOT NULL
               AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
               AND h.option_type IS NULL
              WHERE f.manager_id = :manager_id
                AND f.form_type IN ('13F-HR', '13F-HR/A')
                AND f.period_end_date IS NOT NULL
                AND f.period_end_date = :target_prev_period_end
              GROUP BY f.filing_id, f.period_end_date, f.filed_at, f.form_type, f.accession_no
            )
            SELECT filing_id, period_end_date, filed_at, form_type, accession_no, mapped_rows, total_raw
            FROM prior
            WHERE mapped_rows >= :min_rows
              AND total_raw >= :min_total_raw
            ORDER BY period_end_date DESC, COALESCE(filed_at, '') DESC, accession_no DESC
            LIMIT 1
            """
        ),
        {
            "manager_id": manager_id,
            "target_prev_period_end": target_prev_period_end,
            "min_rows": min_rows,
            "min_total_raw": min_total_raw,
        },
    ).mappings().first()
    return candidate


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/ingest/sec/13f")
def ingest_sec_13f(
    cik: str = Query(..., description="Manager CIK (with or without leading zeros)."),
    limit: int = Query(20, ge=1, le=200, description="Max matching 13F forms to ingest."),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    try:
        service = Sec13FIngestionService(db=db, sec_client=get_sec_client(db))
        result = service.ingest_for_cik(cik=cik, limit=limit)
        return {
            "filings_upserted": result.filings_upserted,
            "holdings_inserted": result.holdings_inserted,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ingest/sec/13dg")
def ingest_sec_13dg(
    cik: str = Query(..., description="Manager CIK (with or without leading zeros)."),
    limit: int = Query(20, ge=1, le=200, description="Max matching 13D/G forms to ingest."),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    try:
        service = Sec13DGIngestionService(db=db, sec_client=get_sec_client(db))
        result = service.ingest_for_cik(cik=cik, limit=limit)
        return {
            "filings_upserted": result.filings_upserted,
            "events_inserted": result.events_inserted,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/resolve-mappings")
def resolve_mappings(
    limit: int = Query(0, ge=0, le=100000),
    db: Session = Depends(get_db),
) -> dict:
    service = SecurityResolverService(db=db)
    summary = service.resolve_all(limit=limit or None)
    return {
        "bootstrap_created": summary.bootstrap_created,
        "holdings_mapped": summary.holdings_mapped,
        "bo_events_mapped": summary.bo_events_mapped,
        "holdings_batches": summary.holdings_batches or [],
        "bo_batches": summary.bo_batches or [],
    }


@router.post("/jobs/refresh-aggregates")
def refresh_aggregates(
    db: Session = Depends(get_db),
) -> dict[str, int]:
    service = AggregateRefreshService(db=db)
    summary = service.refresh_all()
    return {"security_rows": summary.security_rows, "manager_rows": summary.manager_rows}


@router.post("/jobs/sync-tickers")
def sync_tickers(
    limit: int = Query(0, ge=0, le=100000),
    recent_quarters: int = Query(4, ge=1, le=16),
    min_holders: int = Query(3, ge=1, le=1000),
    min_total_value_usd: float = Query(250_000_000.0, ge=0),
    universe_only: int = Query(1, ge=0, le=1),
    db: Session = Depends(get_db),
    sec_client: SecClient = Depends(get_sec_client),
) -> dict[str, int]:
    service = TickerEnrichmentService(db=db, sec_client=sec_client)
    summary = service.sync_from_sec_company_tickers(
        limit=limit or None,
        recent_quarters=recent_quarters,
        min_holders=min_holders,
        min_total_value_usd=min_total_value_usd,
        universe_only=bool(universe_only),
    )
    return {"scanned": summary.scanned, "matched": summary.matched, "inserted": summary.inserted}


@router.post("/jobs/refresh-universe")
def refresh_universe(
    top_n: int = Query(300, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    service = ManagerUniverseService(db=db)
    summary = service.refresh_top_n(top_n=top_n)
    return {"as_of_report_date": summary.as_of_report_date, "selected": summary.selected}


@router.post("/jobs/enrich-cusips")
def enrich_cusips(
    recent_quarters: int = Query(4, ge=1, le=16),
    top_n: int = Query(300, ge=1, le=5000),
    min_holders: int = Query(3, ge=1, le=1000),
    min_total_value_usd: float = Query(250_000_000.0, ge=0),
    provider: str = Query("noop", pattern="^(noop|openfigi)$"),
    limit_cusips: int = Query(0, ge=0, le=200000),
    db: Session = Depends(get_db),
) -> dict:
    if provider == "openfigi":
        settings = get_settings()
        limiter = ProviderRateLimiter()
        rpm = float(settings.openfigi_requests_per_minute)
        limiter.register(provider="OPENFIGI", rate_per_sec=max(0.01, rpm / 60.0))
        p = OpenFigiCusipProvider(db=db, limiter=limiter)
    else:
        p = NoopCusipProvider()

    summary = CusipToTickerEnrichmentService(db=db, provider=p).enrich_in_scope(
        recent_quarters=recent_quarters,
        top_n=top_n,
        min_holders=min_holders,
        min_total_value_usd=min_total_value_usd,
        limit_cusips=(limit_cusips or None),
    )
    return {
        "scanned": summary.scanned,
        "eligible": summary.eligible,
        "matched": summary.matched,
        "inserted_xwalk": summary.inserted_xwalk,
        "inserted_identifiers": summary.inserted_identifiers,
    }


@router.get("/ops/manager-universe")
def manager_universe(
    limit_n: int = Query(300, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        text(
            """
            SELECT
              u.rank,
              u.manager_id,
              m.cik,
              m.manager_name,
              u.total_value_usd,
              u.as_of_report_date,
              u.is_active
            FROM manager_universe u
            JOIN managers m ON m.manager_id = u.manager_id
            ORDER BY u.rank
            LIMIT :limit_n
            """
        ),
        {"limit_n": limit_n},
    ).mappings().all()
    return {"rows": [dict(x) for x in rows]}


@router.get("/ops/api-usage")
def api_usage(
    days: int = Query(7, ge=1, le=90),
    limit_n: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> dict:
    cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    summary = db.execute(
        text(
            """
            SELECT
              provider,
              COUNT(*) AS calls,
              SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END) AS ok_calls,
              SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS error_calls,
              AVG(COALESCE(latency_ms, 0)) AS avg_latency_ms
            FROM api_request_log
            WHERE request_ts >= :cutoff
            GROUP BY provider
            ORDER BY calls DESC
            """
        ),
        {"cutoff": cutoff},
    ).mappings().all()

    recent = db.execute(
        text(
            """
            SELECT provider, endpoint, request_ts, status_code, ok, latency_ms, cache_hit
            FROM api_request_log
            ORDER BY request_id DESC
            LIMIT :limit_n
            """
        ),
        {"limit_n": limit_n},
    ).mappings().all()
    return {"summary": [dict(x) for x in summary], "recent": [dict(x) for x in recent]}


@router.get("/ops/pipeline-runs/latest")
def pipeline_runs_latest(
    db: Session = Depends(get_db),
) -> dict:
    row = db.execute(
        text(
            """
            SELECT run_id
            FROM pipeline_run_events
            ORDER BY event_ts DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    if not row:
        return {"run_id": None, "events": []}
    run_id = str(row["run_id"])
    events = db.execute(
        text(
            """
            SELECT run_id, event_ts, stage, status, message, metrics_json
            FROM pipeline_run_events
            WHERE run_id = :run_id
            ORDER BY event_ts
            """
        ),
        {"run_id": run_id},
    ).mappings().all()
    parsed_events = []
    for event in events:
        row_dict = dict(event)
        metrics_raw = row_dict.get("metrics_json")
        if isinstance(metrics_raw, str) and metrics_raw:
            try:
                row_dict["metrics"] = json.loads(metrics_raw)
            except Exception:
                row_dict["metrics"] = {"_raw": metrics_raw}
        else:
            row_dict["metrics"] = {}
        parsed_events.append(row_dict)
    current = parsed_events[-1] if parsed_events else None
    return {"run_id": run_id, "current": current, "events": parsed_events}


@router.get("/security/search")
def security_search(
    q: str = Query(..., min_length=1, description="Ticker or issuer/security name fragment."),
    limit_n: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    q_norm = q.strip().upper()
    # Fast path for ticker-like queries to avoid broad name scans.
    if q_norm and q_norm.replace(".", "").replace("-", "").isalnum() and len(q_norm) <= 12:
        fast_rows = db.execute(
            text(
                """
                SELECT
                  s.security_id,
                  s.security_name,
                  i.issuer_name,
                  si.id_value AS ticker,
                  COALESCE(si.mic, '') AS mic
                FROM security_identifiers si
                JOIN securities s ON s.security_id = si.security_id
                JOIN issuers i ON i.issuer_id = s.issuer_id
                WHERE si.id_type = 'TICKER'
                  AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                  AND UPPER(si.id_value) LIKE :q_prefix
                  AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
                  AND UPPER(COALESCE(s.security_name, '')) NOT LIKE 'PUT %'
                  AND UPPER(COALESCE(s.security_name, '')) NOT LIKE 'CALL %'
                  AND UPPER(COALESCE(s.security_name, '')) NOT LIKE '%OPTION ROOT=%'
                ORDER BY
                  CASE WHEN UPPER(si.id_value) = :q_exact THEN 0 ELSE 1 END,
                  s.security_id DESC
                LIMIT :limit_n
                """
            ),
            {"q_prefix": f"{q_norm}%", "q_exact": q_norm, "limit_n": limit_n},
        ).mappings().all()
        if fast_rows:
            return {"query": q, "rows": [dict(x) for x in fast_rows]}

    rows = db.execute(
        text(
            """
            SELECT
              s.security_id,
              s.security_name,
              i.issuer_name,
              MAX(CASE WHEN si.id_type = 'TICKER' THEN si.id_value END) AS ticker,
              MAX(CASE WHEN si.id_type = 'TICKER' THEN COALESCE(si.mic, '') END) AS mic
            FROM securities s
            JOIN issuers i ON i.issuer_id = s.issuer_id
            LEFT JOIN security_identifiers si
              ON si.security_id = s.security_id
             AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
            WHERE
              (
                UPPER(COALESCE(s.security_name, '')) LIKE UPPER(:q_like)
                OR UPPER(COALESCE(i.issuer_name, '')) LIKE UPPER(:q_like)
                OR EXISTS (
                  SELECT 1
                  FROM security_identifiers sx
                  WHERE sx.security_id = s.security_id
                    AND sx.id_type = 'TICKER'
                    AND UPPER(sx.id_value) LIKE UPPER(:q_like)
                    AND (sx.valid_to IS NULL OR date('now') < date(sx.valid_to))
                )
              )
              AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
              AND UPPER(COALESCE(s.security_name, '')) NOT LIKE 'PUT %'
              AND UPPER(COALESCE(s.security_name, '')) NOT LIKE 'CALL %'
              AND UPPER(COALESCE(s.security_name, '')) NOT LIKE '%OPTION ROOT=%'
              AND EXISTS (
                SELECT 1
                FROM security_identifiers st
                WHERE st.security_id = s.security_id
                  AND st.id_type = 'TICKER'
                  AND (st.valid_to IS NULL OR date('now') < date(st.valid_to))
              )
            GROUP BY s.security_id, s.security_name, i.issuer_name
            ORDER BY
              CASE WHEN UPPER(COALESCE(MAX(CASE WHEN si.id_type='TICKER' THEN si.id_value END), '')) = UPPER(:q_exact) THEN 0 ELSE 1 END,
              s.security_id DESC
            LIMIT :limit_n
            """
        ),
        {
            "q_like": f"%{q}%",
            "q_exact": q,
            "limit_n": limit_n,
        },
    ).mappings().all()
    return {"query": q, "rows": [dict(x) for x in rows]}


@router.get("/security/{ticker}")
def security_page(
    ticker: str,
    db: Session = Depends(get_db),
) -> dict:
    value_to_usd_multiplier = _value_to_usd_multiplier(db=db)
    sec_row = _lookup_active_security_by_ticker(db=db, ticker=ticker)
    if not sec_row:
        raise HTTPException(status_code=404, detail=f"No active security mapping found for ticker '{ticker}'.")

    security_id = int(sec_row["security_id"])
    scope_ids = _resolve_security_scope_ids(db=db, ticker=ticker)
    if not scope_ids:
        scope_ids = [security_id]
    latest_date = db.execute(
        text(
            """
            SELECT MAX(report_date) AS report_date
            FROM holdings_13f
            WHERE security_id IN :scope_ids
              AND option_type IS NULL
              AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
            """
        ).bindparams(bindparam("scope_ids", expanding=True)),
        {"scope_ids": scope_ids},
    ).scalar()
    if latest_date is None:
        return {
            "security_id": security_id,
            "ticker": sec_row["ticker"],
            "security_name": sec_row["security_name"],
            "mic": sec_row["mic"],
            "latest_quarter": None,
            "top_holders": [],
            "active_positions": [],
            "net_change_last_4q": [],
            "ownership_summary": {},
            "activity_breakdown": {},
            "concentration": {},
        }

    prev_date = db.execute(
        text(
            """
            SELECT report_date
            FROM holdings_13f
            WHERE security_id IN :scope_ids
              AND option_type IS NULL
              AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
              AND report_date < :latest_date
            GROUP BY report_date
            ORDER BY report_date DESC
            LIMIT 1
            """
        ).bindparams(bindparam("scope_ids", expanding=True)),
        {"scope_ids": scope_ids, "latest_date": latest_date},
    ).scalar()

    latest_positions_rows = db.execute(
        text(
            """
            SELECT
              h.manager_id,
              m.manager_name,
              SUM(COALESCE(h.shares, 0)) AS shares,
              SUM(COALESCE(h.value_usd_thousands, 0)) AS value_usd_thousands
            FROM holdings_13f h
            JOIN managers m ON m.manager_id = h.manager_id
            WHERE h.security_id IN :scope_ids
              AND h.report_date = :report_date
              AND h.option_type IS NULL
              AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
            GROUP BY h.manager_id, m.manager_name
            ORDER BY shares DESC
            """
        ).bindparams(bindparam("scope_ids", expanding=True)),
        {"scope_ids": scope_ids, "report_date": latest_date},
    ).mappings().all()
    latest_positions = [dict(x) for x in latest_positions_rows]
    latest_by_manager = {int(x["manager_id"]): x for x in latest_positions}
    prev_by_manager: dict[int, float] = {}
    if prev_date:
        prev_rows = db.execute(
            text(
                """
                SELECT manager_id, SUM(COALESCE(shares, 0)) AS shares
                FROM holdings_13f
                WHERE security_id IN :scope_ids
                  AND report_date = :report_date
                  AND option_type IS NULL
                  AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                GROUP BY manager_id
                """
            ).bindparams(bindparam("scope_ids", expanding=True)),
            {"scope_ids": scope_ids, "report_date": prev_date},
        ).mappings().all()
        prev_by_manager = {int(x["manager_id"]): float(x["shares"] or 0.0) for x in prev_rows}

    split_factor = 1.0
    if prev_date:
        split_factor = _split_factor_between(db=db, security_id=security_id, prev_date=prev_date, curr_date=latest_date)

    active_positions: list[dict] = []
    total_shares = 0.0
    total_value_usd = 0.0
    for row in latest_positions:
        manager_id = int(row["manager_id"])
        curr_shares = float(row["shares"] or 0.0)
        prev_shares = float(prev_by_manager.get(manager_id, 0.0))
        qoq_delta = curr_shares - (prev_shares * split_factor if prev_date else 0.0)
        total_shares += curr_shares
        raw_value = float(row["value_usd_thousands"] or 0.0)
        value_usd = raw_value * value_to_usd_multiplier
        value_usd_thousands = _raw_value_to_usd_thousands(
            raw_value=raw_value,
            value_to_usd_multiplier=value_to_usd_multiplier,
        )
        total_value_usd += value_usd
        active_positions.append(
            {
                "manager_id": manager_id,
                "manager_name": row["manager_name"],
                "shares": curr_shares,
                "value_usd_thousands": value_usd_thousands,
                "qoq_delta_shares": qoq_delta,
                # Avoid expensive manager-universe totals query in hot path.
                "pct_manager_portfolio": None,
                "is_new": prev_shares <= 0 and curr_shares > 0,
            }
        )
    active_positions = sorted(active_positions, key=lambda x: x["shares"], reverse=True)

    manager_union = set(latest_by_manager.keys()) | set(prev_by_manager.keys())
    new_count = 0
    increased_count = 0
    decreased_count = 0
    sold_out_count = 0
    qoq_net_change_shares = 0.0
    for manager_id in manager_union:
        curr_shares = float(latest_by_manager.get(manager_id, {}).get("shares", 0.0))
        prev_shares = float(prev_by_manager.get(manager_id, 0.0))
        prev_adj = prev_shares * split_factor if prev_date else 0.0
        delta = curr_shares - prev_adj
        qoq_net_change_shares += delta
        if curr_shares > 0 and prev_shares <= 0:
            new_count += 1
        elif curr_shares > 0 and prev_shares > 0 and delta > 0:
            increased_count += 1
        elif curr_shares > 0 and prev_shares > 0 and delta < 0:
            decreased_count += 1
        elif curr_shares <= 0 and prev_shares > 0:
            sold_out_count += 1
    holders_count = len(latest_by_manager)
    top_holders = [
        {
            "manager_id": row["manager_id"],
            "manager_name": row["manager_name"],
            "shares": row["shares"],
            "value_usd_thousands": row["value_usd_thousands"],
        }
        for row in active_positions[:50]
    ]

    quarter_dates_for_calc = [
        x[0]
        for x in db.execute(
            text(
                """
                SELECT DISTINCT report_date
                FROM holdings_13f
                WHERE security_id IN :scope_ids
                  AND option_type IS NULL
                  AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                ORDER BY report_date DESC
                LIMIT 5
                """
            ).bindparams(bindparam("scope_ids", expanding=True)),
            {"scope_ids": scope_ids},
        ).all()
    ]
    quarter_dates_display = quarter_dates_for_calc[:4]
    quarter_dates_for_calc_set = set(quarter_dates_for_calc)
    quarter_dates_display_set = set(quarter_dates_display)
    net_change_rows = db.execute(
        text(
            """
            SELECT
              h.manager_id,
              m.manager_name,
              h.report_date,
              SUM(COALESCE(h.shares, 0)) AS shares
            FROM holdings_13f h
            JOIN managers m ON m.manager_id = h.manager_id
            WHERE h.security_id IN :scope_ids
              AND h.report_date IN :quarter_dates
              AND h.option_type IS NULL
              AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
            GROUP BY h.manager_id, m.manager_name, h.report_date
            ORDER BY h.manager_id, h.report_date
            """
        ).bindparams(bindparam("scope_ids", expanding=True), bindparam("quarter_dates", expanding=True)),
        {"scope_ids": scope_ids, "quarter_dates": list(quarter_dates_for_calc_set)},
    ).mappings().all() if quarter_dates_for_calc else []

    per_manager: dict[int, list[dict]] = {}
    for row in net_change_rows:
        per_manager.setdefault(int(row["manager_id"]), []).append(dict(row))
    split_factor_cache: dict[tuple[str, str], float] = {}
    net_change: list[dict] = []
    for manager_id, manager_rows in per_manager.items():
        manager_rows = sorted(manager_rows, key=lambda r: r["report_date"])
        prev_shares: float | None = None
        prev_date: str | None = None
        manager_name = manager_rows[0]["manager_name"]
        for row in manager_rows:
            curr_date = row["report_date"]
            curr_shares = float(row["shares"] or 0.0)
            if prev_shares is None or prev_date is None:
                delta = curr_shares
            else:
                pair = (str(prev_date), str(curr_date))
                factor = split_factor_cache.get(pair)
                if factor is None:
                    factor = _split_factor_between(db=db, security_id=security_id, prev_date=prev_date, curr_date=curr_date)
                    split_factor_cache[pair] = factor
                delta = curr_shares - (prev_shares * factor)
            if curr_date in quarter_dates_display_set:
                net_change.append(
                    {
                        "manager_id": manager_id,
                        "manager_name": manager_name,
                        "report_date": curr_date,
                        "net_change_shares": delta,
                    }
                )
            prev_shares = curr_shares
            prev_date = curr_date
    net_change = sorted(net_change, key=lambda r: (r["report_date"], abs(r["net_change_shares"])), reverse=True)

    concentration = db.execute(
        text(
            """
            WITH manager_q AS (
              SELECT manager_id, SUM(COALESCE(shares, 0)) AS shares
              FROM holdings_13f
              WHERE security_id IN :scope_ids
                AND report_date = :report_date
                AND option_type IS NULL
                AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
              GROUP BY manager_id
            ),
            sums AS (
              SELECT
                COALESCE(SUM(shares), 0) AS total_shares,
                COALESCE((SELECT SUM(shares) FROM (SELECT shares FROM manager_q ORDER BY shares DESC LIMIT 10)), 0) AS top10_shares
              FROM manager_q
            )
            SELECT
              total_shares,
              top10_shares,
              CASE WHEN total_shares = 0 THEN 0 ELSE top10_shares * 1.0 / total_shares END AS top10_pct
            FROM sums
            """
        ).bindparams(bindparam("scope_ids", expanding=True)),
        {"scope_ids": scope_ids, "report_date": latest_date},
    ).mappings().first()

    return {
        "security_id": security_id,
        "ticker": sec_row["ticker"],
        "security_name": sec_row["security_name"],
        "mic": sec_row["mic"],
        "latest_quarter": latest_date,
        "top_holders": [dict(x) for x in top_holders],
        "active_positions": active_positions,
        "net_change_last_4q": [dict(x) for x in net_change],
        "ownership_summary": {
            "holders_count": holders_count,
            "total_shares": total_shares,
            "total_value_usd": total_value_usd,
            "qoq_net_change_shares": qoq_net_change_shares,
            "top10_concentration_pct": (dict(concentration).get("top10_pct", 0.0) if concentration else 0.0),
        },
        "activity_breakdown": {
            "total": holders_count,
            "new": new_count,
            "increased": increased_count,
            "decreased": decreased_count,
            "sold_out": sold_out_count,
            "activity": new_count + increased_count + decreased_count + sold_out_count,
        },
        "concentration": dict(concentration) if concentration else {},
    }




@router.get("/security/{ticker}/events")
def security_events_feed(
    ticker: str,
    limit_n: int = Query(100, ge=1, le=500),
    new_5pct_only: int = Query(0, ge=0, le=1),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    sec_row = _lookup_active_security_by_ticker(db=db, ticker=ticker)
    if not sec_row:
        raise HTTPException(status_code=404, detail=f"No active security mapping found for ticker '{ticker}'.")

    security_id = int(sec_row["security_id"])
    scope_ids = _resolve_security_scope_ids(db=db, ticker=ticker)
    if not scope_ids:
        scope_ids = [security_id]
    where_clauses = [
        "b.security_id IN :scope_ids",
        "(:new_5pct_only = 0 OR b.event_type = 'NEW_5PCT')",
    ]
    params: dict[str, object] = {
        "scope_ids": scope_ids,
        "limit_n": limit_n,
        "new_5pct_only": new_5pct_only,
    }
    if start_date is not None:
        where_clauses.append("CAST(b.report_date AS DATE) >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        where_clauses.append("CAST(b.report_date AS DATE) <= :end_date")
        params["end_date"] = end_date

    rows = db.execute(
        text(
            f"""
            SELECT
              b.report_date,
              b.event_type,
              b.percent_beneficial_owned,
              b.shares_beneficial_owned,
              b.cusip_raw,
              b.mapping_status,
              m.manager_name,
              f.form_type,
              f.accession_no
            FROM beneficial_ownership_events b
            LEFT JOIN managers m ON m.manager_id = b.manager_id
            JOIN filings f ON f.filing_id = b.filing_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY b.report_date DESC, b.bo_event_id DESC
            LIMIT :limit_n
            """
        ).bindparams(bindparam("scope_ids", expanding=True)),
        params,
    ).mappings().all()
    return {
        "security_id": security_id,
        "ticker": sec_row["ticker"],
        "rows": [dict(x) for x in rows],
    }


@router.get("/manager/{manager_key}")
def manager_page(
    manager_key: str,
    db: Session = Depends(get_db),
) -> dict:
    if manager_key.isdigit():
        row = db.execute(
            text("SELECT manager_id, cik, manager_name FROM managers WHERE manager_id = :key"),
            {"key": int(manager_key)},
        ).mappings().first()
    else:
        row = db.execute(
            text("SELECT manager_id, cik, manager_name FROM managers WHERE cik = :key"),
            {"key": manager_key},
        ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail=f"Manager '{manager_key}' not found.")

    manager_id = int(row["manager_id"])
    value_to_usd_multiplier = _value_to_usd_multiplier(db=db)
    latest_filing = _manager_filing_row(db=db, manager_id=manager_id, require_mapped_positions=True) or _manager_filing_row(
        db=db,
        manager_id=manager_id,
        require_mapped_positions=False,
    )
    if latest_filing is None:
        return {
            "manager": dict(row),
            "latest_quarter": None,
            "top_positions": [],
            "new_positions": [],
            "exited_positions": [],
            "metrics": {},
        }

    curr_filing_id = int(latest_filing["filing_id"])
    latest_date = str(latest_filing["period_end_date"])
    key_expr = "COALESCE(NULLIF(UPPER(REPLACE(REPLACE(TRIM(cusip_raw), '-', ''), ' ', '')), ''), 'SID:' || CAST(security_id AS TEXT))"

    top_positions_raw = db.execute(
        text(
            """
            WITH curr AS (
              SELECT
                """
            + key_expr
            + """
                AS match_key,
                MIN(security_id) AS security_id,
                MAX(issuer_name_raw) AS issuer_name_raw,
                MAX(class_title_raw) AS class_title_raw,
                SUM(COALESCE(shares, 0)) AS shares,
                SUM(COALESCE(value_usd_thousands, 0)) AS value_raw
              FROM holdings_13f
              WHERE filing_id = :curr_filing_id
                AND security_id IS NOT NULL
                AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                AND option_type IS NULL
              GROUP BY match_key
            )
            SELECT
              c.security_id,
              c.issuer_name_raw,
              c.class_title_raw,
              c.shares,
              c.value_raw,
              (
                SELECT si.id_value
                FROM security_identifiers si
                WHERE si.security_id = c.security_id
                  AND si.id_type = 'TICKER'
                ORDER BY si.identifier_id
                LIMIT 1
              ) AS ticker
            FROM curr c
            ORDER BY c.value_raw DESC
            LIMIT 50
            """
        ),
        {"curr_filing_id": curr_filing_id},
    ).mappings().all()
    top_positions: list[dict] = []
    for row_raw in top_positions_raw:
        row_dict = dict(row_raw)
        raw_value = float(row_dict.pop("value_raw") or 0.0)
        row_dict["value_usd_thousands"] = _raw_value_to_usd_thousands(
            raw_value=raw_value,
            value_to_usd_multiplier=value_to_usd_multiplier,
        )
        top_positions.append(row_dict)

    curr_totals = db.execute(
        text(
            """
            WITH curr AS (
              SELECT
                """
            + key_expr
            + """
                AS match_key,
                SUM(COALESCE(value_usd_thousands, 0)) AS curr_val
              FROM holdings_13f
              WHERE filing_id = :curr_filing_id
                AND security_id IS NOT NULL
                AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                AND option_type IS NULL
              GROUP BY match_key
            )
            SELECT
              COALESCE((SELECT SUM(curr_val) FROM curr), 0) AS total_curr,
              COALESCE((SELECT COUNT(*) FROM curr), 0) AS positions_count,
              COALESCE((
                SELECT SUM(curr_val)
                FROM (
                  SELECT curr_val
                  FROM curr
                  ORDER BY curr_val DESC
                  LIMIT 10
                )
              ), 0) AS top10_curr
            """
        ),
        {"curr_filing_id": curr_filing_id},
    ).mappings().first()
    total_curr_raw = float((curr_totals or {}).get("total_curr", 0.0) or 0.0)
    curr_positions_count = int((curr_totals or {}).get("positions_count", 0) or 0)
    top10_curr_raw = float((curr_totals or {}).get("top10_curr", 0.0) or 0.0)
    total_curr_usd = total_curr_raw * value_to_usd_multiplier

    new_positions: list[dict] = []
    exited_positions: list[dict] = []
    top_buys: list[dict] = []
    top_sells: list[dict] = []
    metrics: dict = {
        "turnover_ratio": None,
        "top10_concentration_pct": (top10_curr_raw / total_curr_raw) if total_curr_raw > 0 else 0.0,
        "new_positions_count": 0,
        "exited_positions_count": 0,
        "total_value_current": total_curr_usd,
        "total_value_previous": 0.0,
    }

    prev_filing = _manager_prior_comparison_filing(
        db=db,
        manager_id=manager_id,
        latest_period_end_date=latest_date,
        curr_positions_count=curr_positions_count,
        curr_total_raw_value=total_curr_raw,
    )
    if prev_filing:
        prev_date = str(prev_filing["period_end_date"])
        prev_filing_id = int(prev_filing["filing_id"])

        new_positions = [
            dict(x)
            for x in db.execute(
                text(
                    """
                    WITH curr AS (
                      SELECT
                        """
                    + key_expr
                    + """
                        AS match_key,
                        MIN(security_id) AS security_id,
                        MAX(issuer_name_raw) AS issuer_name_raw,
                        MAX(class_title_raw) AS class_title_raw,
                        SUM(COALESCE(value_usd_thousands, 0)) AS value_usd_thousands
                      FROM holdings_13f
                      WHERE filing_id = :curr_filing_id
                        AND security_id IS NOT NULL
                        AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                        AND option_type IS NULL
                      GROUP BY match_key
                    ),
                    prev AS (
                      SELECT
                        """
                    + key_expr
                    + """
                        AS match_key
                      FROM holdings_13f
                      WHERE filing_id = :prev_filing_id
                        AND security_id IS NOT NULL
                        AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                        AND option_type IS NULL
                      GROUP BY match_key
                    )
                    SELECT c.security_id, c.issuer_name_raw, c.class_title_raw, c.value_usd_thousands
                    FROM curr c
                    LEFT JOIN prev p ON p.match_key = c.match_key
                    WHERE p.match_key IS NULL
                    ORDER BY c.value_usd_thousands DESC
                    LIMIT 200
                    """
                ),
                {"curr_filing_id": curr_filing_id, "prev_filing_id": prev_filing_id},
            ).mappings().all()
        ]
        exited_positions = [
            dict(x)
            for x in db.execute(
                text(
                    """
                    WITH curr AS (
                      SELECT
                        """
                    + key_expr
                    + """
                        AS match_key
                      FROM holdings_13f
                      WHERE filing_id = :curr_filing_id
                        AND security_id IS NOT NULL
                        AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                        AND option_type IS NULL
                      GROUP BY match_key
                    ),
                    prev AS (
                      SELECT
                        """
                    + key_expr
                    + """
                        AS match_key,
                        MIN(security_id) AS security_id,
                        MAX(issuer_name_raw) AS issuer_name_raw,
                        MAX(class_title_raw) AS class_title_raw,
                        SUM(COALESCE(value_usd_thousands, 0)) AS value_usd_thousands
                      FROM holdings_13f
                      WHERE filing_id = :prev_filing_id
                        AND security_id IS NOT NULL
                        AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                        AND option_type IS NULL
                      GROUP BY match_key
                    )
                    SELECT p.security_id, p.issuer_name_raw, p.class_title_raw, p.value_usd_thousands
                    FROM prev p
                    LEFT JOIN curr c ON c.match_key = p.match_key
                    WHERE c.match_key IS NULL
                    ORDER BY p.value_usd_thousands DESC
                    LIMIT 200
                    """
                ),
                {"curr_filing_id": curr_filing_id, "prev_filing_id": prev_filing_id},
            ).mappings().all()
        ]

        counts = db.execute(
            text(
                """
                WITH curr AS (
                  SELECT
                    """
                + key_expr
                + """
                    AS match_key
                  FROM holdings_13f
                  WHERE filing_id = :curr_filing_id
                    AND security_id IS NOT NULL
                    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                    AND option_type IS NULL
                  GROUP BY match_key
                ),
                prev AS (
                  SELECT
                    """
                + key_expr
                + """
                    AS match_key
                  FROM holdings_13f
                  WHERE filing_id = :prev_filing_id
                    AND security_id IS NOT NULL
                    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                    AND option_type IS NULL
                  GROUP BY match_key
                )
                SELECT
                  (SELECT COUNT(*) FROM curr c LEFT JOIN prev p ON p.match_key = c.match_key WHERE p.match_key IS NULL) AS new_count,
                  (SELECT COUNT(*) FROM prev p LEFT JOIN curr c ON c.match_key = p.match_key WHERE c.match_key IS NULL) AS exited_count
                """
            ),
            {"curr_filing_id": curr_filing_id, "prev_filing_id": prev_filing_id},
        ).mappings().first()

        m = db.execute(
            text(
                """
                WITH curr AS (
                  SELECT
                    """
                + key_expr
                + """
                    AS match_key,
                    SUM(COALESCE(value_usd_thousands, 0)) AS curr_val
                  FROM holdings_13f
                  WHERE filing_id = :curr_filing_id
                    AND security_id IS NOT NULL
                    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                    AND option_type IS NULL
                  GROUP BY match_key
                ),
                prev AS (
                  SELECT
                    """
                + key_expr
                + """
                    AS match_key,
                    SUM(COALESCE(value_usd_thousands, 0)) AS prev_val
                  FROM holdings_13f
                  WHERE filing_id = :prev_filing_id
                    AND security_id IS NOT NULL
                    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                    AND option_type IS NULL
                  GROUP BY match_key
                ),
                combined AS (
                  SELECT
                    c.match_key AS match_key,
                    COALESCE(c.curr_val, 0) AS curr_val,
                    COALESCE(p.prev_val, 0) AS prev_val
                  FROM curr c
                  LEFT JOIN prev p ON p.match_key = c.match_key
                  UNION ALL
                  SELECT
                    p.match_key AS match_key,
                    0 AS curr_val,
                    COALESCE(p.prev_val, 0) AS prev_val
                  FROM prev p
                  LEFT JOIN curr c ON c.match_key = p.match_key
                  WHERE c.match_key IS NULL
                )
                SELECT
                  (SELECT SUM(curr_val) FROM combined) AS total_curr,
                  (SELECT SUM(prev_val) FROM combined) AS total_prev,
                  (SELECT SUM(ABS(curr_val - prev_val)) FROM combined) AS abs_delta_sum,
                  (SELECT COALESCE(SUM(curr_val), 0)
                   FROM (SELECT curr_val
                         FROM curr
                         ORDER BY curr_val DESC
                         LIMIT 10)) AS top10_curr
                """
            ),
            {"curr_filing_id": curr_filing_id, "prev_filing_id": prev_filing_id},
        ).mappings().first()

        total_curr = float(m["total_curr"] or 0.0)
        total_prev = float(m["total_prev"] or 0.0)
        abs_delta_sum = float(m["abs_delta_sum"] or 0.0)
        avg_port = (total_curr + total_prev) / 2 if (total_curr + total_prev) > 0 else 0
        turnover = (abs_delta_sum / 2) / avg_port if avg_port > 0 else 0
        top10_curr = float(m["top10_curr"] or 0.0)
        deltas = db.execute(
            text(
                """
                WITH curr AS (
                  SELECT
                    """
                + key_expr
                + """
                    AS match_key,
                    MIN(security_id) AS security_id,
                    MAX(issuer_name_raw) AS issuer_name_raw,
                    MAX(class_title_raw) AS class_title_raw,
                    SUM(COALESCE(value_usd_thousands, 0)) AS curr_val
                  FROM holdings_13f
                  WHERE filing_id = :curr_filing_id
                    AND security_id IS NOT NULL
                    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                    AND option_type IS NULL
                  GROUP BY match_key
                ),
                prev AS (
                  SELECT
                    """
                + key_expr
                + """
                    AS match_key,
                    MIN(security_id) AS security_id,
                    MAX(issuer_name_raw) AS issuer_name_raw,
                    MAX(class_title_raw) AS class_title_raw,
                    SUM(COALESCE(value_usd_thousands, 0)) AS prev_val
                  FROM holdings_13f
                  WHERE filing_id = :prev_filing_id
                    AND security_id IS NOT NULL
                    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                    AND option_type IS NULL
                  GROUP BY match_key
                ),
                combined AS (
                  SELECT
                    COALESCE(c.security_id, p.security_id) AS security_id,
                    COALESCE(c.issuer_name_raw, p.issuer_name_raw) AS issuer_name_raw,
                    COALESCE(c.class_title_raw, p.class_title_raw) AS class_title_raw,
                    c.curr_val - COALESCE(p.prev_val, 0) AS delta_val
                  FROM curr c
                  LEFT JOIN prev p ON p.match_key = c.match_key
                  UNION ALL
                  SELECT
                    p.security_id,
                    p.issuer_name_raw,
                    p.class_title_raw,
                    -p.prev_val AS delta_val
                  FROM prev p
                  LEFT JOIN curr c ON c.match_key = p.match_key
                  WHERE c.match_key IS NULL
                )
                SELECT security_id, issuer_name_raw, class_title_raw, delta_val
                FROM combined
                """
            ),
            {"curr_filing_id": curr_filing_id, "prev_filing_id": prev_filing_id},
        ).mappings().all()
        top_buys = sorted(
            [dict(x) for x in deltas if float(x["delta_val"] or 0.0) > 0],
            key=lambda x: float(x["delta_val"]),
            reverse=True,
        )[:10]
        top_sells = sorted(
            [dict(x) for x in deltas if float(x["delta_val"] or 0.0) < 0],
            key=lambda x: float(x["delta_val"]),
        )[:10]

        for row_dict in new_positions:
            raw_value = float(row_dict["value_usd_thousands"] or 0.0)
            row_dict["value_usd_thousands"] = _raw_value_to_usd_thousands(
                raw_value=raw_value,
                value_to_usd_multiplier=value_to_usd_multiplier,
            )
        for row_dict in exited_positions:
            raw_value = float(row_dict["value_usd_thousands"] or 0.0)
            row_dict["value_usd_thousands"] = _raw_value_to_usd_thousands(
                raw_value=raw_value,
                value_to_usd_multiplier=value_to_usd_multiplier,
            )
        for row_dict in top_buys:
            raw_delta = float(row_dict["delta_val"] or 0.0)
            row_dict["delta_val"] = _raw_value_to_usd_thousands(
                raw_value=raw_delta,
                value_to_usd_multiplier=value_to_usd_multiplier,
            )
        for row_dict in top_sells:
            raw_delta = float(row_dict["delta_val"] or 0.0)
            row_dict["delta_val"] = _raw_value_to_usd_thousands(
                raw_value=raw_delta,
                value_to_usd_multiplier=value_to_usd_multiplier,
            )

        metrics = {
            "turnover_ratio": turnover,
            "top10_concentration_pct": (top10_curr / total_curr) if total_curr > 0 else 0,
            "new_positions_count": int((counts or {}).get("new_count", 0) or 0),
            "exited_positions_count": int((counts or {}).get("exited_count", 0) or 0),
            "total_value_current": total_curr * value_to_usd_multiplier,
            "total_value_previous": total_prev * value_to_usd_multiplier,
        }

    return {
        "manager": dict(row),
        "latest_quarter": latest_date,
        "top_positions": [dict(x) for x in top_positions],
        "new_positions": new_positions,
        "exited_positions": exited_positions,
        "top_buys": top_buys,
        "top_sells": top_sells,
        "metrics": metrics,
    }


@router.get("/screeners/accumulation")
def screener_accumulation(
    curr_q: str = Query(..., description="Current quarter date (YYYY-MM-DD)."),
    prev_q: str = Query(..., description="Previous quarter date (YYYY-MM-DD)."),
    limit_n: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        text(
            """
            WITH curr AS (
              SELECT h.security_id, h.manager_id, SUM(COALESCE(h.shares, 0)) AS shares
              FROM holdings_13f h
              WHERE h.report_date = :curr_q
                AND h.security_id IS NOT NULL
                AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                AND h.option_type IS NULL
              GROUP BY h.security_id, h.manager_id
            ),
            prev AS (
              SELECT h.security_id, h.manager_id, SUM(COALESCE(h.shares, 0)) AS shares
              FROM holdings_13f h
              WHERE h.report_date = :prev_q
                AND h.security_id IS NOT NULL
                AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                AND h.option_type IS NULL
              GROUP BY h.security_id, h.manager_id
            ),
            joined AS (
              SELECT
                COALESCE(c.security_id, p.security_id) AS security_id,
                COALESCE(c.manager_id, p.manager_id) AS manager_id,
                COALESCE(c.shares, 0) AS curr_shares,
                COALESCE(p.shares, 0) AS prev_shares
              FROM curr c
              LEFT JOIN prev p
                ON p.security_id = c.security_id
               AND p.manager_id = c.manager_id
              UNION ALL
              SELECT
                p.security_id,
                p.manager_id,
                0 AS curr_shares,
                p.shares AS prev_shares
              FROM prev p
              LEFT JOIN curr c
                ON c.security_id = p.security_id
               AND c.manager_id = p.manager_id
              WHERE c.manager_id IS NULL
            ),
            agg AS (
              SELECT
                security_id,
                SUM(curr_shares - prev_shares) AS net_shares,
                SUM(CASE WHEN curr_shares > 0 AND prev_shares = 0 THEN 1 ELSE 0 END) AS holders_added,
                SUM(CASE WHEN curr_shares = 0 AND prev_shares > 0 THEN 1 ELSE 0 END) AS holders_exited
              FROM joined
              GROUP BY security_id
            )
            SELECT
              a.security_id,
              (a.holders_added - a.holders_exited) AS net_holder_count,
              a.net_shares,
              s.security_name,
              s.instrument_type,
              (
                SELECT si.id_value
                FROM security_identifiers si
                WHERE si.security_id = a.security_id
                  AND si.id_type = 'TICKER'
                  AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                ORDER BY si.valid_from DESC
                LIMIT 1
              ) AS ticker
            FROM agg a
            LEFT JOIN securities s ON s.security_id = a.security_id
            ORDER BY net_holder_count DESC, net_shares DESC
            LIMIT :limit_n
            """
        ),
        {"curr_q": curr_q, "prev_q": prev_q, "limit_n": limit_n},
    ).mappings().all()
    return {"rows": [dict(x) for x in rows], "curr_q": curr_q, "prev_q": prev_q}


@router.get("/screeners/new-5pct-holders")
def screener_new_5pct_holders(
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)."),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)."),
    limit_n: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        text(
            """
            SELECT
              b.report_date,
              b.manager_id,
              m.manager_name,
              b.security_id,
              s.security_name,
              b.percent_beneficial_owned,
              b.shares_beneficial_owned,
              f.accession_no,
              f.form_type
            FROM beneficial_ownership_events b
            LEFT JOIN managers m ON m.manager_id = b.manager_id
            LEFT JOIN securities s ON s.security_id = b.security_id
            JOIN filings f ON f.filing_id = b.filing_id
            WHERE b.event_type = 'NEW_5PCT'
              AND b.report_date BETWEEN :start_date AND :end_date
              AND (
                b.security_id IS NULL
                OR UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
              )
            ORDER BY b.report_date DESC
            LIMIT :limit_n
            """
        ),
        {"start_date": start_date, "end_date": end_date, "limit_n": limit_n},
    ).mappings().all()
    return {"rows": [dict(x) for x in rows], "start_date": start_date, "end_date": end_date}


@router.get("/screeners/accumulation-history")
def screener_accumulation_history(
    limit_n: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    quarter_rows = db.execute(
        text(
            """
            SELECT DISTINCT report_date
            FROM holdings_13f h
            WHERE h.security_id IS NOT NULL
              AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
              AND h.option_type IS NULL
            ORDER BY report_date DESC
            LIMIT 5
            """
        )
    ).all()
    quarters_desc = [x[0] for x in quarter_rows]
    if len(quarters_desc) < 2:
        return {"quarters": quarters_desc, "rows": []}
    quarters = list(reversed(quarters_desc))

    rows = db.execute(
        text(
            """
            WITH manager_q AS (
              SELECT h.security_id, h.manager_id, h.report_date, SUM(COALESCE(h.shares, 0)) AS shares
              FROM holdings_13f h
              WHERE h.security_id IS NOT NULL
                AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                AND h.option_type IS NULL
                AND h.report_date IN (
                  SELECT report_date
                  FROM (
                    SELECT DISTINCT h2.report_date
                    FROM holdings_13f h2
                    WHERE h2.security_id IS NOT NULL
                      AND h2.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                      AND h2.option_type IS NULL
                    ORDER BY report_date DESC
                    LIMIT 5
                  )
                )
              GROUP BY h.security_id, h.manager_id, h.report_date
            ),
            pairs AS (
              SELECT
                c.security_id,
                c.manager_id,
                c.report_date AS curr_q,
                COALESCE(c.shares, 0) - COALESCE(p.shares, 0) AS delta_shares,
                CASE WHEN COALESCE(c.shares, 0) > 0 AND COALESCE(p.shares, 0) = 0 THEN 1 ELSE 0 END AS added,
                CASE WHEN COALESCE(c.shares, 0) = 0 AND COALESCE(p.shares, 0) > 0 THEN 1 ELSE 0 END AS exited
              FROM manager_q c
              LEFT JOIN manager_q p
                ON p.security_id = c.security_id
               AND p.manager_id = c.manager_id
               AND p.report_date = (
                 SELECT MAX(q.report_date) FROM manager_q q
                 WHERE q.security_id = c.security_id AND q.manager_id = c.manager_id AND q.report_date < c.report_date
               )
            ),
            agg AS (
              SELECT
                security_id,
                curr_q AS report_date,
                SUM(delta_shares) AS net_shares,
                SUM(added) - SUM(exited) AS net_holder_count
              FROM pairs
              GROUP BY security_id, curr_q
            ),
            latest AS (
              SELECT security_id, report_date, net_shares, net_holder_count
              FROM agg
              WHERE report_date = (SELECT MAX(report_date) FROM agg)
              ORDER BY net_holder_count DESC, net_shares DESC
              LIMIT :limit_n
            )
            SELECT
              a.security_id,
              a.report_date,
              a.net_shares,
              a.net_holder_count,
              s.security_name,
              (
                SELECT si.id_value
                FROM security_identifiers si
                WHERE si.security_id = a.security_id
                  AND si.id_type = 'TICKER'
                  AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                ORDER BY si.valid_from DESC
                LIMIT 1
              ) AS ticker
            FROM agg a
            JOIN latest l ON l.security_id = a.security_id
            LEFT JOIN securities s ON s.security_id = a.security_id
            ORDER BY a.security_id, a.report_date
            """
        ),
        {"limit_n": limit_n},
    ).mappings().all()

    per_security: dict[int, dict] = {}
    for row in rows:
        sid = int(row["security_id"])
        entry = per_security.setdefault(
            sid,
            {
                "security_id": sid,
                "security_name": row["security_name"],
                "ticker": row["ticker"],
                "series": [],
            },
        )
        entry["series"].append(
            {
                "report_date": row["report_date"],
                "net_shares": float(row["net_shares"] or 0.0),
                "net_holder_count": int(row["net_holder_count"] or 0),
            }
        )
    return {"quarters": quarters, "rows": list(per_security.values())}
