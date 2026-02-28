from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import date
from datetime import datetime
from pathlib import Path

from sqlalchemy import bindparam, text

from app.config import get_settings
from app.db import ensure_schema_and_seed, get_engine


def _build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Institutional flow tracker CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create/update schema and seed API budget defaults.")

    ingest = sub.add_parser("ingest-13f", help="Ingest recent 13F filings for a manager CIK.")
    ingest.add_argument("--cik", required=True, help="CIK, with or without leading zeros.")
    ingest.add_argument("--limit", type=int, default=20, help="Max matching 13F forms to ingest.")

    ingest_13dg = sub.add_parser("ingest-13dg", help="Ingest recent 13D/G filings for a manager CIK.")
    ingest_13dg.add_argument("--cik", required=True, help="CIK, with or without leading zeros.")
    ingest_13dg.add_argument("--limit", type=int, default=20, help="Max matching 13D/G forms to ingest.")

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
    ingest_universe.add_argument("--limit", type=int, default=20, help="Per-manager max matching forms to ingest.")
    ingest_universe.add_argument("--include-13dg", action="store_true", default=False)

    pipeline = sub.add_parser("pipeline-run", help="Run full scoped pipeline.")
    pipeline.add_argument("--top-n", type=int, default=300)
    pipeline.add_argument("--ingest-limit", type=int, default=20)
    pipeline.add_argument("--include-13dg", action="store_true", default=False)
    pipeline.add_argument("--recent-quarters", type=int, default=4)
    pipeline.add_argument("--min-holders", type=int, default=3)
    pipeline.add_argument("--min-total-value-usd", type=float, default=250_000_000.0)

    incr = sub.add_parser("update-incremental", help="Run efficient incremental update for active manager universe.")
    incr.add_argument("--top-n", type=int, default=300)
    incr.add_argument("--ingest-limit", type=int, default=20, help="Per-manager max matching forms to ingest.")
    incr.add_argument("--include-13dg", action="store_true", default=False)
    incr.add_argument("--resolve-quarters", type=int, default=6, help="Recent report_date batches to resolve.")
    incr.add_argument("--recent-quarters", type=int, default=4)
    incr.add_argument("--min-holders", type=int, default=3)
    incr.add_argument("--min-total-value-usd", type=float, default=250_000_000.0)
    incr.add_argument("--skip-sync-tickers", action="store_true", default=False)
    incr.add_argument("--log-file", default="", help="Optional structured log output path.")
    incr.add_argument("--alert-min-13f-pct", type=float, default=95.0)
    incr.add_argument("--alert-min-bo-pct", type=float, default=95.0)

    seed = sub.add_parser("ingest-cik-list", help="Bootstrap by ingesting a CIK list file.")
    seed.add_argument("--file", required=True, help="Path to CIK list file (.txt or .csv).")
    seed.add_argument("--limit", type=int, default=20, help="Per-manager max matching forms to ingest.")
    seed.add_argument("--include-13dg", action="store_true", default=False)

    discover = sub.add_parser("discover-13f-ciks", help="Discover 13F filer CIKs from SEC master index.")
    discover.add_argument("--quarters", type=int, default=4, help="How many recent quarters to scan.")
    discover.add_argument(
        "--max-ciks",
        type=int,
        default=1000,
        help="Maximum CIKs to write. Use 0 for all discovered CIKs. Tie-aware selection includes all CIKs at cutoff score.",
    )
    discover.add_argument(
        "--out",
        default="seeds/ciks.discovered.txt",
        help="Output file path for discovered CIKs.",
    )

    seed_top_aum = sub.add_parser(
        "seed-top-aum",
        help="Seed missing managers from SEC top-N by 13F table value (AUM proxy).",
    )
    seed_top_aum.add_argument(
        "--top-n",
        type=int,
        default=int(settings.aum_top_n_default),
        help="Target top-N managers by SEC 13F table value.",
    )
    seed_top_aum.add_argument("--limit", type=int, default=40, help="Per-manager max matching forms to ingest for missing CIKs.")
    seed_top_aum.add_argument("--include-13dg", action="store_true", default=False)
    seed_top_aum.add_argument(
        "--dataset-url",
        default="",
        help="Optional SEC 13F ZIP URL override. Defaults to latest available dataset.",
    )
    seed_top_aum.add_argument(
        "--out",
        default="seeds/ciks.top_aum.txt",
        help="Output file path for selected top-N CIK list.",
    )
    seed_top_aum.add_argument(
        "--no-prune",
        action="store_true",
        default=False,
        help="Skip pruning existing manager data below the top-N AUM threshold.",
    )

    resume = sub.add_parser("resume-post-ingest", help="Resume post-ingest steps in bounded batches.")
    resume.add_argument("--batch-size", type=int, default=200_000, help="Rows per resolve batch.")
    resume.add_argument("--max-batches", type=int, default=100, help="Safety cap on resolve batches.")
    resume.add_argument("--recent-quarters", type=int, default=4)
    resume.add_argument("--min-holders", type=int, default=3)
    resume.add_argument("--min-total-value-usd", type=float, default=250_000_000.0)
    resume.add_argument("--top-n", type=int, default=300)
    resume.add_argument("--log-file", default="", help="Optional log file path for structured progress logs.")
    resume.add_argument("--skip-sync-tickers", action="store_true", default=False)
    resume.add_argument("--alert-min-13f-pct", type=float, default=95.0)
    resume.add_argument("--alert-min-bo-pct", type=float, default=95.0)

    enrich = sub.add_parser("enrich-cusips", help="Enrich CUSIP -> ticker crosswalk for in-scope holdings.")
    enrich.add_argument("--recent-quarters", type=int, default=4)
    enrich.add_argument("--top-n", type=int, default=300)
    enrich.add_argument("--min-holders", type=int, default=3)
    enrich.add_argument("--min-total-value-usd", type=float, default=250_000_000.0)
    enrich.add_argument("--provider", choices=["openfigi", "noop"], default="noop")
    enrich.add_argument("--limit-cusips", type=int, default=0, help="Optional cap on distinct CUSIPs.")
    enrich.add_argument("--log-file", default="", help="Optional structured log output path.")

    validate = sub.add_parser(
        "validate-live",
        help="Validate manager/security analytics against raw holdings and optional third-party snapshots.",
    )
    validate.add_argument(
        "--manager-key",
        action="append",
        default=[],
        help="Manager key to validate (manager_id or cik). Repeatable.",
    )
    validate.add_argument(
        "--ticker",
        action="append",
        default=[],
        help="Ticker to validate. Repeatable.",
    )
    validate.add_argument("--sample-managers", type=int, default=10, help="Sample additional managers from universe.")
    validate.add_argument("--sample-tickers", type=int, default=20, help="Sample additional tickers from holdings.")
    validate.add_argument(
        "--tolerance-pct",
        type=float,
        default=0.25,
        help="Relative tolerance percent for numeric comparisons.",
    )
    validate.add_argument(
        "--external-provider",
        choices=["none", "nasdaq", "polygon", "alphavantage", "auto"],
        default="none",
        help="Optional external snapshot source.",
    )
    validate.add_argument("--json-out", default="", help="Optional path to write JSON report.")
    validate.add_argument(
        "--fail-on-error",
        action="store_true",
        default=False,
        help="Exit non-zero when internal validation errors are found.",
    )

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


