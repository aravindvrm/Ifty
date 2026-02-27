from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class UniverseRefreshSummary:
    as_of_report_date: str | None
    selected: int


class ManagerUniverseService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def refresh_top_n(self, top_n: int = 300) -> UniverseRefreshSummary:
        latest = self.db.execute(
            text(
                """
                SELECT MAX(report_date)
                FROM holdings_13f
                WHERE mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                """
            )
        ).scalar()
        if latest is None:
            self.db.execute(text("DELETE FROM manager_universe"))
            self.db.commit()
            return UniverseRefreshSummary(as_of_report_date=None, selected=0)

        ranked = self.db.execute(
            text(
                """
                WITH mgr AS (
                  SELECT manager_id, SUM(COALESCE(value_usd_thousands, 0)) * 1000.0 AS total_value_usd
                  FROM holdings_13f
                  WHERE report_date = :latest
                    AND mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                  GROUP BY manager_id
                )
                SELECT
                  manager_id,
                  total_value_usd,
                  ROW_NUMBER() OVER (ORDER BY total_value_usd DESC) AS rnk
                FROM mgr
                ORDER BY rnk
                LIMIT :top_n
                """
            ),
            {"latest": latest, "top_n": top_n},
        ).mappings().all()

        self.db.execute(text("DELETE FROM manager_universe"))
        for row in ranked:
            self.db.execute(
                text(
                    """
                    INSERT INTO manager_universe (
                      manager_id, rank, total_value_usd, as_of_report_date, source, is_active, updated_at
                    ) VALUES (
                      :manager_id, :rank, :total_value_usd, :as_of_report_date, 'HOLDINGS_13F', 1, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "manager_id": int(row["manager_id"]),
                    "rank": int(row["rnk"]),
                    "total_value_usd": float(row["total_value_usd"] or 0.0),
                    "as_of_report_date": latest,
                },
            )
        self.db.commit()
        return UniverseRefreshSummary(as_of_report_date=str(latest), selected=len(ranked))

    def get_active_ciks(self) -> list[str]:
        rows = self.db.execute(
            text(
                """
                SELECT m.cik
                FROM manager_universe u
                JOIN managers m ON m.manager_id = u.manager_id
                WHERE u.is_active = 1
                  AND m.cik IS NOT NULL
                ORDER BY u.rank
                """
            )
        ).all()
        return [str(x[0]) for x in rows if x[0]]
