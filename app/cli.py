from __future__ import annotations

import argparse

from app.config import get_settings
from app.db import ensure_schema_and_seed, get_engine


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Institutional flow tracker CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create/update schema and seed API budget defaults.")

    ingest = sub.add_parser("ingest-13f", help="Ingest recent 13F filings for a manager CIK.")
    ingest.add_argument("--cik", required=True, help="CIK, with or without leading zeros.")
    ingest.add_argument("--limit", type=int, default=20, help="Max recent filing rows to scan.")

    ingest_13dg = sub.add_parser("ingest-13dg", help="Ingest recent 13D/G filings for a manager CIK.")
    ingest_13dg.add_argument("--cik", required=True, help="CIK, with or without leading zeros.")
    ingest_13dg.add_argument("--limit", type=int, default=20, help="Max recent filing rows to scan.")

    sync_tickers = sub.add_parser("sync-tickers", help="Enrich security master with ticker identifiers.")
    sync_tickers.add_argument("--limit", type=int, default=None, help="Optional max securities to scan.")
    sync_tickers.add_argument("--recent-quarters", type=int, default=4)
    sync_tickers.add_argument("--min-holders", type=int, default=3)
    sync_tickers.add_argument("--min-total-value-usd", type=float, default=250_000_000.0)
    sync_tickers.add_argument("--universe-only", action="store_true", default=False)

    resolve = sub.add_parser("resolve-mappings", help="Resolve unmapped holdings/events to security_id.")
    resolve.add_argument("--limit", type=int, default=None, help="Optional max rows per table.")

    refresh_universe = sub.add_parser("refresh-universe", help="Refresh manager universe from latest holdings.")
    refresh_universe.add_argument("--top-n", type=int, default=300)

    ingest_universe = sub.add_parser("ingest-universe", help="Ingest filings for active manager universe.")
    ingest_universe.add_argument("--limit", type=int, default=20, help="Per-manager recent filing rows to scan.")
    ingest_universe.add_argument("--include-13dg", action="store_true", default=False)

    pipeline = sub.add_parser("pipeline-run", help="Run full scoped pipeline.")
    pipeline.add_argument("--top-n", type=int, default=300)
    pipeline.add_argument("--ingest-limit", type=int, default=20)
    pipeline.add_argument("--include-13dg", action="store_true", default=False)
    pipeline.add_argument("--recent-quarters", type=int, default=4)
    pipeline.add_argument("--min-holders", type=int, default=3)
    pipeline.add_argument("--min-total-value-usd", type=float, default=250_000_000.0)

    sub.add_parser("refresh-aggregates", help="Rebuild aggregate tables from mapped holdings.")
    return parser


def _init_db() -> None:
    engine = get_engine()
    ensure_schema_and_seed(engine)
    print("Database initialized and API budgets seeded.")


def _ingest_13f(cik: str, limit: int) -> None:
    from sqlalchemy.orm import Session

    from app.clients.rate_limit import ProviderRateLimiter
    from app.clients.sec_client import SecClient, build_sec_http_session
    from app.ingest.sec_13f import Sec13FIngestionService

    settings = get_settings()
    engine = get_engine()
    ensure_schema_and_seed(engine)

    limiter = ProviderRateLimiter()
    limiter.register(provider="SEC", rate_per_sec=float(settings.sec_burst_per_second))
    session = build_sec_http_session()

    with Session(bind=engine) as db:
        client = SecClient(session=session, limiter=limiter, db=db)
        service = Sec13FIngestionService(db=db, sec_client=client)
        result = service.ingest_for_cik(cik=cik, limit=limit)
        print(f"filings_upserted={result.filings_upserted} holdings_inserted={result.holdings_inserted}")


def _ingest_13dg(cik: str, limit: int) -> None:
    from sqlalchemy.orm import Session

    from app.clients.rate_limit import ProviderRateLimiter
    from app.clients.sec_client import SecClient, build_sec_http_session
    from app.ingest.sec_13dg import Sec13DGIngestionService

    settings = get_settings()
    engine = get_engine()
    ensure_schema_and_seed(engine)

    limiter = ProviderRateLimiter()
    limiter.register(provider="SEC", rate_per_sec=float(settings.sec_burst_per_second))
    session = build_sec_http_session()

    with Session(bind=engine) as db:
        client = SecClient(session=session, limiter=limiter, db=db)
        service = Sec13DGIngestionService(db=db, sec_client=client)
        result = service.ingest_for_cik(cik=cik, limit=limit)
        print(f"filings_upserted={result.filings_upserted} events_inserted={result.events_inserted}")


def _resolve_mappings(limit: int | None) -> None:
    from sqlalchemy.orm import Session

    from app.resolution.security_resolver import SecurityResolverService

    engine = get_engine()
    ensure_schema_and_seed(engine)
    with Session(bind=engine) as db:
        service = SecurityResolverService(db=db)
        summary = service.resolve_all(limit=limit)
        print(
            f"bootstrap_created={summary.bootstrap_created} "
            f"holdings_mapped={summary.holdings_mapped} "
            f"bo_events_mapped={summary.bo_events_mapped}"
        )