def _parse_cik_file(path: str) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"CIK file not found: {path}")

    if file_path.suffix.lower() == ".csv":
        ciks: list[str] = []
        with file_path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            cols = [c.lower().strip() for c in (reader.fieldnames or [])]
            cik_col = None
            for candidate in ["cik", "manager_cik"]:
                if candidate in cols:
                    cik_col = candidate
                    break
            if cik_col is None:
                raise ValueError("CSV must include a 'cik' column.")

            for row in reader:
                val = row.get(cik_col) if row else None
                if not val:
                    continue
                digits = "".join(ch for ch in str(val) if ch.isdigit())
                if digits:
                    ciks.append(digits.zfill(10))
        return sorted(set(ciks))

    # Plain text list: one CIK per line.
    ciks = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits:
            ciks.append(digits.zfill(10))
    return sorted(set(ciks))


def _ingest_cik_list(file_path: str, limit: int, include_13dg: bool) -> None:
    from sqlalchemy.orm import Session

    from app.clients.rate_limit import ProviderRateLimiter
    from app.clients.sec_client import SecClient, build_sec_http_session
    from app.ingest.sec_13dg import Sec13DGIngestionService
    from app.ingest.sec_13f import Sec13FIngestionService

    ciks = _parse_cik_file(file_path)
    settings = get_settings()
    engine = get_engine()
    ensure_schema_and_seed(engine)

    limiter = ProviderRateLimiter()
    limiter.register(provider="SEC", rate_per_sec=float(settings.sec_burst_per_second))
    session = build_sec_http_session()

    with Session(bind=engine) as db:
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
            f"input_managers={len(ciks)} filings_upserted={total_filings} "
            f"holdings_inserted={total_holdings} events_inserted={total_events}"
        )


def _recent_quarters(n: int) -> list[tuple[int, int]]:
    today = date.today()
    q = (today.month - 1) // 3 + 1
    y = today.year
    result: list[tuple[int, int]] = []
    for _ in range(max(1, n)):
        result.append((y, q))
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    return result


