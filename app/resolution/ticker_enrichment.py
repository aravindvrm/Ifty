from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.sec_client import SecClient

SUFFIX_TOKENS = {
    "INC",
    "INCORPORATED",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "PLC",
    "LTD",
    "LIMITED",
    "HOLDINGS",
    "HOLDING",
    "GROUP",
    "SA",
    "NV",
}

EXCHANGE_TO_MIC = {
    "Nasdaq": "XNAS",
    "NYSE": "XNYS",
    "NYSE American": "XASE",
    "NYSE Arca": "ARCX",
    "NYSE MKT": "XASE",
    "OTC": "OTCM",
}


def _normalize_issuer_name(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9 ]+", " ", name.upper())
    parts = [p for p in value.split() if p and p not in SUFFIX_TOKENS]
    return " ".join(parts)


@dataclass
class TickerSyncSummary:
    scanned: int = 0
    matched: int = 0
    inserted: int = 0


class TickerEnrichmentService:
    def __init__(self, db: Session, sec_client: SecClient) -> None:
        self.db = db
        self.sec_client = sec_client

    def _load_sec_ticker_index(self) -> dict[str, list[dict]]:
        payload = self.sec_client.get_company_tickers_exchange()
        data = payload.get("data", [])
        index: dict[str, list[dict]] = {}
        if not isinstance(data, list):
            return index
        for row in data:
            if not isinstance(row, list) or len(row) < 4:
                continue
            # [cik, name, ticker, exchange]
            company_name = str(row[1] or "")
            ticker = str(row[2] or "").strip().upper()
            exchange = str(row[3] or "").strip()
            if not company_name or not ticker:
                continue
            norm = _normalize_issuer_name(company_name)
            index.setdefault(norm, []).append(
                {
                    "company_name": company_name,
                    "ticker": ticker,
                    "exchange": exchange,
                }
            )
        return index

    def sync_from_sec_company_tickers(
        self,
        limit: int | None = None,
        recent_quarters: int = 4,
        min_holders: int = 3,
        min_total_value_usd: float = 250_000_000.0,
        universe_only: bool = True,
    ) -> TickerSyncSummary:
        sec_index = self._load_sec_ticker_index()
        summary = TickerSyncSummary()

        sql = """
            WITH recent_q AS (
              SELECT report_date
              FROM (
                SELECT DISTINCT report_date
                FROM holdings_13f
                ORDER BY report_date DESC
                LIMIT :recent_quarters
              )
            ),
            base AS (
              SELECT
                h.security_id,
                COUNT(DISTINCT h.manager_id) AS holders_count,
                SUM(COALESCE(h.value_usd_thousands, 0)) * 1000.0 AS total_value_usd
              FROM holdings_13f h
              WHERE h.security_id IS NOT NULL
                AND h.mapping_status IN ('MAPPED', 'MAPPED_LOW_CONF')
                AND h.report_date IN (SELECT report_date FROM recent_q)
                AND (
                  :universe_only = 0
                  OR h.manager_id IN (SELECT manager_id FROM manager_universe WHERE is_active = 1)
                )
              GROUP BY h.security_id
              HAVING COUNT(DISTINCT h.manager_id) >= :min_holders
                 OR SUM(COALESCE(h.value_usd_thousands, 0)) * 1000.0 >= :min_total_value_usd
            )
            SELECT s.security_id, s.active_from, s.primary_mic, i.issuer_name
            FROM securities s
            JOIN issuers i ON i.issuer_id = s.issuer_id
            JOIN base b ON b.security_id = s.security_id
            WHERE NOT EXISTS (
              SELECT 1 FROM security_identifiers si
              WHERE si.security_id = s.security_id
                AND si.id_type = 'TICKER'
                AND si.valid_to IS NULL
            )
            ORDER BY s.security_id
        """
        if limit is not None:
            sql += " LIMIT :limit_n"
            rows = self.db.execute(
                text(sql),
                {
                    "limit_n": limit,
                    "recent_quarters": recent_quarters,
                    "min_holders": min_holders,
                    "min_total_value_usd": min_total_value_usd,
                    "universe_only": 1 if universe_only else 0,
                },
            ).mappings().all()
        else:
            rows = self.db.execute(
                text(sql),
                {
                    "recent_quarters": recent_quarters,
                    "min_holders": min_holders,
                    "min_total_value_usd": min_total_value_usd,
                    "universe_only": 1 if universe_only else 0,
                },
            ).mappings().all()

        for row in rows:
            summary.scanned += 1
            security_id = int(row["security_id"])
            issuer_name = str(row["issuer_name"] or "").strip()
            if not issuer_name:
                continue
            norm = _normalize_issuer_name(issuer_name)
            matches = sec_index.get(norm, [])
            if not matches:
                continue

            summary.matched += 1
            chosen = matches[0]
            ticker = chosen["ticker"]
            mic = row["primary_mic"] or EXCHANGE_TO_MIC.get(chosen["exchange"])
            valid_from = row["active_from"] or "2000-01-01"

            exists = self.db.execute(
                text(
                    """
                    SELECT 1
                    FROM security_identifiers
                    WHERE security_id = :security_id
                      AND id_type = 'TICKER'
                      AND UPPER(id_value) = :ticker
                      AND COALESCE(mic, '') = COALESCE(:mic, '')
                      AND valid_to IS NULL
                    LIMIT 1
                    """
                ),
                {"security_id": security_id, "ticker": ticker, "mic": mic},
            ).mappings().first()
            if exists:
                continue

            # `id_type,id_value` is globally unique, so skip if ticker is already claimed.
            ticker_claimed = self.db.execute(
                text(
                    """
                    SELECT 1
                    FROM security_identifiers
                    WHERE id_type = 'TICKER'
                      AND UPPER(id_value) = :ticker
                    LIMIT 1
                    """
                ),
                {"ticker": ticker},
            ).mappings().first()
            if ticker_claimed:
                continue

            self.db.execute(
                text(
                    """
                    INSERT INTO security_identifiers (
                      security_id, id_type, id_value, mic, valid_from, valid_to, source_system, confidence
                    ) VALUES (
                      :security_id, 'TICKER', :ticker, :mic, :valid_from, NULL, 'SEC_COMPANY_TICKERS', 0.7
                    )
                    """
                ),
                {
                    "security_id": security_id,
                    "ticker": ticker,
                    "mic": mic,
                    "valid_from": valid_from,
                },
            )
            summary.inserted += 1

        self.db.commit()
        return summary
