from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes import _value_to_usd_multiplier


def _safe_int(value: Any, default: int, min_v: int, max_v: int) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        out = default
    return max(min_v, min(max_v, out))


class AiReadOnlyTools:
    def __init__(self, db: Session):
        self.db = db
        self._value_to_usd_multiplier = _value_to_usd_multiplier(db=db)

    @property
    def specs(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_securities",
                    "description": "Find securities by ticker or name fragment.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit_n": {"type": "integer", "minimum": 1, "maximum": 25},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_institutions",
                    "description": "Find institutions by name, CIK, or manager id.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit_n": {"type": "integer", "minimum": 1, "maximum": 25},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "security_snapshot",
                    "description": "Get latest-quarter snapshot for a security ticker.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "holders_limit": {"type": "integer", "minimum": 1, "maximum": 25},
                        },
                        "required": ["ticker"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "institution_snapshot",
                    "description": "Get latest-quarter snapshot for an institution.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "manager_key": {"type": "string"},
                            "positions_limit": {"type": "integer", "minimum": 1, "maximum": 25},
                        },
                        "required": ["manager_key"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "market_pulse",
                    "description": "Get latest market-wide flow and breadth summary.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "recent_13dg_events",
                    "description": "Get recent mapped 13D/G events for the feed.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days": {"type": "integer", "minimum": 1, "maximum": 365},
                            "limit_n": {"type": "integer", "minimum": 1, "maximum": 50},
                        },
                    },
                },
            },
        ]

    def execute(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "search_securities":
            return self.search_securities(query=str(args.get("query") or ""), limit_n=args.get("limit_n"))
        if tool_name == "search_institutions":
            return self.search_institutions(query=str(args.get("query") or ""), limit_n=args.get("limit_n"))
        if tool_name == "security_snapshot":
            return self.security_snapshot(
                ticker=str(args.get("ticker") or ""),
                holders_limit=args.get("holders_limit"),
            )
        if tool_name == "institution_snapshot":
            return self.institution_snapshot(
                manager_key=str(args.get("manager_key") or ""),
                positions_limit=args.get("positions_limit"),
            )
        if tool_name == "market_pulse":
            return self.market_pulse()
        if tool_name == "recent_13dg_events":
            return self.recent_13dg_events(days=args.get("days"), limit_n=args.get("limit_n"))
        return {"ok": False, "error": f"Unknown tool '{tool_name}'"}

    def search_securities(self, query: str, limit_n: Any = 10) -> dict[str, Any]:
        q = query.strip()
        if not q:
            return {"ok": False, "error": "query is required"}

        limit = _safe_int(limit_n, default=10, min_v=1, max_v=25)
        q_norm = q.upper()
        rows = self.db.execute(
            text(
                """
                SELECT
                  s.security_id,
                  COALESCE(si.id_value, '') AS ticker,
                  COALESCE(s.security_name, i.issuer_name, '') AS security_name,
                  COALESCE(i.issuer_name, '') AS issuer_name
                FROM security_identifiers si
                JOIN securities s ON s.security_id = si.security_id
                LEFT JOIN issuers i ON i.issuer_id = s.issuer_id
                WHERE si.id_type = 'TICKER'
                  AND (
                    UPPER(si.id_value) LIKE :q_like
                    OR UPPER(COALESCE(s.security_name, '')) LIKE :q_like
                    OR UPPER(COALESCE(i.issuer_name, '')) LIKE :q_like
                  )
                  AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
                  AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                ORDER BY
                  CASE WHEN UPPER(si.id_value) = :q_exact THEN 0 ELSE 1 END,
                  si.id_value ASC
                LIMIT :limit_n
                """
            ),
            {"q_like": f"%{q_norm}%", "q_exact": q_norm, "limit_n": limit},
        ).mappings().all()

        return {"ok": True, "query": q, "rows": [dict(x) for x in rows]}

    def search_institutions(self, query: str, limit_n: Any = 10) -> dict[str, Any]:
        q = query.strip()
        if not q:
            return {"ok": False, "error": "query is required"}

        limit = _safe_int(limit_n, default=10, min_v=1, max_v=25)
        q_norm = q.upper()
        q_digits = "".join(ch for ch in q if ch.isdigit())
        rows = self.db.execute(
            text(
                """
                SELECT
                  m.manager_id,
                  m.cik,
                  m.manager_name
                FROM managers m
                WHERE UPPER(m.manager_name) LIKE :q_like
                   OR (:q_digits_like <> '' AND COALESCE(m.cik, '') LIKE :q_digits_like)
                   OR CAST(m.manager_id AS TEXT) = :q_raw
                ORDER BY
                  CASE WHEN UPPER(m.manager_name) = :q_exact THEN 0 ELSE 1 END,
                  m.manager_name ASC
                LIMIT :limit_n
                """
            ),
            {
                "q_like": f"%{q_norm}%",
                "q_digits_like": (f"%{q_digits}%" if q_digits else ""),
                "q_raw": q,
                "q_exact": q_norm,
                "limit_n": limit,
            },
        ).mappings().all()

        return {"ok": True, "query": q, "rows": [dict(x) for x in rows]}

    def security_snapshot(self, ticker: str, holders_limit: Any = 10) -> dict[str, Any]:
        t = ticker.strip().upper()
        if not t:
            return {"ok": False, "error": "ticker is required"}

        limit = _safe_int(holders_limit, default=10, min_v=1, max_v=25)

        sec = self.db.execute(
            text(
                """
                SELECT
                  s.security_id,
                  COALESCE(si.id_value, '') AS ticker,
                  COALESCE(s.security_name, i.issuer_name, '') AS security_name
                FROM security_identifiers si
                JOIN securities s ON s.security_id = si.security_id
                LEFT JOIN issuers i ON i.issuer_id = s.issuer_id
                WHERE si.id_type = 'TICKER'
                  AND UPPER(si.id_value) = :ticker
                  AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
                ORDER BY CASE WHEN si.valid_to IS NULL THEN 0 ELSE 1 END, si.valid_from DESC
                LIMIT 1
                """
            ),
            {"ticker": t},
        ).mappings().first()
        if not sec:
            return {"ok": False, "error": f"No security found for ticker '{t}'"}

        security_id = int(sec["security_id"])
        latest = self.db.execute(
            text(
                """
                SELECT report_date, holders_count, total_shares, total_value_usd, top10_pct
                FROM agg_security_quarter
                WHERE security_id = :security_id
                ORDER BY report_date DESC
                LIMIT 1
                """
            ),
            {"security_id": security_id},
        ).mappings().first()
        if not latest:
            return {
                "ok": True,
                "security_id": security_id,
                "ticker": sec["ticker"],
                "security_name": sec["security_name"],
                "latest_quarter": None,
                "top_holders": [],
            }

        latest_q = str(latest["report_date"])
        prev_q = self.db.execute(
            text(
                """
                SELECT report_date
                FROM agg_security_quarter
                WHERE security_id = :security_id
                  AND report_date < :latest_q
                ORDER BY report_date DESC
                LIMIT 1
                """
            ),
            {"security_id": security_id, "latest_q": latest_q},
        ).scalar()

        activity = {
            "new": 0,
            "increased": 0,
            "decreased": 0,
            "sold_out": 0,
        }
        qoq_net_change_shares = 0.0
        if prev_q:
            rows = self.db.execute(
                text(
                    """
                    WITH curr AS (
                      SELECT manager_id, SUM(COALESCE(shares, 0)) AS shares
                      FROM holdings_13f
                      WHERE security_id = :security_id
                        AND report_date = :latest_q
                        AND option_type IS NULL
                        AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                      GROUP BY manager_id
                    ),
                    prev AS (
                      SELECT manager_id, SUM(COALESCE(shares, 0)) AS shares
                      FROM holdings_13f
                      WHERE security_id = :security_id
                        AND report_date = :prev_q
                        AND option_type IS NULL
                        AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                      GROUP BY manager_id
                    ),
                    joined AS (
                      SELECT
                        c.manager_id AS manager_id,
                        COALESCE(c.shares, 0) AS curr_shares,
                        COALESCE(p.shares, 0) AS prev_shares
                      FROM curr c
                      LEFT JOIN prev p ON p.manager_id = c.manager_id
                      UNION ALL
                      SELECT
                        p.manager_id AS manager_id,
                        0 AS curr_shares,
                        COALESCE(p.shares, 0) AS prev_shares
                      FROM prev p
                      LEFT JOIN curr c ON c.manager_id = p.manager_id
                      WHERE c.manager_id IS NULL
                    )
                    SELECT manager_id, curr_shares, prev_shares, (curr_shares - prev_shares) AS delta_shares
                    FROM joined
                    """
                ),
                {"security_id": security_id, "latest_q": latest_q, "prev_q": str(prev_q)},
            ).mappings().all()
            for row in rows:
                curr_shares = float(row["curr_shares"] or 0.0)
                prev_shares = float(row["prev_shares"] or 0.0)
                delta = float(row["delta_shares"] or 0.0)
                qoq_net_change_shares += delta
                if curr_shares > 0 and prev_shares <= 0:
                    activity["new"] += 1
                elif curr_shares <= 0 and prev_shares > 0:
                    activity["sold_out"] += 1
                elif delta > 0:
                    activity["increased"] += 1
                elif delta < 0:
                    activity["decreased"] += 1

        top_rows = self.db.execute(
            text(
                """
                SELECT
                  h.manager_id,
                  m.manager_name,
                  SUM(COALESCE(h.shares, 0)) AS shares,
                  SUM(COALESCE(h.value_usd_thousands, 0)) AS value_raw
                FROM holdings_13f h
                JOIN managers m ON m.manager_id = h.manager_id
                WHERE h.security_id = :security_id
                  AND h.report_date = :latest_q
                  AND h.option_type IS NULL
                  AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                GROUP BY h.manager_id, m.manager_name
                ORDER BY shares DESC
                LIMIT :limit_n
                """
            ),
            {"security_id": security_id, "latest_q": latest_q, "limit_n": limit},
        ).mappings().all()

        top_holders = []
        for row in top_rows:
            top_holders.append(
                {
                    "manager_id": int(row["manager_id"]),
                    "manager_name": row["manager_name"],
                    "shares": float(row["shares"] or 0.0),
                    "value_usd": float(row["value_raw"] or 0.0) * self._value_to_usd_multiplier,
                }
            )

        return {
            "ok": True,
            "security_id": security_id,
            "ticker": sec["ticker"],
            "security_name": sec["security_name"],
            "latest_quarter": latest_q,
            "ownership_summary": {
                "holders_count": int(latest["holders_count"] or 0),
                "total_shares": float(latest["total_shares"] or 0.0),
                "total_value_usd": float(latest["total_value_usd"] or 0.0)
                * (self._value_to_usd_multiplier / 1000.0),
                "top10_concentration_pct": float(latest["top10_pct"] or 0.0),
                "qoq_net_change_shares": qoq_net_change_shares,
            },
            "activity_breakdown": activity,
            "top_holders": top_holders,
        }

    def institution_snapshot(self, manager_key: str, positions_limit: Any = 10) -> dict[str, Any]:
        key = manager_key.strip()
        if not key:
            return {"ok": False, "error": "manager_key is required"}

        limit = _safe_int(positions_limit, default=10, min_v=1, max_v=25)

        if key.isdigit():
            manager_id = int(key)
            manager = self.db.execute(
                text(
                    """
                    SELECT manager_id, cik, manager_name
                    FROM managers
                    WHERE manager_id = :manager_id OR cik = :cik
                    LIMIT 1
                    """
                ),
                {"manager_id": manager_id, "cik": key},
            ).mappings().first()
        else:
            manager = self.db.execute(
                text(
                    """
                    SELECT manager_id, cik, manager_name
                    FROM managers
                    WHERE UPPER(manager_name) = UPPER(:key)
                       OR UPPER(manager_name) LIKE UPPER(:name_like)
                    ORDER BY CASE WHEN UPPER(manager_name) = UPPER(:key) THEN 0 ELSE 1 END, manager_name
                    LIMIT 1
                    """
                ),
                {"key": key, "name_like": f"%{key}%"},
            ).mappings().first()

        if not manager:
            return {"ok": False, "error": f"No institution found for '{key}'"}

        manager_id = int(manager["manager_id"])
        latest = self.db.execute(
            text(
                """
                SELECT
                  report_date,
                  positions_count,
                  total_value_usd,
                  top10_value_pct,
                  turnover_ratio,
                  new_positions_count,
                  exited_positions_count
                FROM agg_manager_quarter
                WHERE manager_id = :manager_id
                ORDER BY report_date DESC
                LIMIT 1
                """
            ),
            {"manager_id": manager_id},
        ).mappings().first()

        latest_q = str(latest["report_date"]) if latest and latest.get("report_date") else None
        top_positions = []
        if latest_q:
            top_rows = self.db.execute(
                text(
                    """
                    SELECT
                      h.security_id,
                      SUM(COALESCE(h.shares, 0)) AS shares,
                      SUM(COALESCE(h.value_usd_thousands, 0)) AS value_raw,
                      COALESCE(s.security_name, '') AS security_name,
                      (
                        SELECT si.id_value
                        FROM security_identifiers si
                        WHERE si.security_id = h.security_id
                          AND si.id_type = 'TICKER'
                          AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                        ORDER BY si.valid_from DESC
                        LIMIT 1
                      ) AS ticker
                    FROM holdings_13f h
                    LEFT JOIN securities s ON s.security_id = h.security_id
                    WHERE h.manager_id = :manager_id
                      AND h.report_date = :latest_q
                      AND h.security_id IS NOT NULL
                      AND h.option_type IS NULL
                      AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                      AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
                    GROUP BY h.security_id, s.security_name
                    ORDER BY value_raw DESC
                    LIMIT :limit_n
                    """
                ),
                {"manager_id": manager_id, "latest_q": latest_q, "limit_n": limit},
            ).mappings().all()

            for row in top_rows:
                top_positions.append(
                    {
                        "security_id": int(row["security_id"]),
                        "ticker": str(row.get("ticker") or "").upper() or None,
                        "security_name": row["security_name"],
                        "shares": float(row["shares"] or 0.0),
                        "value_usd": float(row["value_raw"] or 0.0) * self._value_to_usd_multiplier,
                    }
                )

        return {
            "ok": True,
            "manager": dict(manager),
            "latest_quarter": latest_q,
            "metrics": {
                "positions_count": int((latest or {}).get("positions_count", 0) or 0),
                "total_value_usd": float((latest or {}).get("total_value_usd", 0.0) or 0.0)
                * (self._value_to_usd_multiplier / 1000.0),
                "top10_concentration_pct": float((latest or {}).get("top10_value_pct", 0.0) or 0.0),
                "turnover_ratio": (None if latest is None else float(latest.get("turnover_ratio") or 0.0)),
                "new_positions_count": int((latest or {}).get("new_positions_count", 0) or 0),
                "exited_positions_count": int((latest or {}).get("exited_positions_count", 0) or 0),
            },
            "top_positions": top_positions,
        }

    def market_pulse(self) -> dict[str, Any]:
        quarters = self.db.execute(
            text(
                """
                SELECT DISTINCT report_date
                FROM agg_security_quarter
                ORDER BY report_date DESC
                LIMIT 2
                """
            )
        ).all()
        quarter_values = [str(x[0]) for x in quarters if x and x[0] is not None]
        if len(quarter_values) < 2:
            return {"ok": True, "latest_quarter": quarter_values[0] if quarter_values else None, "pulse": {}}

        latest_q = quarter_values[0]
        prev_q = quarter_values[1]
        value_scale = self._value_to_usd_multiplier / 1000.0

        row = self.db.execute(
            text(
                """
                WITH flow AS (
                  SELECT
                    (COALESCE(c.total_shares, 0) - COALESCE(p.total_shares, 0)) AS delta_shares,
                    (COALESCE(c.holders_count, 0) - COALESCE(p.holders_count, 0)) AS delta_holders,
                    (COALESCE(c.total_value_usd, 0) - COALESCE(p.total_value_usd, 0)) AS delta_value_usd
                  FROM agg_security_quarter c
                  JOIN securities s ON s.security_id = c.security_id
                  LEFT JOIN agg_security_quarter p
                    ON p.security_id = c.security_id
                   AND p.report_date = :prev_q
                  WHERE c.report_date = :latest_q
                    AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
                )
                SELECT
                  COUNT(*) AS universe_count,
                  COALESCE(SUM(CASE WHEN delta_shares > 0 THEN 1 ELSE 0 END), 0) AS accum_count,
                  COALESCE(SUM(CASE WHEN delta_shares < 0 THEN 1 ELSE 0 END), 0) AS dist_count,
                  COALESCE(SUM(CASE WHEN delta_holders > 0 THEN delta_holders ELSE 0 END), 0) AS holders_added,
                  COALESCE(SUM(CASE WHEN delta_holders < 0 THEN -delta_holders ELSE 0 END), 0) AS holders_trimmed,
                  COALESCE(SUM(delta_value_usd), 0) AS net_value_change_usd
                FROM flow
                """
            ),
            {"latest_q": latest_q, "prev_q": prev_q},
        ).mappings().first() or {}

        universe_count = int(row.get("universe_count", 0) or 0)
        accum_count = int(row.get("accum_count", 0) or 0)
        dist_count = int(row.get("dist_count", 0) or 0)
        holders_added = int(row.get("holders_added", 0) or 0)
        holders_trimmed = int(row.get("holders_trimmed", 0) or 0)

        return {
            "ok": True,
            "latest_quarter": latest_q,
            "previous_quarter": prev_q,
            "pulse": {
                "universe_count": universe_count,
                "accum_count": accum_count,
                "dist_count": dist_count,
                "breadth_accum_pct": (accum_count / universe_count) if universe_count > 0 else 0.0,
                "breadth_dist_pct": (dist_count / universe_count) if universe_count > 0 else 0.0,
                "holders_added": holders_added,
                "holders_trimmed": holders_trimmed,
                "participation_increase_pct": (
                    holders_added / (holders_added + holders_trimmed)
                    if (holders_added + holders_trimmed) > 0
                    else 0.0
                ),
                "net_value_change_usd": float(row.get("net_value_change_usd", 0.0) or 0.0) * value_scale,
            },
        }

    def recent_13dg_events(self, days: Any = 30, limit_n: Any = 20) -> dict[str, Any]:
        days_int = _safe_int(days, default=30, min_v=1, max_v=365)
        limit = _safe_int(limit_n, default=20, min_v=1, max_v=50)
        rows = self.db.execute(
            text(
                """
                SELECT
                  b.report_date,
                  b.event_type,
                  b.percent_beneficial_owned,
                  b.shares_beneficial_owned,
                  COALESCE(m.manager_name, '') AS manager_name,
                  COALESCE(s.security_name, b.issuer_name_raw, '') AS security_name,
                  COALESCE(
                    (
                      SELECT si.id_value
                      FROM security_identifiers si
                      WHERE si.security_id = b.security_id
                        AND si.id_type = 'TICKER'
                        AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                      ORDER BY si.valid_from DESC
                      LIMIT 1
                    ),
                    b.ticker_raw,
                    ''
                  ) AS ticker,
                  f.form_type
                FROM beneficial_ownership_events b
                LEFT JOIN managers m ON m.manager_id = b.manager_id
                LEFT JOIN securities s ON s.security_id = b.security_id
                JOIN filings f ON f.filing_id = b.filing_id
                WHERE b.report_date >= date('now', :days_window)
                  AND b.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                  AND b.security_id IS NOT NULL
                  AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
                ORDER BY b.report_date DESC, b.bo_event_id DESC
                LIMIT :limit_n
                """
            ),
            {"days_window": f"-{days_int} day", "limit_n": limit},
        ).mappings().all()
        return {"ok": True, "days": days_int, "rows": [dict(x) for x in rows]}