def _discover_13f_ciks(quarters: int, max_ciks: int, out_path: str) -> None:
    from collections import defaultdict

    from sqlalchemy.orm import Session

    from app.clients.rate_limit import ProviderRateLimiter
    from app.clients.sec_client import SecClient, build_sec_http_session

    settings = get_settings()
    engine = get_engine()
    ensure_schema_and_seed(engine)

    limiter = ProviderRateLimiter()
    limiter.register(provider="SEC", rate_per_sec=float(settings.sec_burst_per_second))
    session = build_sec_http_session()
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    scores: dict[str, int] = defaultdict(int)
    scanned_indexes = 0

    with Session(bind=engine) as db:
        client = SecClient(session=session, limiter=limiter, db=db)
        for year, quarter in _recent_quarters(quarters):
            url = f"{settings.sec_archives_base_url}/edgar/full-index/{year}/QTR{quarter}/master.idx"
            try:
                text_data = client.download_text(url)
            except Exception:
                continue
            scanned_indexes += 1
            for line in text_data.splitlines():
                if "|" not in line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 5:
                    continue
                cik, _company, form_type, _filed_date, _filename = parts[:5]
                if form_type not in {"13F-HR", "13F-HR/A"}:
                    continue
                digits = "".join(ch for ch in cik if ch.isdigit())
                if not digits:
                    continue
                scores[digits.zfill(10)] += 1

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if max_ciks <= 0 or max_ciks >= len(ranked):
        selected = [cik for cik, _score in ranked]
        cutoff_score = ranked[-1][1] if ranked else 0
    else:
        cutoff_score = ranked[max_ciks - 1][1]
        selected = [cik for cik, score in ranked if score >= cutoff_score]
    out_file.write_text("\n".join(selected) + ("\n" if selected else ""), encoding="utf-8")
    print(
        f"quarters_scanned={scanned_indexes} discovered={len(scores)} "
        f"selected={len(selected)} requested_max={max_ciks} cutoff_score={cutoff_score} out={out_file}"
    )


def _prune_below_aum(top_n: int) -> None:
    from sqlalchemy.orm import Session

    engine = get_engine()
    ensure_schema_and_seed(engine)
    with Session(bind=engine) as db:
        latest = db.execute(
            text(
                """
                SELECT MAX(report_date)
                FROM holdings_13f
                WHERE option_type IS NULL
                  AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                """
            )
        ).scalar()
        if latest is None:
            print("prune_skipped reason=no_mapped_holdings")
            return

        keep_rows = db.execute(
            text(
                """
                WITH ranked AS (
                  SELECT
                    manager_id,
                    ROW_NUMBER() OVER (ORDER BY SUM(COALESCE(value_usd_thousands, 0)) DESC, manager_id ASC) AS rnk
                  FROM holdings_13f
                  WHERE report_date = :latest
                    AND option_type IS NULL
                    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                  GROUP BY manager_id
                )
                SELECT manager_id
                FROM ranked
                WHERE rnk <= :top_n
                """
            ),
            {"latest": latest, "top_n": top_n},
        ).all()
        keep_ids = [int(x[0]) for x in keep_rows if x and x[0] is not None]
        if not keep_ids:
            print("prune_skipped reason=empty_keep_set")
            return

        before = {
            "managers": int(db.execute(text("SELECT COUNT(*) FROM managers")).scalar() or 0),
            "filings": int(db.execute(text("SELECT COUNT(*) FROM filings")).scalar() or 0),
            "holdings": int(db.execute(text("SELECT COUNT(*) FROM holdings_13f")).scalar() or 0),
            "events": int(db.execute(text("SELECT COUNT(*) FROM beneficial_ownership_events")).scalar() or 0),
            "manager_universe": int(db.execute(text("SELECT COUNT(*) FROM manager_universe")).scalar() or 0),
            "agg_manager_quarter": int(db.execute(text("SELECT COUNT(*) FROM agg_manager_quarter")).scalar() or 0),
        }

        db.execute(
            text("DELETE FROM manager_universe WHERE manager_id NOT IN :keep_ids").bindparams(
                bindparam("keep_ids", expanding=True)
            ),
            {"keep_ids": keep_ids},
        )
        db.execute(
            text("DELETE FROM agg_manager_quarter WHERE manager_id NOT IN :keep_ids").bindparams(
                bindparam("keep_ids", expanding=True)
            ),
            {"keep_ids": keep_ids},
        )
        db.execute(
            text("DELETE FROM beneficial_ownership_events WHERE manager_id IS NOT NULL AND manager_id NOT IN :keep_ids").bindparams(
                bindparam("keep_ids", expanding=True)
            ),
            {"keep_ids": keep_ids},
        )
        db.execute(
            text("DELETE FROM holdings_13f WHERE manager_id NOT IN :keep_ids").bindparams(
                bindparam("keep_ids", expanding=True)
            ),
            {"keep_ids": keep_ids},
        )
        db.execute(
            text("DELETE FROM filings WHERE manager_id IS NOT NULL AND manager_id NOT IN :keep_ids").bindparams(
                bindparam("keep_ids", expanding=True)
            ),
            {"keep_ids": keep_ids},
        )
        db.execute(
            text("DELETE FROM managers WHERE manager_id NOT IN :keep_ids").bindparams(bindparam("keep_ids", expanding=True)),
            {"keep_ids": keep_ids},
        )
        db.commit()

        after = {
            "managers": int(db.execute(text("SELECT COUNT(*) FROM managers")).scalar() or 0),
            "filings": int(db.execute(text("SELECT COUNT(*) FROM filings")).scalar() or 0),
            "holdings": int(db.execute(text("SELECT COUNT(*) FROM holdings_13f")).scalar() or 0),
            "events": int(db.execute(text("SELECT COUNT(*) FROM beneficial_ownership_events")).scalar() or 0),
            "manager_universe": int(db.execute(text("SELECT COUNT(*) FROM manager_universe")).scalar() or 0),
            "agg_manager_quarter": int(db.execute(text("SELECT COUNT(*) FROM agg_manager_quarter")).scalar() or 0),
        }

    print(
        "prune_complete "
        f"top_n={top_n} latest={latest} keep={len(keep_ids)} "
        f"managers_removed={before['managers'] - after['managers']} "
        f"filings_removed={before['filings'] - after['filings']} "
        f"holdings_removed={before['holdings'] - after['holdings']} "
        f"events_removed={before['events'] - after['events']}"
    )


