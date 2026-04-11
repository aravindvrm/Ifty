from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


def _table_exists(db: Session, table_name: str) -> bool:
    dialect = str(
        getattr(getattr(db, "bind", None), "dialect", None).name if getattr(db, "bind", None) else ""
    ).lower()
    if dialect.startswith("postgres"):
        exists = db.execute(
            text("SELECT to_regclass(:relname) IS NOT NULL"),
            {"relname": f"public.{table_name}"},
        ).scalar()
        return bool(exists)
    row = db.execute(
        text(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return bool(row)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def _build_quarter_series(db: Session, security_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not security_ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT security_id, report_date, total_value_usd, holders_count
            FROM agg_security_quarter
            WHERE security_id IN :security_ids
            ORDER BY security_id ASC, report_date ASC
            """
        ).bindparams(bindparam("security_ids", expanding=True)),
        {"security_ids": sorted(set(security_ids))},
    ).mappings().all()
    out: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        sid = int(row["security_id"])
        out.setdefault(sid, []).append(
            {
                "report_date": str(row["report_date"]),
                "total_value_usd": float(row["total_value_usd"] or 0.0),
                "holders_count": int(row["holders_count"] or 0),
            }
        )
    return out


def _follow_through_delta(
    series: list[dict[str, Any]],
    event_date: str,
) -> tuple[float, float] | None:
    if len(series) < 2:
        return None
    curr_idx = -1
    for idx, row in enumerate(series):
        if str(row["report_date"]) <= event_date:
            curr_idx = idx
    if curr_idx < 0 or curr_idx + 1 >= len(series):
        return None
    curr = series[curr_idx]
    nxt = series[curr_idx + 1]
    delta_value = float(nxt["total_value_usd"]) - float(curr["total_value_usd"])
    delta_holders = float(nxt["holders_count"]) - float(curr["holders_count"])
    return (delta_value, delta_holders)


def _init_bucket(
    *,
    signal_id: str,
    label: str,
    direction: str,
    description: str,
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "label": label,
        "direction": direction,
        "description": description,
        "sample_n": 0,
        "hits": 0,
        "misses": 0,
        "median_follow_through_value_usd": None,
        "median_abs_follow_through_value_usd": None,
        "median_follow_through_holders": None,
        "_follow_values": [],
        "_follow_abs_values": [],
        "_follow_holders": [],
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    sample_n = int(bucket.get("sample_n") or 0)
    hits = int(bucket.get("hits") or 0)
    misses = int(bucket.get("misses") or 0)
    follow_values = [float(x) for x in bucket.pop("_follow_values", [])]
    follow_abs_values = [float(x) for x in bucket.pop("_follow_abs_values", [])]
    follow_holders = [float(x) for x in bucket.pop("_follow_holders", [])]
    hit_rate = (100.0 * hits / sample_n) if sample_n > 0 else None
    bucket["hit_rate_pct"] = round(hit_rate, 1) if hit_rate is not None else None
    bucket["median_follow_through_value_usd"] = _median(follow_values)
    bucket["median_abs_follow_through_value_usd"] = _median(follow_abs_values)
    bucket["median_follow_through_holders"] = _median(follow_holders)
    bucket["misses"] = misses
    return bucket


def compute_signal_scorecards(
    db: Session,
    *,
    days: int = 365,
    min_samples: int = 5,
) -> dict[str, Any]:
    if not _table_exists(db=db, table_name="agg_security_quarter"):
        return {
            "window_days": int(days),
            "generated_at": datetime.now(UTC).isoformat(),
            "rows": [],
            "warning": "agg_security_quarter table missing",
        }

    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=max(1, int(days)))
    start_date_iso = start_date.isoformat()
    end_date_iso = end_date.isoformat()

    bo_rows = db.execute(
        text(
            """
            SELECT
              bo_event_id,
              security_id,
              report_date,
              event_type
            FROM beneficial_ownership_events
            WHERE security_id IS NOT NULL
              AND report_date >= :start_date
              AND report_date <= :end_date
              AND event_type IN ('NEW_5PCT', 'AMENDMENT_UP', 'AMENDMENT_DOWN', 'EXIT_5PCT')
            ORDER BY report_date DESC, bo_event_id DESC
            """
        ),
        {"start_date": start_date_iso, "end_date": end_date_iso},
    ).mappings().all()

    insider_rows: list[dict[str, Any]] = []
    if _table_exists(db=db, table_name="insider_transactions"):
        insider_rows = [
            dict(row)
            for row in db.execute(
                text(
                    """
                    WITH grouped AS (
                      SELECT
                        security_id,
                        transaction_date,
                        UPPER(COALESCE(signal_type, 'OTHER')) AS signal_type,
                        COUNT(*) AS tx_count,
                        COUNT(
                          DISTINCT CASE
                            WHEN COALESCE(reporting_owner_cik, '') <> '' THEN reporting_owner_cik
                            ELSE COALESCE(reporting_owner_name, '')
                          END
                        ) AS distinct_insiders
                      FROM insider_transactions
                      WHERE security_id IS NOT NULL
                        AND transaction_date >= :start_date
                        AND transaction_date <= :end_date
                        AND UPPER(COALESCE(signal_type, '')) IN ('OPEN_MARKET_BUY', 'OPEN_MARKET_SELL')
                      GROUP BY security_id, transaction_date, UPPER(COALESCE(signal_type, 'OTHER'))
                    )
                    SELECT security_id, transaction_date, signal_type, tx_count, distinct_insiders
                    FROM grouped
                    WHERE distinct_insiders >= 2
                    ORDER BY transaction_date DESC, tx_count DESC
                    """
                ),
                {"start_date": start_date_iso, "end_date": end_date_iso},
            ).mappings().all()
        ]

    security_ids = {int(row["security_id"]) for row in bo_rows if row.get("security_id") is not None}
    security_ids.update(
        int(row["security_id"])
        for row in insider_rows
        if row.get("security_id") is not None
    )
    quarter_series = _build_quarter_series(db, list(security_ids))

    buckets: dict[str, dict[str, Any]] = {
        "13DG_NEW_5PCT": _init_bucket(
            signal_id="13DG_NEW_5PCT",
            label="13D/G New 5% Stakes",
            direction="BULLISH",
            description="NEW_5PCT beneficial ownership events; hit means next-quarter institutional value rose.",
        ),
        "13DG_AMENDMENT_UP": _init_bucket(
            signal_id="13DG_AMENDMENT_UP",
            label="13D/G Amendment Up",
            direction="BULLISH",
            description="AMENDMENT_UP events; hit means next-quarter institutional value rose.",
        ),
        "13DG_AMENDMENT_DOWN": _init_bucket(
            signal_id="13DG_AMENDMENT_DOWN",
            label="13D/G Amendment Down",
            direction="BEARISH",
            description="AMENDMENT_DOWN events; hit means next-quarter institutional value fell.",
        ),
        "13DG_EXIT_5PCT": _init_bucket(
            signal_id="13DG_EXIT_5PCT",
            label="13D/G Exit < 5%",
            direction="BEARISH",
            description="EXIT_5PCT events; hit means next-quarter institutional value fell.",
        ),
        "INSIDER_CLUSTER_BUY": _init_bucket(
            signal_id="INSIDER_CLUSTER_BUY",
            label="Insider Cluster Buy",
            direction="BULLISH",
            description=">=2 distinct insiders buying on a day; hit means next-quarter institutional value rose.",
        ),
        "INSIDER_CLUSTER_SELL": _init_bucket(
            signal_id="INSIDER_CLUSTER_SELL",
            label="Insider Cluster Sell",
            direction="BEARISH",
            description=">=2 distinct insiders selling on a day; hit means next-quarter institutional value fell.",
        ),
    }

    bo_map = {
        "NEW_5PCT": ("13DG_NEW_5PCT", 1),
        "AMENDMENT_UP": ("13DG_AMENDMENT_UP", 1),
        "AMENDMENT_DOWN": ("13DG_AMENDMENT_DOWN", -1),
        "EXIT_5PCT": ("13DG_EXIT_5PCT", -1),
    }
    for row in bo_rows:
        event_type = str(row.get("event_type") or "").upper()
        signal_info = bo_map.get(event_type)
        if not signal_info:
            continue
        signal_id, direction = signal_info
        security_id = int(row["security_id"])
        series = quarter_series.get(security_id) or []
        delta = _follow_through_delta(series, str(row.get("report_date") or ""))
        if delta is None:
            continue
        delta_value, delta_holders = delta
        bucket = buckets[signal_id]
        bucket["sample_n"] = int(bucket["sample_n"]) + 1
        if direction * delta_value > 0:
            bucket["hits"] = int(bucket["hits"]) + 1
        else:
            bucket["misses"] = int(bucket["misses"]) + 1
        bucket["_follow_values"].append(delta_value)
        bucket["_follow_abs_values"].append(abs(delta_value))
        bucket["_follow_holders"].append(delta_holders)

    insider_map = {
        "OPEN_MARKET_BUY": ("INSIDER_CLUSTER_BUY", 1),
        "OPEN_MARKET_SELL": ("INSIDER_CLUSTER_SELL", -1),
    }
    for row in insider_rows:
        signal_type = str(row.get("signal_type") or "").upper()
        signal_info = insider_map.get(signal_type)
        if not signal_info:
            continue
        signal_id, direction = signal_info
        security_id = int(row["security_id"])
        series = quarter_series.get(security_id) or []
        delta = _follow_through_delta(series, str(row.get("transaction_date") or ""))
        if delta is None:
            continue
        delta_value, delta_holders = delta
        bucket = buckets[signal_id]
        bucket["sample_n"] = int(bucket["sample_n"]) + 1
        if direction * delta_value > 0:
            bucket["hits"] = int(bucket["hits"]) + 1
        else:
            bucket["misses"] = int(bucket["misses"]) + 1
        bucket["_follow_values"].append(delta_value)
        bucket["_follow_abs_values"].append(abs(delta_value))
        bucket["_follow_holders"].append(delta_holders)

    rows: list[dict[str, Any]] = []
    for key in [
        "13DG_NEW_5PCT",
        "13DG_AMENDMENT_UP",
        "13DG_AMENDMENT_DOWN",
        "13DG_EXIT_5PCT",
        "INSIDER_CLUSTER_BUY",
        "INSIDER_CLUSTER_SELL",
    ]:
        bucket = _finalize_bucket(buckets[key])
        bucket["insufficient_samples"] = int(bucket.get("sample_n") or 0) < max(1, int(min_samples))
        rows.append(bucket)

    return {
        "window_days": int(days),
        "start_date": start_date_iso,
        "end_date": end_date_iso,
        "generated_at": datetime.now(UTC).isoformat(),
        "rows": rows,
    }

