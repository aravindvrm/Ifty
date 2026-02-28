from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import urlencode

import requests
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.api import routes
from app.clients.rate_limit import ProviderRateLimiter
from app.config import get_settings

_MAPPED_NON_OPTION_FILTER = """
    security_id IS NOT NULL
    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
    AND option_type IS NULL
"""

_MATCH_KEY_EXPR = """
    COALESCE(
      NULLIF(UPPER(REPLACE(REPLACE(TRIM(cusip_raw), '-', ''), ' ', '')), ''),
      'SID:' || CAST(security_id AS TEXT)
    )
"""


@dataclass
class ValidationIssue:
    scope: str
    key: str
    metric: str
    severity: str
    expected: Any
    actual: Any
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "key": self.key,
            "metric": self.metric,
            "severity": self.severity,
            "expected": self.expected,
            "actual": self.actual,
            "note": self.note,
        }


def _parse_number(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    s = s.replace(",", "").replace("$", "")
    m = re.search(r"-?\d+(\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _symbol_variants(ticker: str) -> list[str]:
    t = ticker.upper().strip()
    variants: list[str] = []
    for candidate in (t, t.replace("/", "."), t.replace("/", "-")):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants


def _is_close(actual: float | int | None, expected: float | int | None, tolerance_pct: float) -> bool:
    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False
    a = float(actual)
    e = float(expected)
    if a == e:
        return True
    tol = max(1e-9, abs(e) * tolerance_pct / 100.0)
    return abs(a - e) <= tol


def _sample_manager_keys(db: Session, n: int) -> list[str]:
    if n <= 0:
        return []
    rows = db.execute(
        text(
            """
            SELECT CAST(manager_id AS TEXT) AS manager_key
            FROM manager_universe
            WHERE is_active = 1
            ORDER BY rank
            LIMIT :n
            """
        ),
        {"n": n},
    ).all()
    if rows:
        return [str(x[0]) for x in rows]
    rows = db.execute(
        text(
            """
            SELECT CAST(manager_id AS TEXT) AS manager_key
            FROM managers
            ORDER BY manager_id
            LIMIT :n
            """
        ),
        {"n": n},
    ).all()
    return [str(x[0]) for x in rows]


def _sample_tickers(db: Session, n: int) -> list[str]:
    if n <= 0:
        return []
    mapped_filter_h = """
        h.security_id IS NOT NULL
        AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
        AND h.option_type IS NULL
    """
    mapped_filter_plain = """
        security_id IS NOT NULL
        AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
        AND option_type IS NULL
    """
    rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT MAX(report_date) AS report_date
              FROM holdings_13f
              WHERE """
            + mapped_filter_plain
            + """
            )
            SELECT si.id_value AS ticker
            FROM holdings_13f h
            JOIN latest l ON l.report_date = h.report_date
            JOIN security_identifiers si ON si.security_id = h.security_id
            JOIN securities s ON s.security_id = h.security_id
            WHERE """
            + mapped_filter_h
            + """
              AND si.id_type = 'TICKER'
              AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
              AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
            GROUP BY si.id_value
            ORDER BY SUM(COALESCE(h.value_usd_thousands, 0)) DESC
            LIMIT :n
            """
        ),
        {"n": n},
    ).all()
    return [str(x[0]).upper() for x in rows]


def _manager_expected_metrics(db: Session, manager_id: int) -> dict[str, Any]:
    value_to_usd_multiplier = routes._value_to_usd_multiplier(db=db)  # noqa: SLF001
    latest_filing = routes._manager_filing_row(db=db, manager_id=manager_id, require_mapped_positions=True) or routes._manager_filing_row(  # noqa: SLF001
        db=db,
        manager_id=manager_id,
        require_mapped_positions=False,
    )
    if latest_filing is None:
        return {
            "latest_quarter": None,
            "turnover_ratio": None,
            "top10_concentration_pct": None,
            "new_positions_count": 0,
            "exited_positions_count": 0,
            "total_value_current": 0.0,
            "total_value_previous": 0.0,
            "top_buy_delta": None,
            "top_sell_delta": None,
            "prev_coverage_gap": False,
            "latest_period_filing_count": 0,
        }
    latest_date = str(latest_filing["period_end_date"])
    curr_filing_id = int(latest_filing["filing_id"])
    prev_any_filing = routes._manager_filing_row(  # noqa: SLF001
        db=db,
        manager_id=manager_id,
        before_period_end_date=latest_date,
        require_mapped_positions=False,
    )
    latest_period_filing_count = int(
        db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM filings
                WHERE manager_id = :manager_id
                  AND period_end_date = :latest_date
                  AND form_type IN ('13F-HR', '13F-HR/A')
                """
            ),
            {"manager_id": manager_id, "latest_date": latest_date},
        ).scalar()
        or 0
    )

    curr_totals = db.execute(
        text(
            """
            WITH curr AS (
              SELECT
                """
            + _MATCH_KEY_EXPR
            + """
                AS match_key,
                SUM(COALESCE(value_usd_thousands, 0)) AS curr_val
              FROM holdings_13f
              WHERE filing_id = :curr_filing_id
                AND """
            + _MAPPED_NON_OPTION_FILTER
            + """
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

    prev_filing = routes._manager_prior_comparison_filing(  # noqa: SLF001
        db=db,
        manager_id=manager_id,
        latest_period_end_date=latest_date,
        curr_positions_count=curr_positions_count,
        curr_total_raw_value=total_curr_raw,
    )
    prev_coverage_gap = prev_any_filing is not None and prev_filing is None
    if prev_filing is None:
        return {
            "latest_quarter": latest_date,
            "turnover_ratio": None,
            "top10_concentration_pct": (top10_curr_raw / total_curr_raw) if total_curr_raw > 0 else 0.0,
            "new_positions_count": 0,
            "exited_positions_count": 0,
            "total_value_current": total_curr_raw * value_to_usd_multiplier,
            "total_value_previous": 0.0,
            "top_buy_delta": None,
            "top_sell_delta": None,
            "prev_coverage_gap": prev_coverage_gap,
            "latest_period_filing_count": latest_period_filing_count,
        }
    prev_filing_id = int(prev_filing["filing_id"])

    rows = db.execute(
        text(
            """
            WITH curr AS (
              SELECT
                """ + _MATCH_KEY_EXPR + """
                AS match_key,
                SUM(COALESCE(value_usd_thousands, 0)) AS curr_val
              FROM holdings_13f
              WHERE filing_id = :curr_filing_id
                AND """ + _MAPPED_NON_OPTION_FILTER + """
              GROUP BY match_key
            ),
            prev AS (
              SELECT
                """ + _MATCH_KEY_EXPR + """
                AS match_key,
                SUM(COALESCE(value_usd_thousands, 0)) AS prev_val
              FROM holdings_13f
              WHERE filing_id = :prev_filing_id
                AND """ + _MAPPED_NON_OPTION_FILTER + """
              GROUP BY match_key
            ),
            combined AS (
              SELECT c.match_key, c.curr_val, COALESCE(p.prev_val, 0) AS prev_val
              FROM curr c
              LEFT JOIN prev p ON p.match_key = c.match_key
              UNION ALL
              SELECT p.match_key, 0 AS curr_val, p.prev_val
              FROM prev p
              LEFT JOIN curr c ON c.match_key = p.match_key
              WHERE c.match_key IS NULL
            )
            SELECT match_key, curr_val, prev_val, (curr_val - prev_val) AS delta_val
            FROM combined
            """
        ),
        {"curr_filing_id": curr_filing_id, "prev_filing_id": prev_filing_id},
    ).mappings().all()

    counts = db.execute(
        text(
            """
            WITH curr AS (
              SELECT
                """
                + _MATCH_KEY_EXPR
                + """
                AS match_key
              FROM holdings_13f
              WHERE filing_id = :curr_filing_id
                AND """
            + _MAPPED_NON_OPTION_FILTER
            + """
              GROUP BY match_key
            ),
            prev AS (
              SELECT
                """
                + _MATCH_KEY_EXPR
                + """
                AS match_key
              FROM holdings_13f
              WHERE filing_id = :prev_filing_id
                AND """
            + _MAPPED_NON_OPTION_FILTER
            + """
              GROUP BY match_key
            )
            SELECT
              (SELECT COUNT(*) FROM curr c LEFT JOIN prev p ON p.match_key = c.match_key WHERE p.match_key IS NULL) AS new_count,
              (SELECT COUNT(*) FROM prev p LEFT JOIN curr c ON c.match_key = p.match_key WHERE c.match_key IS NULL) AS exited_count
            """
        ),
        {"curr_filing_id": curr_filing_id, "prev_filing_id": prev_filing_id},
    ).mappings().first()

    total_curr_raw = sum(float(r["curr_val"] or 0.0) for r in rows)
    total_prev_raw = sum(float(r["prev_val"] or 0.0) for r in rows)
    abs_delta_sum = sum(abs(float(r["delta_val"] or 0.0)) for r in rows)
    denom = total_curr_raw + total_prev_raw
    turnover = (abs_delta_sum / denom) if denom > 0 else 0.0
    sorted_curr = sorted((float(r["curr_val"] or 0.0) for r in rows), reverse=True)
    top10_curr_raw = sum(sorted_curr[:10])
    new_count = int((counts or {}).get("new_count", 0) or 0)
    exited_count = int((counts or {}).get("exited_count", 0) or 0)
    pos_deltas_k = [
        (float(r["delta_val"] or 0.0) * value_to_usd_multiplier) / 1000.0
        for r in rows
        if float(r["delta_val"] or 0.0) > 0
    ]
    neg_deltas_k = [
        (float(r["delta_val"] or 0.0) * value_to_usd_multiplier) / 1000.0
        for r in rows
        if float(r["delta_val"] or 0.0) < 0
    ]

    return {
        "latest_quarter": latest_date,
        "turnover_ratio": turnover,
        "top10_concentration_pct": (top10_curr_raw / total_curr_raw) if total_curr_raw > 0 else 0.0,
        "new_positions_count": new_count,
        "exited_positions_count": exited_count,
        "total_value_current": total_curr_raw * value_to_usd_multiplier,
        "total_value_previous": total_prev_raw * value_to_usd_multiplier,
        "top_buy_delta": max(pos_deltas_k) if pos_deltas_k else None,
        "top_sell_delta": min(neg_deltas_k) if neg_deltas_k else None,
        "prev_coverage_gap": prev_coverage_gap,
        "latest_period_filing_count": latest_period_filing_count,
    }


def _security_expected_metrics(db: Session, ticker: str) -> dict[str, Any]:
    sec_row = routes._lookup_active_security_by_ticker(db=db, ticker=ticker)  # noqa: SLF001
    if not sec_row:
        return {"exists": False}

    security_id = int(sec_row["security_id"])
    scope_ids = routes._resolve_security_scope_ids(db=db, ticker=ticker)  # noqa: SLF001
    if not scope_ids:
        scope_ids = [security_id]

    latest_date = db.execute(
        text(
            """
            SELECT MAX(report_date)
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
            "exists": True,
            "latest_quarter": None,
            "prev_quarter": None,
            "internal_split_factor": None,
        }

    value_to_usd_multiplier = routes._value_to_usd_multiplier(db=db)  # noqa: SLF001
    latest_rows = db.execute(
        text(
            """
            SELECT manager_id, SUM(COALESCE(shares, 0)) AS shares, SUM(COALESCE(value_usd_thousands, 0)) AS value_raw
            FROM holdings_13f
            WHERE security_id IN :scope_ids
              AND report_date = :latest_date
              AND option_type IS NULL
              AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
            GROUP BY manager_id
            """
        ).bindparams(bindparam("scope_ids", expanding=True)),
        {"scope_ids": scope_ids, "latest_date": latest_date},
    ).mappings().all()
    by_manager_curr = {int(r["manager_id"]): float(r["shares"] or 0.0) for r in latest_rows}
    holders_count = len(by_manager_curr)
    total_shares = sum(float(r["shares"] or 0.0) for r in latest_rows)
    total_value_usd = sum(float(r["value_raw"] or 0.0) * value_to_usd_multiplier for r in latest_rows)
    top10_shares = sum(sorted((float(r["shares"] or 0.0) for r in latest_rows), reverse=True)[:10])

    prev_date = db.execute(
        text(
            """
            SELECT MAX(report_date)
            FROM holdings_13f
            WHERE security_id IN :scope_ids
              AND option_type IS NULL
              AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
              AND report_date < :latest_date
            """
        ).bindparams(bindparam("scope_ids", expanding=True)),
        {"scope_ids": scope_ids, "latest_date": latest_date},
    ).scalar()
    by_manager_prev: dict[int, float] = {}
    if prev_date is not None:
        prev_rows = db.execute(
            text(
                """
                SELECT manager_id, SUM(COALESCE(shares, 0)) AS shares
                FROM holdings_13f
                WHERE security_id IN :scope_ids
                  AND report_date = :prev_date
                  AND option_type IS NULL
                  AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                GROUP BY manager_id
                """
            ).bindparams(bindparam("scope_ids", expanding=True)),
            {"scope_ids": scope_ids, "prev_date": prev_date},
        ).mappings().all()
        by_manager_prev = {int(r["manager_id"]): float(r["shares"] or 0.0) for r in prev_rows}

    split_factor = 1.0
    if prev_date is not None:
        split_factor = routes._split_factor_between(  # noqa: SLF001
            db=db, security_id=security_id, prev_date=prev_date, curr_date=latest_date
        )
    manager_union = set(by_manager_curr) | set(by_manager_prev)
    qoq_net_change = 0.0
    for manager_id in manager_union:
        curr = by_manager_curr.get(manager_id, 0.0)
        prev = by_manager_prev.get(manager_id, 0.0)
        prev_adj = prev * split_factor if prev_date is not None else 0.0
        qoq_net_change += curr - prev_adj

    return {
        "exists": True,
        "latest_quarter": latest_date,
        "prev_quarter": prev_date,
        "internal_split_factor": split_factor if prev_date is not None else None,
        "holders_count": holders_count,
        "total_shares": total_shares,
        "total_value_usd": total_value_usd,
        "qoq_net_change_shares": qoq_net_change,
        "top10_concentration_pct": (top10_shares / total_shares) if total_shares > 0 else 0.0,
    }


def _extract_key_values(data: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                out.update(_extract_key_values(v, key))
            else:
                out[key.lower()] = v
    elif isinstance(data, list):
        for idx, v in enumerate(data):
            key = f"{prefix}[{idx}]"
            if isinstance(v, (dict, list)):
                out.update(_extract_key_values(v, key))
            else:
                out[key.lower()] = v
    return out


def _fetch_external_nasdaq_security_snapshot(
    ticker: str,
    limiter: ProviderRateLimiter | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    user_agent = settings.sec_user_agent.strip() or "Mozilla/5.0"
    url = f"https://api.nasdaq.com/api/company/{ticker}/institutional-holdings?limit=100&offset=0"
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.nasdaq.com",
        "Referer": f"https://www.nasdaq.com/market-activity/stocks/{ticker.lower()}/institutional-holdings",
    }
    if limiter is not None:
        limiter.acquire("NASDAQ")
    response = requests.get(url, headers=headers, timeout=max(10.0, settings.request_timeout_seconds))
    response.raise_for_status()
    payload = response.json()
    flat = _extract_key_values(payload.get("data", payload))

    holders_val = None
    shares_val = None
    for k, v in flat.items():
        if holders_val is None and "holder" in k and "institution" in k and "change" not in k:
            holders_val = _parse_number(v)
        if shares_val is None and "share" in k and "held" in k and "change" not in k:
            shares_val = _parse_number(v)
        if shares_val is None and "activeposition" in k:
            shares_val = _parse_number(v)

    return {
        "ticker": ticker.upper(),
        "holders_count": int(holders_val) if holders_val is not None else None,
        "total_shares": shares_val,
        "raw_keys": list(flat.keys())[:25],
    }


def _fetch_external_alphavantage_security_snapshot(
    ticker: str,
    limiter: ProviderRateLimiter | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    api_key = settings.av_key.strip()
    if not api_key:
        raise ValueError("AV_KEY not configured")
    shares_outstanding = None
    used_symbol = ticker.upper()
    last_error = "Alpha Vantage response missing SharesOutstanding"
    for symbol in _symbol_variants(ticker):
        if limiter is not None:
            limiter.acquire("ALPHAVANTAGE")
        params = urlencode(
            {
                "function": "OVERVIEW",
                "symbol": symbol,
                "apikey": api_key,
            }
        )
        url = f"https://www.alphavantage.co/query?{params}"
        response = requests.get(url, timeout=max(10.0, settings.request_timeout_seconds))
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("Note"):
            last_error = str(payload.get("Note"))
            continue
        shares_outstanding = (
            _parse_number((payload or {}).get("SharesOutstanding")) if isinstance(payload, dict) else None
        )
        if shares_outstanding is not None:
            used_symbol = symbol
            break
    if shares_outstanding is None:
        raise RuntimeError(last_error)
    return {
        "source": "alphavantage",
        "ticker": used_symbol,
        "shares_outstanding": shares_outstanding,
    }


def _fetch_external_polygon_security_snapshot(
    ticker: str,
    start_date: str | None,
    end_date: str | None,
    limiter: ProviderRateLimiter | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    api_key = settings.poly_key.strip()
    if not api_key:
        raise ValueError("POLY_KEY not configured")
    def _get(url: str) -> dict[str, Any]:
        if limiter is not None:
            limiter.acquire("POLYGON")
        response = requests.get(url, timeout=max(10.0, settings.request_timeout_seconds))
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data if isinstance(data, dict) else {}

    used_symbol = ticker.upper()
    results: dict[str, Any] = {}
    last_error = "Polygon ticker snapshot unavailable"
    for symbol in _symbol_variants(ticker):
        snap_url = f"https://api.polygon.io/v3/reference/tickers/{symbol}?apiKey={api_key}"
        try:
            snap = _get(snap_url)
        except Exception as exc:  # pragma: no cover - network-dependent
            last_error = str(exc)
            continue
        results = snap.get("results", {}) if isinstance(snap, dict) else {}
        used_symbol = symbol
        break
    if not results:
        raise RuntimeError(last_error)

    shares_outstanding = None
    for key in ("share_class_shares_outstanding", "weighted_shares_outstanding"):
        shares_outstanding = _parse_number(results.get(key))
        if shares_outstanding is not None:
            break

    split_factor = None
    split_count = 0
    if start_date and end_date:
        q = urlencode(
            {
                "ticker": used_symbol,
                "execution_date.gte": start_date,
                "execution_date.lte": end_date,
                "limit": 1000,
                "apiKey": api_key,
            }
        )
        splits_url = f"https://api.polygon.io/v3/reference/splits?{q}"
        splits_payload = _get(splits_url)
        split_rows = splits_payload.get("results", []) if isinstance(splits_payload, dict) else []
        factor = 1.0
        for row in split_rows:
            split_to = _parse_number(row.get("split_to") if isinstance(row, dict) else None)
            split_from = _parse_number(row.get("split_from") if isinstance(row, dict) else None)
            if split_to is None or split_from in (None, 0):
                continue
            factor *= float(split_to) / float(split_from)
            split_count += 1
        split_factor = factor

    return {
        "source": "polygon",
        "ticker": used_symbol,
        "shares_outstanding": shares_outstanding,
        "split_factor": split_factor,
        "split_events_count": split_count,
    }


def _fetch_external_market_snapshot(
    ticker: str,
    start_date: str | None,
    end_date: str | None,
    provider: str,
    polygon_limiter: ProviderRateLimiter | None,
    av_limiter: ProviderRateLimiter | None,
) -> dict[str, Any]:
    if provider == "polygon":
        return _fetch_external_polygon_security_snapshot(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            limiter=polygon_limiter,
        )
    if provider == "alphavantage":
        return _fetch_external_alphavantage_security_snapshot(ticker=ticker, limiter=av_limiter)
    if provider == "auto":
        errs: list[str] = []
        try:
            return _fetch_external_polygon_security_snapshot(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                limiter=polygon_limiter,
            )
        except Exception as exc:
            errs.append(f"polygon: {exc}")
        try:
            return _fetch_external_alphavantage_security_snapshot(ticker=ticker, limiter=av_limiter)
        except Exception as exc:
            errs.append(f"alphavantage: {exc}")
        raise RuntimeError("; ".join(errs))
    raise ValueError(f"Unknown external provider: {provider}")


def run_live_validation(
    db: Session,
    manager_keys: list[str],
    tickers: list[str],
    sample_managers: int,
    sample_tickers: int,
    tolerance_pct: float,
    external_provider: str = "none",
) -> dict[str, Any]:
    issues: list[ValidationIssue] = []
    checked_managers: list[str] = []
    checked_tickers: list[str] = []
    external_limiter: ProviderRateLimiter | None = None
    if external_provider == "nasdaq":
        settings = get_settings()
        external_limiter = ProviderRateLimiter()
        external_limiter.register(
            provider="NASDAQ",
            rate_per_sec=max(0.05, float(settings.nasdaq_burst_per_second)),
            capacity=1.0,
        )
    polygon_limiter: ProviderRateLimiter | None = None
    av_limiter: ProviderRateLimiter | None = None
    if external_provider in {"polygon", "auto"}:
        settings = get_settings()
        polygon_limiter = ProviderRateLimiter()
        polygon_limiter.register(
            provider="POLYGON",
            rate_per_sec=max(0.05, float(settings.polygon_burst_per_second)),
            capacity=1.0,
        )
    if external_provider in {"alphavantage", "auto"}:
        settings = get_settings()
        av_limiter = ProviderRateLimiter()
        av_limiter.register(
            provider="ALPHAVANTAGE",
            rate_per_sec=max(0.03, float(settings.alphavantage_burst_per_second)),
            capacity=1.0,
        )

    manager_universe = list(dict.fromkeys([*(manager_keys or []), *_sample_manager_keys(db, sample_managers)]))
    ticker_universe = list(dict.fromkeys([*(t.upper() for t in (tickers or [])), *_sample_tickers(db, sample_tickers)]))

    # Global coverage check for broader sampled runs (skip targeted/fixture runs).
    if sample_managers > 0 or sample_tickers > 0:
        latest_q = db.execute(
            text(
                """
                SELECT MAX(period_end_date)
                FROM filings
                WHERE form_type IN ('13F-HR', '13F-HR/A')
                """
            )
        ).scalar()
        if latest_q is not None:
            mgr_count = int(
                db.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT manager_id)
                        FROM filings
                        WHERE form_type IN ('13F-HR', '13F-HR/A')
                          AND period_end_date = :latest_q
                        """
                    ),
                    {"latest_q": latest_q},
                ).scalar()
                or 0
            )
            if mgr_count < 1000:
                issues.append(
                    ValidationIssue(
                        scope="dataset_coverage",
                        key=str(latest_q),
                        metric="distinct_managers_latest_quarter",
                        severity="warn",
                        expected=">=1000",
                        actual=mgr_count,
                        note="Universe appears truncated; security/manager comparisons vs public sources may differ materially.",
                    )
                )
            anchor_managers = {
                "VANGUARD": "%VANGUARD%",
                "BLACKROCK": "%BLACKROCK%",
                "STATE_STREET": "%STATE STREET%",
            }
            for anchor_key, like_pattern in anchor_managers.items():
                anchor_count = int(
                    db.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM managers
                            WHERE UPPER(manager_name) LIKE :pattern
                            """
                        ),
                        {"pattern": like_pattern},
                    ).scalar()
                    or 0
                )
                if anchor_count == 0:
                    issues.append(
                        ValidationIssue(
                            scope="dataset_coverage",
                            key=anchor_key,
                            metric="anchor_manager_presence",
                            severity="warn",
                            expected=">=1",
                            actual=0,
                            note="Major institutional filer missing from manager universe; ingestion/discovery coverage is likely incomplete.",
                        )
                    )

    for manager_key in manager_universe:
        checked_managers.append(manager_key)
        actual = routes.manager_page(manager_key=manager_key, db=db)
        manager_id = int(actual["manager"]["manager_id"])
        expected = _manager_expected_metrics(db=db, manager_id=manager_id)
        if expected.get("prev_coverage_gap"):
            issues.append(
                ValidationIssue(
                    scope="manager_data_quality",
                    key=manager_key,
                    metric="prev_quarter_coverage",
                    severity="warn",
                    expected="mapped prior quarter available",
                    actual="prior filing exists but mapped holdings are missing",
                    note="QoQ metrics may be unstable for this manager until prior-quarter mapping coverage is restored.",
                )
            )
        if int(expected.get("latest_period_filing_count") or 0) > 1:
            issues.append(
                ValidationIssue(
                    scope="manager_data_quality",
                    key=manager_key,
                    metric="latest_quarter_filing_count",
                    severity="warn",
                    expected=1,
                    actual=int(expected.get("latest_period_filing_count") or 0),
                    note="Multiple filings for latest quarter; APIs must use canonical filing selection to avoid double-counting.",
                )
            )
        total_curr_usd = float(expected.get("total_value_current") or 0.0)
        total_prev_usd = float(expected.get("total_value_previous") or 0.0)
        if total_curr_usd > 0 and total_prev_usd / total_curr_usd < 0.01:
            issues.append(
                ValidationIssue(
                    scope="manager_data_quality",
                    key=manager_key,
                    metric="qoq_coverage_ratio",
                    severity="warn",
                    expected=">=1% previous-quarter value coverage",
                    actual=f"{(total_prev_usd / total_curr_usd) * 100:.4f}%",
                    note="Extremely low previous-quarter coverage often indicates mapping or filing-selection issues.",
                )
            )

        pairs = [
            ("latest_quarter", actual.get("latest_quarter"), expected.get("latest_quarter")),
            ("new_positions_count", actual.get("metrics", {}).get("new_positions_count"), expected.get("new_positions_count")),
            ("exited_positions_count", actual.get("metrics", {}).get("exited_positions_count"), expected.get("exited_positions_count")),
            ("turnover_ratio", actual.get("metrics", {}).get("turnover_ratio"), expected.get("turnover_ratio")),
            ("top10_concentration_pct", actual.get("metrics", {}).get("top10_concentration_pct"), expected.get("top10_concentration_pct")),
            ("total_value_current", actual.get("metrics", {}).get("total_value_current"), expected.get("total_value_current")),
            ("total_value_previous", actual.get("metrics", {}).get("total_value_previous"), expected.get("total_value_previous")),
        ]
        for metric, actual_val, expected_val in pairs:
            ok = (
                actual_val == expected_val
                if metric == "latest_quarter"
                else _is_close(actual_val, expected_val, tolerance_pct=tolerance_pct)
            )
            if not ok:
                issues.append(
                    ValidationIssue(
                        scope="manager",
                        key=manager_key,
                        metric=metric,
                        severity="error",
                        expected=expected_val,
                        actual=actual_val,
                    )
                )

        expected_top_buy = expected.get("top_buy_delta")
        actual_top_buy = (
            float(actual["top_buys"][0]["delta_val"]) if actual.get("top_buys") else None
        )
        if not _is_close(actual_top_buy, expected_top_buy, tolerance_pct=tolerance_pct):
            issues.append(
                ValidationIssue(
                    scope="manager",
                    key=manager_key,
                    metric="top_buy_delta",
                    severity="warn",
                    expected=expected_top_buy,
                    actual=actual_top_buy,
                    note="Top buy delta mismatch; review holdings diff keying.",
                )
            )

        expected_top_sell = expected.get("top_sell_delta")
        actual_top_sell = (
            float(actual["top_sells"][0]["delta_val"]) if actual.get("top_sells") else None
        )
        if not _is_close(actual_top_sell, expected_top_sell, tolerance_pct=tolerance_pct):
            issues.append(
                ValidationIssue(
                    scope="manager",
                    key=manager_key,
                    metric="top_sell_delta",
                    severity="warn",
                    expected=expected_top_sell,
                    actual=actual_top_sell,
                    note="Top sell delta mismatch; review holdings diff keying.",
                )
            )

    for ticker in ticker_universe:
        checked_tickers.append(ticker)
        actual = routes.security_page(ticker=ticker, db=db)
        expected = _security_expected_metrics(db=db, ticker=ticker)
        if not expected.get("exists"):
            issues.append(
                ValidationIssue(
                    scope="security",
                    key=ticker,
                    metric="exists",
                    severity="warn",
                    expected=True,
                    actual=False,
                    note="Ticker not mapped in active security identifiers.",
                )
            )
            continue

        pairs = [
            ("latest_quarter", actual.get("latest_quarter"), expected.get("latest_quarter")),
            ("holders_count", actual.get("ownership_summary", {}).get("holders_count"), expected.get("holders_count")),
            ("total_shares", actual.get("ownership_summary", {}).get("total_shares"), expected.get("total_shares")),
            ("total_value_usd", actual.get("ownership_summary", {}).get("total_value_usd"), expected.get("total_value_usd")),
            ("qoq_net_change_shares", actual.get("ownership_summary", {}).get("qoq_net_change_shares"), expected.get("qoq_net_change_shares")),
            (
                "top10_concentration_pct",
                actual.get("ownership_summary", {}).get("top10_concentration_pct"),
                expected.get("top10_concentration_pct"),
            ),
        ]
        for metric, actual_val, expected_val in pairs:
            ok = (
                actual_val == expected_val
                if metric == "latest_quarter"
                else _is_close(actual_val, expected_val, tolerance_pct=tolerance_pct)
            )
            if not ok:
                issues.append(
                    ValidationIssue(
                        scope="security",
                        key=ticker,
                        metric=metric,
                        severity="error",
                        expected=expected_val,
                        actual=actual_val,
                    )
                )

        if external_provider == "nasdaq":
            try:
                external = _fetch_external_nasdaq_security_snapshot(
                    ticker=ticker,
                    limiter=external_limiter,
                )
                ext_holders = external.get("holders_count")
                ext_shares = external.get("total_shares")
                int_holders = actual.get("ownership_summary", {}).get("holders_count")
                int_shares = actual.get("ownership_summary", {}).get("total_shares")
                if ext_holders is not None and int_holders is not None and not _is_close(
                    int_holders, ext_holders, tolerance_pct=max(tolerance_pct, 3.0)
                ):
                    issues.append(
                        ValidationIssue(
                            scope="security_external",
                            key=ticker,
                            metric="holders_count",
                            severity="warn",
                            expected=ext_holders,
                            actual=int_holders,
                            note="Mismatch vs Nasdaq institutional holders.",
                        )
                    )
                if ext_shares is not None and int_shares is not None and not _is_close(
                    int_shares, ext_shares, tolerance_pct=max(tolerance_pct, 5.0)
                ):
                    issues.append(
                        ValidationIssue(
                            scope="security_external",
                            key=ticker,
                            metric="total_shares",
                            severity="warn",
                            expected=ext_shares,
                            actual=int_shares,
                            note="Mismatch vs Nasdaq institutional shares.",
                        )
                    )
            except Exception as exc:  # pragma: no cover - network-dependent
                issues.append(
                    ValidationIssue(
                        scope="security_external",
                        key=ticker,
                        metric="nasdaq_fetch",
                        severity="warn",
                        expected="successful fetch",
                        actual="failed",
                        note=str(exc),
                    )
                )
        if external_provider in {"polygon", "alphavantage", "auto"}:
            try:
                external = _fetch_external_market_snapshot(
                    ticker=ticker,
                    start_date=expected.get("prev_quarter"),
                    end_date=expected.get("latest_quarter"),
                    provider=external_provider,
                    polygon_limiter=polygon_limiter,
                    av_limiter=av_limiter,
                )
                ext_shares_outstanding = external.get("shares_outstanding")
                int_shares = actual.get("ownership_summary", {}).get("total_shares")
                if (
                    ext_shares_outstanding is not None
                    and int_shares is not None
                    and float(int_shares) > float(ext_shares_outstanding) * 1.02
                ):
                    issues.append(
                        ValidationIssue(
                            scope="security_external",
                            key=ticker,
                            metric="total_shares_vs_outstanding",
                            severity="warn",
                            expected=f"<= {ext_shares_outstanding}",
                            actual=int_shares,
                            note=f"Internal institutional shares exceed outstanding ({external.get('source')}).",
                        )
                    )
                ext_split_factor = external.get("split_factor")
                int_split_factor = expected.get("internal_split_factor")
                if (
                    ext_split_factor is not None
                    and int_split_factor is not None
                    and not _is_close(
                        float(int_split_factor),
                        float(ext_split_factor),
                        tolerance_pct=max(0.5, tolerance_pct),
                    )
                ):
                    issues.append(
                        ValidationIssue(
                            scope="security_external",
                            key=ticker,
                            metric="split_factor",
                            severity="warn",
                            expected=ext_split_factor,
                            actual=int_split_factor,
                            note=f"Internal split factor differs vs {external.get('source')}.",
                        )
                    )
            except Exception as exc:  # pragma: no cover - network-dependent
                issues.append(
                    ValidationIssue(
                        scope="security_external",
                        key=ticker,
                        metric=f"{external_provider}_fetch",
                        severity="warn",
                        expected="successful fetch",
                        actual="failed",
                        note=str(exc),
                    )
                )

    error_count = sum(1 for i in issues if i.severity == "error")
    warn_count = sum(1 for i in issues if i.severity == "warn")
    return {
        "checked": {
            "managers": checked_managers,
            "tickers": checked_tickers,
            "external_provider": external_provider,
        },
        "error_count": error_count,
        "warn_count": warn_count,
        "issues": [i.as_dict() for i in issues],
    }


def report_to_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    checked = report.get("checked", {})
    lines.append(
        f"validated_managers={len(checked.get('managers', []))} "
        f"validated_tickers={len(checked.get('tickers', []))} "
        f"errors={report.get('error_count', 0)} warnings={report.get('warn_count', 0)}"
    )
    for issue in report.get("issues", []):
        lines.append(
            f"[{issue['severity'].upper()}] {issue['scope']} {issue['key']} {issue['metric']} "
            f"expected={issue['expected']} actual={issue['actual']} note={issue.get('note', '')}"
        )
    return "\n".join(lines)


def report_to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