def _seed_top_aum(
    top_n: int,
    limit: int,
    include_13dg: bool,
    dataset_url: str,
    out_path: str,
    prune_below_threshold: bool,
) -> None:
    from sqlalchemy.orm import Session

    from app.clients.rate_limit import ProviderRateLimiter
    from app.clients.sec_client import SecClient, build_sec_http_session
    from app.ingest.sec_13dg import Sec13DGIngestionService
    from app.ingest.sec_13f import Sec13FIngestionService
    from app.pipeline.aum_seed import fetch_top_managers_by_13f_value

    settings = get_settings()
    engine = get_engine()
    ensure_schema_and_seed(engine)

    limiter = ProviderRateLimiter()
    limiter.register(provider="SEC", rate_per_sec=float(settings.sec_burst_per_second))
    session = build_sec_http_session()

    selected_dataset_url, records = fetch_top_managers_by_13f_value(
        session=session,
        limiter=limiter,
        top_n=top_n,
        dataset_url=dataset_url,
    )
    target_ciks = [r.cik for r in records]
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n".join(target_ciks) + ("\n" if target_ciks else ""), encoding="utf-8")

    with Session(bind=engine) as db:
        existing_rows = db.execute(
            text("SELECT cik FROM managers WHERE cik IS NOT NULL AND cik IN :target_ciks").bindparams(
                bindparam("target_ciks", expanding=True)
            ),
            {"target_ciks": target_ciks or ["0000000000"]},
        ).all()
        existing = {str(x[0]) for x in existing_rows if x and x[0]}
        missing = [c for c in target_ciks if c not in existing]

        client = SecClient(session=session, limiter=limiter, db=db)
        svc_13f = Sec13FIngestionService(db=db, sec_client=client)
        svc_13dg = Sec13DGIngestionService(db=db, sec_client=client)

        total_filings = 0
        total_holdings = 0
        total_events = 0
        for cik in missing:
            r13f = svc_13f.ingest_for_cik(cik=cik, limit=limit)
            total_filings += r13f.filings_upserted
            total_holdings += r13f.holdings_inserted
            if include_13dg:
                r13dg = svc_13dg.ingest_for_cik(cik=cik, limit=limit)
                total_filings += r13dg.filings_upserted
                total_events += r13dg.events_inserted

    print(
        "seed_top_aum_selected "
        f"dataset_url={selected_dataset_url} top_n={top_n} selected={len(target_ciks)} "
        f"existing={len(existing)} missing={len(missing)} out={out_file}"
    )
    print(
        f"seed_top_aum_ingest filings_upserted={total_filings} "
        f"holdings_inserted={total_holdings} events_inserted={total_events}"
    )

    _resolve_mappings(limit=None)
    _refresh_aggregates()
    _refresh_universe(top_n=top_n)
    if prune_below_threshold:
        _prune_below_aum(top_n=top_n)
        _refresh_aggregates()
        _refresh_universe(top_n=top_n)


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


