from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class AggregateRefreshSummary:
    security_rows: int
    manager_rows: int


class AggregateRefreshService:
    def __init__(self, db: Session) -> None:
        self.db = db
        bind = getattr(db, "bind", None)
        self._dialect = (bind.dialect.name if bind is not None else "").lower()

    def refresh_security_quarter(self) -> int:
        if self._dialect != "postgresql":
            self.db.execute(text("DELETE FROM agg_security_quarter"))
            rows = self.db.execute(
                text(
                    """
                    WITH base AS (
                      SELECT security_id, report_date, manager_id, SUM(COALESCE(shares, 0)) AS shares, SUM(COALESCE(value_usd_thousands, 0)) * 1000.0 AS value_usd
                      FROM holdings_13f
                      WHERE security_id IS NOT NULL
                        AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                      GROUP BY security_id, report_date, manager_id
                    ),
                    ranked AS (
                      SELECT
                        security_id,
                        report_date,
                        manager_id,
                        shares,
                        value_usd,
                        ROW_NUMBER() OVER (PARTITION BY security_id, report_date ORDER BY shares DESC) AS rn
                      FROM base
                    )
                    SELECT
                      security_id,
                      report_date,
                      COUNT(DISTINCT manager_id) AS holders_count,
                      SUM(shares) AS total_shares,
                      SUM(value_usd) AS total_value_usd,
                      SUM(CASE WHEN rn <= 10 THEN shares ELSE 0 END) AS top10_shares
                    FROM ranked
                    GROUP BY security_id, report_date
                    """
                )
            ).mappings().all()

            inserted = 0
            for row in rows:
                total_shares = float(row["total_shares"] or 0.0)
                top10_shares = float(row["top10_shares"] or 0.0)
                self.db.execute(
                    text(
                        """
                        INSERT INTO agg_security_quarter (
                          security_id, report_date, holders_count, total_shares, total_value_usd, top10_shares, top10_pct
                        ) VALUES (
                          :security_id, :report_date, :holders_count, :total_shares, :total_value_usd, :top10_shares, :top10_pct
                        )
                        """
                    ),
                    {
                        "security_id": int(row["security_id"]),
                        "report_date": row["report_date"],
                        "holders_count": int(row["holders_count"]),
                        "total_shares": total_shares,
                        "total_value_usd": float(row["total_value_usd"] or 0.0),
                        "top10_shares": top10_shares,
                        "top10_pct": (top10_shares / total_shares) if total_shares > 0 else 0.0,
                    },
                )
                inserted += 1
            self.db.commit()
            return inserted

        self.db.execute(text("DELETE FROM agg_security_quarter"))
        result = self.db.execute(
            text(
                """
                INSERT INTO agg_security_quarter (
                  security_id, report_date, holders_count, total_shares, total_value_usd, top10_shares, top10_pct
                )
                WITH base AS (
                  SELECT
                    security_id,
                    report_date,
                    manager_id,
                    SUM(COALESCE(shares, 0)) AS shares,
                    SUM(COALESCE(value_usd_thousands, 0)) * 1000.0 AS value_usd
                  FROM holdings_13f
                  WHERE security_id IS NOT NULL
                    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                  GROUP BY security_id, report_date, manager_id
                ),
                ranked AS (
                  SELECT
                    security_id,
                    report_date,
                    manager_id,
                    shares,
                    value_usd,
                    ROW_NUMBER() OVER (PARTITION BY security_id, report_date ORDER BY shares DESC) AS rn
                  FROM base
                ),
                summary AS (
                  SELECT
                    security_id,
                    report_date,
                    COUNT(DISTINCT manager_id) AS holders_count,
                    SUM(shares) AS total_shares,
                    SUM(value_usd) AS total_value_usd,
                    SUM(CASE WHEN rn <= 10 THEN shares ELSE 0 END) AS top10_shares
                  FROM ranked
                  GROUP BY security_id, report_date
                )
                SELECT
                  security_id,
                  report_date,
                  holders_count,
                  total_shares,
                  total_value_usd,
                  top10_shares,
                  CASE WHEN total_shares > 0 THEN top10_shares / total_shares ELSE 0 END AS top10_pct
                FROM summary
                """
            )
        )
        self.db.commit()
        return int(result.rowcount or 0)

    def refresh_manager_quarter(self) -> int:
        if self._dialect != "postgresql":
            self.db.execute(text("DELETE FROM agg_manager_quarter"))
            base_rows = self.db.execute(
                text(
                    """
                    SELECT manager_id, report_date
                    FROM holdings_13f
                    WHERE security_id IS NOT NULL
                      AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                    GROUP BY manager_id, report_date
                    ORDER BY manager_id, report_date
                    """
                )
            ).mappings().all()

            inserted = 0
            for row in base_rows:
                manager_id = int(row["manager_id"])
                report_date = row["report_date"]
                curr_positions = self.db.execute(
                    text(
                        """
                        SELECT security_id, SUM(COALESCE(value_usd_thousands, 0)) * 1000.0 AS value_usd
                        FROM holdings_13f
                        WHERE manager_id = :manager_id
                          AND report_date = :report_date
                          AND security_id IS NOT NULL
                          AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                        GROUP BY security_id
                        """
                    ),
                    {"manager_id": manager_id, "report_date": report_date},
                ).mappings().all()
                curr_map = {int(x["security_id"]): float(x["value_usd"] or 0.0) for x in curr_positions}
                total_value = sum(curr_map.values())
                top10_value = sum(sorted(curr_map.values(), reverse=True)[:10])

                prev_date = self.db.execute(
                    text(
                        """
                        SELECT MAX(report_date) AS prev_date
                        FROM holdings_13f
                        WHERE manager_id = :manager_id
                          AND report_date < :report_date
                          AND security_id IS NOT NULL
                          AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                        """
                    ),
                    {"manager_id": manager_id, "report_date": report_date},
                ).scalar()

                turnover_ratio = 0.0
                new_count = 0
                exited_count = 0
                if prev_date:
                    prev_positions = self.db.execute(
                        text(
                            """
                            SELECT security_id, SUM(COALESCE(value_usd_thousands, 0)) * 1000.0 AS value_usd
                            FROM holdings_13f
                            WHERE manager_id = :manager_id
                              AND report_date = :prev_date
                              AND security_id IS NOT NULL
                              AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                            GROUP BY security_id
                            """
                        ),
                        {"manager_id": manager_id, "prev_date": prev_date},
                    ).mappings().all()
                    prev_map = {int(x["security_id"]): float(x["value_usd"] or 0.0) for x in prev_positions}

                    all_secs = set(curr_map) | set(prev_map)
                    abs_delta_sum = sum(abs(curr_map.get(sec, 0.0) - prev_map.get(sec, 0.0)) for sec in all_secs)
                    avg_port = (sum(curr_map.values()) + sum(prev_map.values())) / 2
                    turnover_ratio = (abs_delta_sum / 2) / avg_port if avg_port > 0 else 0.0
                    new_count = len(set(curr_map) - set(prev_map))
                    exited_count = len(set(prev_map) - set(curr_map))

                self.db.execute(
                    text(
                        """
                        INSERT INTO agg_manager_quarter (
                          manager_id, report_date, positions_count, total_value_usd, top10_value_pct,
                          turnover_ratio, new_positions_count, exited_positions_count
                        ) VALUES (
                          :manager_id, :report_date, :positions_count, :total_value_usd, :top10_value_pct,
                          :turnover_ratio, :new_positions_count, :exited_positions_count
                        )
                        """
                    ),
                    {
                        "manager_id": manager_id,
                        "report_date": report_date,
                        "positions_count": len(curr_map),
                        "total_value_usd": total_value,
                        "top10_value_pct": (top10_value / total_value) if total_value > 0 else 0.0,
                        "turnover_ratio": turnover_ratio,
                        "new_positions_count": new_count,
                        "exited_positions_count": exited_count,
                    },
                )
                inserted += 1

            self.db.commit()
            return inserted

        self.db.execute(text("DELETE FROM agg_manager_quarter"))
        result = self.db.execute(
            text(
                """
                INSERT INTO agg_manager_quarter (
                  manager_id,
                  report_date,
                  positions_count,
                  total_value_usd,
                  top10_value_pct,
                  turnover_ratio,
                  new_positions_count,
                  exited_positions_count
                )
                WITH pos AS (
                  SELECT
                    manager_id,
                    report_date,
                    security_id,
                    SUM(COALESCE(value_usd_thousands, 0)) * 1000.0 AS value_usd
                  FROM holdings_13f
                  WHERE security_id IS NOT NULL
                    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                  GROUP BY manager_id, report_date, security_id
                ),
                ranked AS (
                  SELECT
                    manager_id,
                    report_date,
                    security_id,
                    value_usd,
                    ROW_NUMBER() OVER (PARTITION BY manager_id, report_date ORDER BY value_usd DESC) AS rn
                  FROM pos
                ),
                mgr AS (
                  SELECT
                    manager_id,
                    report_date,
                    COUNT(*) AS positions_count,
                    SUM(value_usd) AS total_value_usd,
                    SUM(CASE WHEN rn <= 10 THEN value_usd ELSE 0 END) AS top10_value
                  FROM ranked
                  GROUP BY manager_id, report_date
                ),
                mgr_prev AS (
                  SELECT
                    m.*,
                    LAG(report_date) OVER (PARTITION BY manager_id ORDER BY report_date) AS prev_date
                  FROM mgr m
                ),
                flow_raw AS (
                  SELECT
                    mp.manager_id,
                    mp.report_date,
                    c.security_id,
                    c.value_usd AS curr_value,
                    0::double precision AS prev_value,
                    1 AS has_curr,
                    0 AS has_prev
                  FROM mgr_prev mp
                  JOIN pos c
                    ON c.manager_id = mp.manager_id
                   AND c.report_date = mp.report_date
                  WHERE mp.prev_date IS NOT NULL
                  UNION ALL
                  SELECT
                    mp.manager_id,
                    mp.report_date,
                    p.security_id,
                    0::double precision AS curr_value,
                    p.value_usd AS prev_value,
                    0 AS has_curr,
                    1 AS has_prev
                  FROM mgr_prev mp
                  JOIN pos p
                    ON p.manager_id = mp.manager_id
                   AND p.report_date = mp.prev_date
                  WHERE mp.prev_date IS NOT NULL
                ),
                flow AS (
                  SELECT
                    manager_id,
                    report_date,
                    security_id,
                    SUM(curr_value) AS curr_value,
                    SUM(prev_value) AS prev_value,
                    MAX(has_curr) AS has_curr,
                    MAX(has_prev) AS has_prev
                  FROM flow_raw
                  GROUP BY manager_id, report_date, security_id
                ),
                turnover AS (
                  SELECT
                    manager_id,
                    report_date,
                    SUM(ABS(curr_value - prev_value)) AS abs_delta_sum,
                    SUM(CASE WHEN has_curr = 1 AND has_prev = 0 THEN 1 ELSE 0 END) AS new_positions_count,
                    SUM(CASE WHEN has_curr = 0 AND has_prev = 1 THEN 1 ELSE 0 END) AS exited_positions_count,
                    SUM(curr_value) AS curr_total,
                    SUM(prev_value) AS prev_total
                  FROM flow
                  GROUP BY manager_id, report_date
                )
                SELECT
                  m.manager_id,
                  m.report_date,
                  m.positions_count,
                  m.total_value_usd,
                  CASE WHEN m.total_value_usd > 0 THEN m.top10_value / m.total_value_usd ELSE 0 END AS top10_value_pct,
                  CASE
                    WHEN t.manager_id IS NULL THEN 0
                    WHEN ((t.curr_total + t.prev_total) / 2.0) > 0
                      THEN (t.abs_delta_sum / 2.0) / ((t.curr_total + t.prev_total) / 2.0)
                    ELSE 0
                  END AS turnover_ratio,
                  COALESCE(t.new_positions_count, 0) AS new_positions_count,
                  COALESCE(t.exited_positions_count, 0) AS exited_positions_count
                FROM mgr m
                LEFT JOIN turnover t
                  ON t.manager_id = m.manager_id
                 AND t.report_date = m.report_date
                """
            )
        )
        self.db.commit()
        return int(result.rowcount or 0)

    def refresh_all(self) -> AggregateRefreshSummary:
        prior_statement_timeout: str | None = None
        if self._dialect == "postgresql":
            prior_statement_timeout = str(self.db.execute(text("SHOW statement_timeout")).scalar() or "0")
            self.db.execute(text("SELECT set_config('statement_timeout', '0', false)"))
            self.db.commit()
        try:
            sec_rows = self.refresh_security_quarter()
            mgr_rows = self.refresh_manager_quarter()
            return AggregateRefreshSummary(security_rows=sec_rows, manager_rows=mgr_rows)
        finally:
            if self._dialect == "postgresql" and prior_statement_timeout is not None:
                self.db.execute(
                    text("SELECT set_config('statement_timeout', :timeout, false)"),
                    {"timeout": prior_statement_timeout},
                )
                self.db.commit()
