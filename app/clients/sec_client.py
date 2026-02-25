from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.rate_limit import ProviderRateLimiter
from app.config import get_settings


def _clean_cik(cik: str) -> str:
    return "".join(ch for ch in cik if ch.isdigit())


def cik_10(cik: str) -> str:
    return _clean_cik(cik).zfill(10)


def cik_int(cik: str) -> str:
    return str(int(_clean_cik(cik)))


@dataclass
class SecClient:
    session: requests.Session
    limiter: ProviderRateLimiter
    db: Session

    def _request_json(self, url: str) -> Any:
        settings = get_settings()
        self.limiter.acquire("SEC")
        start = time.perf_counter()
        status_code = None
        ok = 0
        try:
            response = self.session.get(url, timeout=settings.request_timeout_seconds)
            status_code = response.status_code
            response.raise_for_status()
            ok = 1
            return response.json()
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            self.db.execute(
                text(
                    """
                    INSERT INTO api_request_log (provider, endpoint, status_code, ok, latency_ms, cache_hit)
                    VALUES ('SEC', :endpoint, :status_code, :ok, :latency_ms, 0)
                    """
                ),
                {
                    "endpoint": url,
                    "status_code": status_code,
                    "ok": ok,
                    "latency_ms": latency_ms,
                },
            )
            self.db.commit()

    def get_submissions(self, cik: str) -> dict[str, Any]:
        settings = get_settings()
        url = f"{settings.sec_base_url}/submissions/CIK{cik_10(cik)}.json"
        data = self._request_json(url)
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected SEC submissions response for CIK {cik}")
        return data

    def get_filing_index(self, cik: str, accession_no_dashless: str) -> dict[str, Any]:
        settings = get_settings()
        url = (
            f"{settings.sec_archives_base_url}/edgar/data/{cik_int(cik)}/"
            f"{accession_no_dashless}/index.json"
        )
        data = self._request_json(url)
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected filing index response for CIK {cik}")
        return data

    def get_company_tickers_exchange(self) -> dict[str, Any]:
        settings = get_settings()
        url = f"{settings.sec_www_base_url}/files/company_tickers_exchange.json"
        data = self._request_json(url)
        if not isinstance(data, dict):
            raise ValueError("Unexpected company_tickers_exchange response")
        return data

    def download_text(self, url: str) -> str:
        settings = get_settings()
        self.limiter.acquire("SEC")
        start = time.perf_counter()
        status_code = None
        ok = 0
        try:
            response = self.session.get(url, timeout=settings.request_timeout_seconds)
            status_code = response.status_code
            response.raise_for_status()
            ok = 1
            return response.text
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            self.db.execute(
                text(
                    """
                    INSERT INTO api_request_log (provider, endpoint, status_code, ok, latency_ms, cache_hit)
                    VALUES ('SEC', :endpoint, :status_code, :ok, :latency_ms, 0)
                    """
                ),
                {
                    "endpoint": url,
                    "status_code": status_code,
                    "ok": ok,
                    "latency_ms": latency_ms,
                },
            )
            self.db.commit()


def build_sec_http_session() -> requests.Session:
    settings = get_settings()
    if not settings.sec_user_agent.strip():
        raise ValueError("SEC_USER_AGENT is required. Example: 'Name email@example.com'")
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": settings.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
    )
    return session