def _update_incremental(
    top_n: int,
    ingest_limit: int,
    include_13dg: bool,
    resolve_quarters: int,
    recent_quarters: int,
    min_holders: int,
    min_total_value_usd: float,
    skip_sync_tickers: bool,
    log_file: str,
    alert_min_13f_pct: float,
    alert_min_bo_pct: float,
) -> None:
    engine = get_engine()
    ensure_schema_and_seed(engine)
    _ensure_pipeline_log_table(engine)
    run_id = datetime.utcnow().strftime("incr-%Y%m%dT%H%M%SZ")
    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="incremental_start",
        status="INFO",
        message="Starting incremental update",
        metrics={
            "top_n": top_n,
            "ingest_limit": ingest_limit,
            "include_13dg": include_13dg,
            "resolve_quarters": resolve_quarters,
            "recent_quarters": recent_quarters,
            "min_holders": min_holders,
            "min_total_value_usd": min_total_value_usd,
            "skip_sync_tickers": skip_sync_tickers,
        },
        log_file=log_file,
    )

    t0 = time.perf_counter()
    _refresh_universe(top_n=top_n)
    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="refresh_universe_pre",
        status="INFO",
        message="Refreshed manager universe before ingest",
        metrics={"elapsed_sec": round(time.perf_counter() - t0, 3)},
        log_file=log_file,
    )

    t_ing = time.perf_counter()
    _ingest_universe(limit=ingest_limit, include_13dg=include_13dg)
    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="ingest_universe",
        status="INFO",
        message="Ingested active manager universe filings",
        metrics={"elapsed_sec": round(time.perf_counter() - t_ing, 3)},
        log_file=log_file,
    )

    before = _current_mapping_counts(engine)
    t_res = time.perf_counter()
    from sqlalchemy.orm import Session
    from app.resolution.security_resolver import SecurityResolverService

    with Session(bind=engine) as db:
        summary = SecurityResolverService(db=db).resolve_all(limit=resolve_quarters)
    after = _current_mapping_counts(engine)
    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="resolve_recent",
        status="INFO",
        message="Resolved mappings for recent quarter batches",
        metrics={
            "elapsed_sec": round(time.perf_counter() - t_res, 3),
            "bootstrap_created": summary.bootstrap_created,
            "holdings_mapped": summary.holdings_mapped,
            "bo_events_mapped": summary.bo_events_mapped,
            "holdings_batches": summary.holdings_batches or [],
            "bo_batches": summary.bo_batches or [],
            "before": before,
            "after": after,
        },
        log_file=log_file,
    )

    if skip_sync_tickers:
        _emit_run_event(
            engine=engine,
            run_id=run_id,
            stage="sync_tickers",
            status="INFO",
            message="Skipped ticker sync by flag",
            metrics={},
            log_file=log_file,
        )
    else:
        t_sync = time.perf_counter()
        _sync_tickers(
            limit=None,
            recent_quarters=recent_quarters,
            min_holders=min_holders,
            min_total_value_usd=min_total_value_usd,
            universe_only=True,
        )
        _emit_run_event(
            engine=engine,
            run_id=run_id,
            stage="sync_tickers",
            status="INFO",
            message="Completed ticker sync",
            metrics={"elapsed_sec": round(time.perf_counter() - t_sync, 3)},
            log_file=log_file,
        )

    t_agg = time.perf_counter()
    _refresh_aggregates()
    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="refresh_aggregates",
        status="INFO",
        message="Completed aggregate refresh",
        metrics={"elapsed_sec": round(time.perf_counter() - t_agg, 3)},
        log_file=log_file,
    )
    t_uni = time.perf_counter()
    _refresh_universe(top_n=top_n)
    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="refresh_universe_post",
        status="INFO",
        message="Refreshed manager universe after ingest+resolve",
        metrics={"elapsed_sec": round(time.perf_counter() - t_uni, 3)},
        log_file=log_file,
    )
    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="incremental_done",
        status="INFO",
        message="Incremental update completed",
        metrics={"final_counts": _current_mapping_counts(engine)},
        log_file=log_file,
    )
    final_counts = _current_mapping_counts(engine)
    coverage = _coverage_metrics(final_counts)
    if coverage["mapping_pct_13f"] < alert_min_13f_pct or coverage["mapping_pct_bo"] < alert_min_bo_pct:
        _emit_run_event(
            engine=engine,
            run_id=run_id,
            stage="mapping_alert",
            status="WARN",
            message="Mapping coverage below configured threshold",
            metrics={
                **coverage,
                "alert_min_13f_pct": alert_min_13f_pct,
                "alert_min_bo_pct": alert_min_bo_pct,
                "counts": final_counts,
            },
            log_file=log_file,
        )


