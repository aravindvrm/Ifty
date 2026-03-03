from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.clients.sec_client import SecClient
from app.config import get_settings
from app.ingest.sec_13dg import SUPPORTED_FORMS, normalize_13dg_form_type

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class DiscoverySummary:
    ciks: list[str]
    latest_filed_date_by_cik: dict[str, str]
    files_attempted: int
    files_scanned: int
    filings_matched: int
    mode: str


def _quarter_for_month(month: int) -> int:
    return ((month - 1) // 3) + 1


def _recent_quarters(n: int, today: date) -> list[tuple[int, int]]:
    q = _quarter_for_month(today.month)
    y = today.year
    result: list[tuple[int, int]] = []
    for _ in range(max(1, n)):
        result.append((y, q))
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    return result


def _recent_days(n: int, today: date) -> list[date]:
    return [today - timedelta(days=i) for i in range(max(1, n))]


def _normalize_idx_cik(raw: str) -> str | None:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    return digits.zfill(10)


def _normalize_idx_date(raw: str) -> str | None:
    value = (raw or "").strip()
    if not value or not _DATE_RE.match(value):
        return None
    return value


def _prev_quarter(year: int, quarter: int) -> tuple[int, int]:
    quarter -= 1
    if quarter <= 0:
        return year - 1, 4
    return year, quarter


def _parse_13dg_master_idx(text_data: str) -> list[tuple[str, str | None]]:
    rows: list[tuple[str, str | None]] = []
    for line in text_data.splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        cik_raw, _company, form_type_raw, filed_date_raw, _filename = parts[:5]
        form_type = normalize_13dg_form_type(form_type_raw)
        if form_type not in SUPPORTED_FORMS:
            continue
        cik = _normalize_idx_cik(cik_raw)
        if not cik:
            continue
        filed_date = _normalize_idx_date(filed_date_raw)
        rows.append((cik, filed_date))
    return rows


class Sec13DGIndexDiscoveryService:
    def __init__(self, sec_client: SecClient) -> None:
        self.sec_client = sec_client
        self.settings = get_settings()

    def discover(
        self,
        *,
        mode: str = "daily",
        days: int = 21,
        quarters: int = 6,
        max_ciks: int = 300,
        today: date | None = None,
    ) -> DiscoverySummary:
        normalized_mode = (mode or "daily").strip().lower()
        if normalized_mode not in {"none", "daily", "quarterly", "both"}:
            raise ValueError(f"Unsupported discovery mode: {mode}")
        if normalized_mode == "none":
            return DiscoverySummary(
                ciks=[],
                latest_filed_date_by_cik={},
                files_attempted=0,
                files_scanned=0,
                filings_matched=0,
                mode=normalized_mode,
            )

        now = today or date.today()
        scores: dict[str, float] = {}
        latest_filed_date_by_cik: dict[str, str] = {}
        files_attempted = 0
        files_scanned = 0
        filings_matched = 0

        def _consume_url(url: str, weight: float) -> bool:
            nonlocal files_attempted, files_scanned, filings_matched
            files_attempted += 1
            try:
                idx_text = self.sec_client.download_text(url)
            except Exception:
                return False
            files_scanned += 1
            rows = _parse_13dg_master_idx(idx_text)
            filings_matched += len(rows)
            for cik, filed_date in rows:
                scores[cik] = float(scores.get(cik, 0.0)) + float(weight)
                if not filed_date:
                    continue
                existing = latest_filed_date_by_cik.get(cik)
                if existing is None or filed_date > existing:
                    latest_filed_date_by_cik[cik] = filed_date
            return True

        if normalized_mode in {"daily", "both"}:
            day_target = max(1, int(days))
            day_success = 0
            day_attempt_cap = max(day_target * 10, 180)
            d = now
            attempts = 0
            while day_success < day_target and attempts < day_attempt_cap:
                q = _quarter_for_month(d.month)
                url = (
                    f"{self.settings.sec_archives_base_url}/edgar/daily-index/"
                    f"{d.year}/QTR{q}/master.{d.strftime('%Y%m%d')}.idx"
                )
                # Weight successful files from newest to oldest.
                weight = 2.0 + ((day_target - day_success) / day_target)
                if _consume_url(url=url, weight=weight):
                    day_success += 1
                attempts += 1
                d -= timedelta(days=1)

        if normalized_mode in {"quarterly", "both"}:
            quarter_target = max(1, int(quarters))
            quarter_success = 0
            quarter_attempt_cap = max(quarter_target * 6, 24)
            year = now.year
            quarter = _quarter_for_month(now.month)
            attempts = 0
            while quarter_success < quarter_target and attempts < quarter_attempt_cap:
                url = f"{self.settings.sec_archives_base_url}/edgar/full-index/{year}/QTR{quarter}/master.idx"
                weight = 1.0 + ((quarter_target - quarter_success) / quarter_target)
                if _consume_url(url=url, weight=weight):
                    quarter_success += 1
                attempts += 1
                year, quarter = _prev_quarter(year, quarter)

        ranked = sorted(
            scores.items(),
            key=lambda kv: (
                -kv[1],
                -(int(latest_filed_date_by_cik.get(kv[0], "0000-00-00").replace("-", "") or 0)),
                kv[0],
            ),
        )
        if max_ciks > 0:
            ranked = ranked[:max_ciks]
        selected = [cik for cik, _score in ranked]
        selected_latest = {cik: latest_filed_date_by_cik[cik] for cik in selected if cik in latest_filed_date_by_cik}
        return DiscoverySummary(
            ciks=selected,
            latest_filed_date_by_cik=selected_latest,
            files_attempted=files_attempted,
            files_scanned=files_scanned,
            filings_matched=filings_matched,
            mode=normalized_mode,
        )
