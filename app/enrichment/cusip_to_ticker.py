from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.rate_limit import ProviderRateLimiter
from app.config import get_settings


def normalize_cusip(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = "".join(ch for ch in str(raw).upper() if ch.isalnum())
    if len(cleaned) < 8:
        return None
    if len(cleaned) >= 9:
        return cleaned[:9]
    return cleaned


@dataclass
class CusipMapping:
    cusip: str
    ticker: str | None
    figi: str | None
    name: str | None
    mic: str | None
    source: str
    confidence: float


@dataclass
class EnrichSummary:
    scanned: int = 0
    eligible: int = 0
    matched: int = 0
    inserted_xwalk: int = 0
    inserted_identifiers: int = 0


class CusipProvider(Protocol):
    source: str

    def map_cusips(self, cusips: list[str]) -> dict[str, CusipMapping]:
        ...


class NoopCusipProvider:
    source = "NOOP"

    def map_cusips(self, cusips: list[str]) -> dict[str, CusipMapping]:
        return {}


class OpenFigiCusipProvider:
    source = "OPENFIGI"

    def __init__(self, db: Session, limiter: ProviderRateLimiter) -> None:
        self.db = db
        self.limiter = limiter
        self.settings = get_settings()
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        if self.settings.openfigi_api_key:
            self.session.headers.update({"X-OPENFIGI-APIKEY": self.settings.openfigi_api_key})

    def _log(self, endpoint: str, status_code: int | None, ok: int, latency_ms: int) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO api_request_log (provider, endpoint, status_code, ok, latency_ms, cache_hit)
                VALUES ('OPENFIGI', :endpoint, :status_code, :ok, :latency_ms, 0)
                """
            ),
            {
                "endpoint": endpoint,
                "status_code": status_code,
                "ok": ok,
                "latency_ms": latency_ms,
            },
        )
        self.db.commit()

    def map_cusips(self, cusips: list[str]) -> dict[str, CusipMapping]:
        results: dict[str, CusipMapping] = {}
        if not cusips:
            return results

        batch = max(1, int(self.settings.openfigi_batch_size))
        for i in range(0, len(cusips), batch):
            chunk = cusips[i : i + batch]
            payload = [{"idType": "ID_CUSIP", "idValue": c} for c in chunk]
            self.limiter.acquire("OPENFIGI")
            start = time.perf_counter()
            status = None
            ok = 0
            try:
                resp = self.session.post(
                    self.settings.openfigi_base_url,
                    json=payload,
                    timeout=self.settings.request_timeout_seconds,
                )
                status = resp.status_code
                resp.raise_for_status()
                ok = 1
                body = resp.json()
                if not isinstance(body, list):
                    continue
                for idx, row in enumerate(body):
                    if idx >= len(chunk):
                        break
                    cusip = chunk[idx]
                    data = (row or {}).get("data") if isinstance(row, dict) else None
                    if not isinstance(data, list) or not data:
                        continue
                    first = data[0] if isinstance(data[0], dict) else {}
                    ticker = str(first.get("ticker") or "").strip().upper() or None
                    figi = str(first.get("figi") or "").strip() or None
                    name = str(first.get("name") or "").strip() or None
                    mic = str(first.get("exchCode") or "").strip().upper() or None
                    results[cusip] = CusipMapping(
                        cusip=cusip,
                        ticker=ticker,
                        figi=figi,
                        name=name,
                        mic=mic,
                        source=self.source,
                        confidence=0.85 if ticker else 0.4,
                    )
            finally:
                self._log(
                    endpoint=self.settings.openfigi_base_url,
                    status_code=status,
                    ok=ok,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                )
        return results


class CusipToTickerEnrichmentService:
    def __init__(self, db: Session, provider: CusipProvider) -> None:
        self.db = db
        self.provider = provider

    def _select_in_scope_cusips(
        self,
        recent_quarters: int,
        top_n: int,
        min_holders: int,
        min_total_value_usd: float,
        limit_cusips: int | None,
    ) -> list[str]:
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
            top_mgr AS (
              SELECT manager_id
              FROM manager_universe
              WHERE is_active = 1
              ORDER BY rank
              LIMIT :top_n
            ),
            scoped AS (
              SELECT
                UPPER(REPLACE(REPLACE(REPLACE(TRIM(h.cusip_raw), ' ', ''), '-', ''), '.', '')) AS cusip_norm,
                COUNT(DISTINCT h.manager_id) AS holders_count,
                SUM(COALESCE(h.value_usd_thousands, 0)) * 1000.0 AS total_value_usd
              FROM holdings_13f h
              WHERE h.cusip_raw IS NOT NULL
                AND TRIM(h.cusip_raw) <> ''
                AND h.report_date IN (SELECT report_date FROM recent_q)
                AND h.manager_id IN (SELECT manager_id FROM top_mgr)
              GROUP BY UPPER(REPLACE(REPLACE(REPLACE(TRIM(h.cusip_raw), ' ', ''), '-', ''), '.', ''))
            )
            SELECT cusip_norm
            FROM scoped
            WHERE holders_count >= :min_holders
               OR total_value_usd >= :min_total_value_usd
            ORDER BY total_value_usd DESC
        """
        params = {
            "recent_quarters": recent_quarters,
            "top_n": top_n,
            "min_holders": min_holders,
            "min_total_value_usd": min_total_value_usd,
        }
        if limit_cusips is not None:
            sql += " LIMIT :limit_cusips"
            params["limit_cusips"] = limit_cusips
        rows = self.db.execute(text(sql), params).all()
        out: list[str] = []
        for row in rows:
            c = normalize_cusip(row[0] if row else None)
            if c:
                out.append(c)
        return sorted(set(out))

    def _upsert_xwalk(self, mapping: CusipMapping) -> int:
        exists = self.db.execute(
            text("SELECT 1 FROM cusip_ticker_xwalk WHERE cusip = :cusip"),
            {"cusip": mapping.cusip},
        ).first()
        self.db.execute(
            text(
                """
                INSERT INTO cusip_ticker_xwalk (cusip, ticker, figi, name, mic, source, confidence, first_seen, last_seen)
                VALUES (:cusip, :ticker, :figi, :name, :mic, :source, :confidence, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(cusip) DO UPDATE SET
                  ticker = excluded.ticker,
                  figi = excluded.figi,
                  name = excluded.name,
                  mic = excluded.mic,
                  source = excluded.source,
                  confidence = excluded.confidence,
                  last_seen = CURRENT_TIMESTAMP
                """
            ),
            {
                "cusip": mapping.cusip,
                "ticker": mapping.ticker,
                "figi": mapping.figi,
                "name": mapping.name,
                "mic": mapping.mic,
                "source": mapping.source,
                "confidence": mapping.confidence,
            },
        )
        return 0 if exists else 1

    def _upsert_security_identifiers(self, source_tag: str) -> int:
        result = self.db.execute(
            text(
                """
                WITH map_src AS (
                  SELECT
                    x.cusip,
                    UPPER(x.ticker) AS ticker,
                    x.mic,
                    x.confidence
                  FROM cusip_ticker_xwalk x
                  WHERE x.ticker IS NOT NULL
                    AND x.source = :source_tag
                ),
                matches AS (
                  SELECT
                    si.security_id,
                    m.ticker,
                    COALESCE(m.mic, si.mic) AS mic,
                    m.confidence,
                    si.valid_from AS base_valid_from
                  FROM map_src m
                  JOIN security_identifiers si
                    ON si.id_type = 'CUSIP'
                   AND UPPER(REPLACE(REPLACE(REPLACE(si.id_value, ' ', ''), '-', ''), '.', '')) = m.cusip
                )
                INSERT INTO security_identifiers (
                  security_id, id_type, id_value, mic, valid_from, valid_to, source_system, confidence
                )
                SELECT
                  m.security_id,
                  'TICKER',
                  m.ticker,
                  m.mic,
                  m.base_valid_from,
                  NULL,
                  :source_system,
                  LEAST(0.9, GREATEST(0.4, m.confidence))
                FROM matches m
                WHERE NOT EXISTS (
                  SELECT 1
                  FROM security_identifiers t
                  WHERE t.security_id = m.security_id
                    AND t.id_type = 'TICKER'
                    AND UPPER(t.id_value) = m.ticker
                    AND COALESCE(t.mic, '') = COALESCE(m.mic, '')
                    AND t.valid_to IS NULL
                )
                """
            ),
            {"source_tag": source_tag, "source_system": f"CUSIP_XWALK_{source_tag}"},
        )
        return int(result.rowcount or 0)

    def enrich_in_scope(
        self,
        recent_quarters: int,
        top_n: int,
        min_holders: int,
        min_total_value_usd: float,
        limit_cusips: int | None,
    ) -> EnrichSummary:
        summary = EnrichSummary()
        cusips = self._select_in_scope_cusips(
            recent_quarters=recent_quarters,
            top_n=top_n,
            min_holders=min_holders,
            min_total_value_usd=min_total_value_usd,
            limit_cusips=limit_cusips,
        )
        summary.scanned = len(cusips)

        existing = {str(r[0]) for r in self.db.execute(text("SELECT cusip FROM cusip_ticker_xwalk")).all()} if cusips else set()
        to_enrich = [c for c in cusips if c not in existing]
        summary.eligible = len(to_enrich)

        mapped = self.provider.map_cusips(to_enrich)
        summary.matched = len(mapped)
        for c in to_enrich:
            m = mapped.get(c)
            if not m:
                m = CusipMapping(
                    cusip=c,
                    ticker=None,
                    figi=None,
                    name=None,
                    mic=None,
                    source=getattr(self.provider, "source", "UNKNOWN"),
                    confidence=0.0,
                )
            summary.inserted_xwalk += self._upsert_xwalk(m)

        summary.inserted_identifiers = self._upsert_security_identifiers(
            source_tag=getattr(self.provider, "source", "UNKNOWN")
        )
        self.db.commit()
        return summary