def _ensure_pipeline_log_table(engine) -> None:
    from sqlalchemy.orm import Session

    with Session(bind=engine) as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS pipeline_run_events (
                  run_id TEXT NOT NULL,
                  event_ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  stage TEXT NOT NULL,
                  status TEXT NOT NULL,
                  message TEXT,
                  metrics_json TEXT
                )
                """
            )
        )
        db.commit()


def _emit_run_event(
    engine,
    run_id: str,
    stage: str,
    status: str,
    message: str,
    metrics: dict | None = None,
    log_file: str = "",
) -> None:
    from sqlalchemy.orm import Session

    payload = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "message": message,
        "metrics": metrics or {},
    }
    line = json.dumps(payload, separators=(",", ":"))
    print(line)
    if log_file:
        p = Path(log_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    with Session(bind=engine) as db:
        db.execute(
            text(
                """
                INSERT INTO pipeline_run_events (run_id, stage, status, message, metrics_json)
                VALUES (:run_id, :stage, :status, :message, :metrics_json)
                """
            ),
            {
                "run_id": run_id,
                "stage": stage,
                "status": status,
                "message": message,
                "metrics_json": json.dumps(metrics or {}),
            },
        )
        db.commit()


def _current_mapping_counts(engine) -> dict[str, int]:
    from sqlalchemy.orm import Session

    with Session(bind=engine) as db:
        unmapped_13f = int(
            db.execute(text("SELECT COUNT(*) FROM holdings_13f WHERE security_id IS NULL")).scalar() or 0
        )
        mapped_13f = int(
            db.execute(text("SELECT COUNT(*) FROM holdings_13f WHERE security_id IS NOT NULL")).scalar() or 0
        )
        unmapped_bo = int(
            db.execute(text("SELECT COUNT(*) FROM beneficial_ownership_events WHERE security_id IS NULL")).scalar()
            or 0
        )
        mapped_bo = int(
            db.execute(text("SELECT COUNT(*) FROM beneficial_ownership_events WHERE security_id IS NOT NULL")).scalar()
            or 0
        )
    return {
        "unmapped_13f": unmapped_13f,
        "mapped_13f": mapped_13f,
        "unmapped_bo": unmapped_bo,
        "mapped_bo": mapped_bo,
    }


def _coverage_metrics(counts: dict[str, int]) -> dict[str, float]:
    total_13f = counts["mapped_13f"] + counts["unmapped_13f"]
    total_bo = counts["mapped_bo"] + counts["unmapped_bo"]
    pct_13f = (counts["mapped_13f"] * 100.0 / total_13f) if total_13f else 100.0
    pct_bo = (counts["mapped_bo"] * 100.0 / total_bo) if total_bo else 100.0
    return {"mapping_pct_13f": round(pct_13f, 2), "mapping_pct_bo": round(pct_bo, 2)}


def _resume_post_ingest(
    batch_size: int,
    max_batches: int,
    recent_quarters: int,
    min_holders: int,
    min_total_value_usd: float,
    top_n: int,
    log_file: str,
    skip_sync_tickers: bool,
    alert_min_13f_pct: float,
    alert_min_bo_pct: float,
) -> None:
    engine = get_engine()
    ensure_schema_and_seed(engine)
    _ensure_pipeline_log_table(engine)
    run_id = datetime.utcnow().strftime("post-%Y%m%dT%H%M%SZ")
    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="resume_start",
        status="INFO",
        message="Starting resume-post-ingest",
        metrics={
            "batch_size": batch_size,
            "max_batches": max_batches,
            "recent_quarters": recent_quarters,
            "min_holders": min_holders,
            "min_total_value_usd": min_total_value_usd,
            "top_n": top_n,
            "skip_sync_tickers": skip_sync_tickers,
            "api_db_url": get_settings().api_db_url,
        },
        log_file=log_file,
    )

    total_bootstrap = 0
    total_holdings = 0
    total_bo = 0
    for i in range(1, max_batches + 1):
        from sqlalchemy.orm import Session

        from app.resolution.security_resolver import SecurityResolverService

        before = _current_mapping_counts(engine)
        t0 = time.perf_counter()
        try:
            with Session(bind=engine) as db:
                summary = SecurityResolverService(db=db).resolve_all(limit=batch_size)
        except Exception as exc:
            _emit_run_event(
                engine=engine,
                run_id=run_id,
                stage="resolve_batch",
                status="ERROR",
                message=f"Resolve batch {i} failed: {exc}",
                metrics={"batch": i, "before": before},
                log_file=log_file,
            )
            raise
        elapsed = round(time.perf_counter() - t0, 3)
        after = _current_mapping_counts(engine)

        total_bootstrap += summary.bootstrap_created
        total_holdings += summary.holdings_mapped
        total_bo += summary.bo_events_mapped
        _emit_run_event(
            engine=engine,
            run_id=run_id,
            stage="resolve_batch",
            status="INFO",
            message=f"Completed resolve batch {i}",
            metrics={
                "batch": i,
                "elapsed_sec": elapsed,
                "bootstrap_created": summary.bootstrap_created,
                "holdings_mapped": summary.holdings_mapped,
                "bo_events_mapped": summary.bo_events_mapped,
                "holdings_batches": summary.holdings_batches or [],
                "bo_batches": summary.bo_batches or [],
                "before": before,
                "after": after,
            },
            log_file=log_file,
        )
        if summary.bootstrap_created == 0 and summary.holdings_mapped == 0 and summary.bo_events_mapped == 0:
            break

    try:
        if skip_sync_tickers:
            _emit_run_event(
                engine=engine,
                run_id=run_id,
                stage="sync_tickers",
                status="INFO",
                message="Skipped ticker sync by flag",
                metrics={},
                log_file=log_file,
            )
        else:
            t_sync = time.perf_counter()
            _sync_tickers(
                limit=None,
                recent_quarters=recent_quarters,
                min_holders=min_holders,
                min_total_value_usd=min_total_value_usd,
                universe_only=True,
            )
            _emit_run_event(
                engine=engine,
                run_id=run_id,
                stage="sync_tickers",
                status="INFO",
                message="Completed ticker sync",
                metrics={"elapsed_sec": round(time.perf_counter() - t_sync, 3)},
                log_file=log_file,
            )

        t_agg = time.perf_counter()
        _refresh_aggregates()
        _emit_run_event(
            engine=engine,
            run_id=run_id,
            stage="refresh_aggregates",
            status="INFO",
            message="Completed aggregate refresh",
            metrics={"elapsed_sec": round(time.perf_counter() - t_agg, 3)},
            log_file=log_file,
        )

        t_uni = time.perf_counter()
        _refresh_universe(top_n=top_n)
        _emit_run_event(
            engine=engine,
            run_id=run_id,
            stage="refresh_universe",
            status="INFO",
            message="Completed universe refresh",
            metrics={"elapsed_sec": round(time.perf_counter() - t_uni, 3)},
            log_file=log_file,
        )
    except Exception as exc:
        _emit_run_event(
            engine=engine,
            run_id=run_id,
            stage="post_resolve",
            status="ERROR",
            message=f"Post-resolve stage failed: {exc}",
            metrics={},
            log_file=log_file,
        )
        raise
    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="resume_done",
        status="INFO",
        message="resume-post-ingest completed",
        metrics={
            "bootstrap_created_total": total_bootstrap,
            "holdings_mapped_total": total_holdings,
            "bo_events_mapped_total": total_bo,
            "final_counts": _current_mapping_counts(engine),
        },
        log_file=log_file,
    )
    final_counts = _current_mapping_counts(engine)
    coverage = _coverage_metrics(final_counts)
    if coverage["mapping_pct_13f"] < alert_min_13f_pct or coverage["mapping_pct_bo"] < alert_min_bo_pct:
        _emit_run_event(
            engine=engine,
            run_id=run_id,
            stage="mapping_alert",
            status="WARN",
            message="Mapping coverage below configured threshold",
            metrics={
                **coverage,
                "alert_min_13f_pct": alert_min_13f_pct,
                "alert_min_bo_pct": alert_min_bo_pct,
                "counts": final_counts,
            },
            log_file=log_file,
        )


def _enrich_cusips(
    recent_quarters: int,
    top_n: int,
    min_holders: int,
    min_total_value_usd: float,
    provider_name: str,
    limit_cusips: int,
    log_file: str,
) -> None:
    from sqlalchemy.orm import Session

    from app.clients.rate_limit import ProviderRateLimiter
    from app.enrichment.cusip_to_ticker import (
        CusipToTickerEnrichmentService,
        NoopCusipProvider,
        OpenFigiCusipProvider,
    )

    engine = get_engine()
    ensure_schema_and_seed(engine)
    _ensure_pipeline_log_table(engine)
    run_id = datetime.utcnow().strftime("enrich-%Y%m%dT%H%M%SZ")
    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="enrich_start",
        status="INFO",
        message="Starting CUSIP enrichment",
        metrics={
            "provider": provider_name,
            "recent_quarters": recent_quarters,
            "top_n": top_n,
            "min_holders": min_holders,
            "min_total_value_usd": min_total_value_usd,
            "limit_cusips": limit_cusips,
        },
        log_file=log_file,
    )

    with Session(bind=engine) as db:
        if provider_name == "openfigi":
            settings = get_settings()
            limiter = ProviderRateLimiter()
            rpm = float(settings.openfigi_requests_per_minute)
            limiter.register(provider="OPENFIGI", rate_per_sec=max(0.01, rpm / 60.0))
            provider = OpenFigiCusipProvider(db=db, limiter=limiter)
        else:
            provider = NoopCusipProvider()

        t0 = time.perf_counter()
        summary = CusipToTickerEnrichmentService(db=db, provider=provider).enrich_in_scope(
            recent_quarters=recent_quarters,
            top_n=top_n,
            min_holders=min_holders,
            min_total_value_usd=min_total_value_usd,
            limit_cusips=(limit_cusips or None),
        )
        elapsed = round(time.perf_counter() - t0, 3)

    _emit_run_event(
        engine=engine,
        run_id=run_id,
        stage="enrich_done",
        status="INFO",
        message="Completed CUSIP enrichment",
        metrics={
            "runtime_sec": elapsed,
            "scanned": summary.scanned,
            "eligible": summary.eligible,
            "matched": summary.matched,
            "inserted_xwalk": summary.inserted_xwalk,
            "inserted_identifiers": summary.inserted_identifiers,
        },
        log_file=log_file,
    )


def _refresh_aggregates() -> None:
    from sqlalchemy.orm import Session

    from app.analytics.aggregates import AggregateRefreshService

    engine = get_engine()
    ensure_schema_and_seed(engine)
    with Session(bind=engine) as db:
        service = AggregateRefreshService(db=db)
        summary = service.refresh_all()
        print(f"security_rows={summary.security_rows} manager_rows={summary.manager_rows}")


def _validate_live(
    manager_keys: list[str],
    tickers: list[str],
    sample_managers: int,
    sample_tickers: int,
    tolerance_pct: float,
    external_provider: str,
    json_out: str,
    fail_on_error: bool,
) -> None:
    from sqlalchemy.orm import Session

    from app.validation.live_validation import report_to_json, report_to_text, run_live_validation

    engine = get_engine()
    ensure_schema_and_seed(engine)
    with Session(bind=engine) as db:
        report = run_live_validation(
            db=db,
            manager_keys=manager_keys,
            tickers=tickers,
            sample_managers=sample_managers,
            sample_tickers=sample_tickers,
            tolerance_pct=tolerance_pct,
            external_provider=external_provider,
        )
    print(report_to_text(report))
    if json_out:
        out = Path(json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_to_json(report), encoding="utf-8")
        print(f"json_report={out}")
    if fail_on_error and int(report.get("error_count", 0)) > 0:
        raise SystemExit(2)


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
    elif args.command == "update-incremental":
        _update_incremental(
            top_n=args.top_n,
            ingest_limit=args.ingest_limit,
            include_13dg=args.include_13dg,
            resolve_quarters=args.resolve_quarters,
            recent_quarters=args.recent_quarters,
            min_holders=args.min_holders,
            min_total_value_usd=args.min_total_value_usd,
            skip_sync_tickers=args.skip_sync_tickers,
            log_file=args.log_file,
            alert_min_13f_pct=args.alert_min_13f_pct,
            alert_min_bo_pct=args.alert_min_bo_pct,
        )
    elif args.command == "resume-post-ingest":
        _resume_post_ingest(
            batch_size=args.batch_size,
            max_batches=args.max_batches,
            recent_quarters=args.recent_quarters,
            min_holders=args.min_holders,
            min_total_value_usd=args.min_total_value_usd,
            top_n=args.top_n,
            log_file=args.log_file,
            skip_sync_tickers=args.skip_sync_tickers,
            alert_min_13f_pct=args.alert_min_13f_pct,
            alert_min_bo_pct=args.alert_min_bo_pct,
        )
    elif args.command == "ingest-cik-list":
        _ingest_cik_list(file_path=args.file, limit=args.limit, include_13dg=args.include_13dg)
    elif args.command == "discover-13f-ciks":
        _discover_13f_ciks(quarters=args.quarters, max_ciks=args.max_ciks, out_path=args.out)
    elif args.command == "seed-top-aum":
        _seed_top_aum(
            top_n=args.top_n,
            limit=args.limit,
            include_13dg=args.include_13dg,
            dataset_url=args.dataset_url,
            out_path=args.out,
            prune_below_threshold=not bool(args.no_prune),
        )
    elif args.command == "enrich-cusips":
        _enrich_cusips(
            recent_quarters=args.recent_quarters,
            top_n=args.top_n,
            min_holders=args.min_holders,
            min_total_value_usd=args.min_total_value_usd,
            provider_name=args.provider,
            limit_cusips=args.limit_cusips,
            log_file=args.log_file,
        )
    elif args.command == "validate-live":
        _validate_live(
            manager_keys=args.manager_key,
            tickers=args.ticker,
            sample_managers=args.sample_managers,
            sample_tickers=args.sample_tickers,
            tolerance_pct=args.tolerance_pct,
            external_provider=args.external_provider,
            json_out=args.json_out,
            fail_on_error=args.fail_on_error,
        )
    elif args.command == "refresh-aggregates":
        _refresh_aggregates()
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