def _sync_tickers(
    limit: int | None,
    recent_quarters: int,
    min_holders: int,
    min_total_value_usd: float,
    universe_only: bool,
) -> None:
    from sqlalchemy.orm import Session

    from app.clients.rate_limit import ProviderRateLimiter
    from app.clients.sec_client import SecClient, build_sec_http_session
    from app.resolution.ticker_enrichment import TickerEnrichmentService

    settings = get_settings()
    engine = get_engine()
    ensure_schema_and_seed(engine)

    limiter = ProviderRateLimiter()
    limiter.register(provider="SEC", rate_per_sec=float(settings.sec_burst_per_second))
    session = build_sec_http_session()

    with Session(bind=engine) as db:
        client = SecClient(session=session, limiter=limiter, db=db)
        service = TickerEnrichmentService(db=db, sec_client=client)
        summary = service.sync_from_sec_company_tickers(
            limit=limit,
            recent_quarters=recent_quarters,
            min_holders=min_holders,
            min_total_value_usd=min_total_value_usd,
            universe_only=universe_only,
        )
        print(f"scanned={summary.scanned} matched={summary.matched} inserted={summary.inserted}")


def _refresh_universe(top_n: int) -> None:
    from sqlalchemy.orm import Session

    from app.pipeline.universe import ManagerUniverseService

    engine = get_engine()
    ensure_schema_and_seed(engine)
    with Session(bind=engine) as db:
        service = ManagerUniverseService(db=db)
        summary = service.refresh_top_n(top_n=top_n)
        print(f"as_of_report_date={summary.as_of_report_date} selected={summary.selected}")


def _ingest_universe(limit: int, include_13dg: bool) -> None:
    from sqlalchemy.orm import Session

    from app.clients.rate_limit import ProviderRateLimiter
    from app.clients.sec_client import SecClient, build_sec_http_session
    from app.ingest.sec_13dg import Sec13DGIngestionService
    from app.ingest.sec_13f import Sec13FIngestionService
    from app.pipeline.universe import ManagerUniverseService

    settings = get_settings()
    engine = get_engine()
    ensure_schema_and_seed(engine)

    limiter = ProviderRateLimiter()
    limiter.register(provider="SEC", rate_per_sec=float(settings.sec_burst_per_second))
    session = build_sec_http_session()

    with Session(bind=engine) as db:
        universe = ManagerUniverseService(db=db)
        ciks = universe.get_active_ciks()
        client = SecClient(session=session, limiter=limiter, db=db)
        svc_13f = Sec13FIngestionService(db=db, sec_client=client)
        svc_13dg = Sec13DGIngestionService(db=db, sec_client=client)

        total_filings = 0
        total_holdings = 0
        total_events = 0
        for cik in ciks:
            r13f = svc_13f.ingest_for_cik(cik=cik, limit=limit)
            total_filings += r13f.filings_upserted
            total_holdings += r13f.holdings_inserted
            if include_13dg:
                r13dg = svc_13dg.ingest_for_cik(cik=cik, limit=limit)
                total_filings += r13dg.filings_upserted
                total_events += r13dg.events_inserted

        print(
            f"managers={len(ciks)} filings_upserted={total_filings} "
            f"holdings_inserted={total_holdings} events_inserted={total_events}"
        )


def _pipeline_run(
    top_n: int,
    ingest_limit: int,
    include_13dg: bool,
    recent_quarters: int,
    min_holders: int,
    min_total_value_usd: float,
) -> None:
    _refresh_universe(top_n=top_n)
    _ingest_universe(limit=ingest_limit, include_13dg=include_13dg)
    _resolve_mappings(limit=None)
    _sync_tickers(
        limit=None,
        recent_quarters=recent_quarters,
        min_holders=min_holders,
        min_total_value_usd=min_total_value_usd,
        universe_only=True,
    )
    _refresh_aggregates()


def _refresh_aggregates() -> None:
    from sqlalchemy.orm import Session

    from app.analytics.aggregates import AggregateRefreshService

    engine = get_engine()
    ensure_schema_and_seed(engine)
    with Session(bind=engine) as db:
        service = AggregateRefreshService(db=db)
        summary = service.refresh_all()
        print(f"security_rows={summary.security_rows} manager_rows={summary.manager_rows}")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "init-db":
        _init_db()
    elif args.command == "ingest-13f":
        _ingest_13f(cik=args.cik, limit=args.limit)
    elif args.command == "ingest-13dg":
        _ingest_13dg(cik=args.cik, limit=args.limit)
    elif args.command == "sync-tickers":
        _sync_tickers(
            limit=args.limit,
            recent_quarters=args.recent_quarters,
            min_holders=args.min_holders,
            min_total_value_usd=args.min_total_value_usd,
            universe_only=args.universe_only,
        )
    elif args.command == "resolve-mappings":
        _resolve_mappings(limit=args.limit)
    elif args.command == "refresh-universe":
        _refresh_universe(top_n=args.top_n)
    elif args.command == "ingest-universe":
        _ingest_universe(limit=args.limit, include_13dg=args.include_13dg)
    elif args.command == "pipeline-run":
        _pipeline_run(
            top_n=args.top_n,
            ingest_limit=args.ingest_limit,
            include_13dg=args.include_13dg,
            recent_quarters=args.recent_quarters,
            min_holders=args.min_holders,
            min_total_value_usd=args.min_total_value_usd,
        )
    elif args.command == "refresh-aggregates":
        _refresh_aggregates()
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
