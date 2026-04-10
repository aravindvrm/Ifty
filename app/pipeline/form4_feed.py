from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.clients.sec_client import SecClient
from app.config import get_settings
from app.ingest.sec_form4 import FORM4_FORMS, IngestForm4Result, SecForm4IngestionService

_ACCESSION_DASHED_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")
_ACCESSION_NODASH_RE = re.compile(r"(\d{18})")


def _quarter_for_month(month: int) -> int:
    return ((month - 1) // 3) + 1


def _normalize_filed_date(raw: str) -> str | None:
    token = str(raw or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
        return token
    if re.fullmatch(r"\d{8}", token):
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    return None


def _normalize_accession_from_filename(filename: str) -> str | None:
    match = _ACCESSION_DASHED_RE.search(filename or "")
    if match:
        return match.group(1)
    match = _ACCESSION_NODASH_RE.search(filename or "")
    if not match:
        return None
    token = match.group(1)
    return f"{token[:10]}-{token[10:12]}-{token[12:18]}"


def _parse_form4_master_idx(text_data: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text_data.splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        cik_raw, _company, form_type_raw, filed_date_raw, filename = parts[:5]
        form_type = (form_type_raw or "").strip().upper()
        if form_type not in FORM4_FORMS:
            continue
        cik = "".join(ch for ch in cik_raw if ch.isdigit()).zfill(10)
        if not cik:
            continue
        accession_no = _normalize_accession_from_filename(filename)
        if not accession_no:
            continue
        filed_at = _normalize_filed_date(filed_date_raw or "")
        if not filed_at:
            continue
        rows.append(
            {
                "cik": cik,
                "form_type": form_type,
                "filed_at": filed_at,
                "filename": filename,
                "accession_no": accession_no,
            }
        )
    return rows


@dataclass
class DailyForm4UpdateSummary:
    files_attempted: int
    files_scanned: int
    filings_discovered: int
    filings_processed: int
    filings_upserted: int
    transactions_inserted: int
    parse_failures: int
    days_requested: int
    max_filings_requested: int
    max_filings_applied: int | None
    run_ts_utc: str


class DailyForm4FeedUpdateService:
    def __init__(self, db: Session, sec_client: SecClient) -> None:
        self.db = db
        self.sec_client = sec_client
        self.settings = get_settings()

    def run(self, *, days: int = 14, max_filings: int = 0) -> DailyForm4UpdateSummary:
        requested_days = max(1, int(days))
        max_filings_requested = max(0, int(max_filings))
        max_filings_applied: int | None = max_filings_requested if max_filings_requested > 0 else None
        now = date.today()
        files_attempted = 0
        files_scanned = 0
        discovered: list[dict[str, str]] = []

        success_days = 0
        attempts = 0
        attempt_cap = max(requested_days * 10, 180)
        cursor_day = now
        while success_days < requested_days and attempts < attempt_cap:
            q = _quarter_for_month(cursor_day.month)
            url = (
                f"{self.settings.sec_archives_base_url}/edgar/daily-index/"
                f"{cursor_day.year}/QTR{q}/master.{cursor_day.strftime('%Y%m%d')}.idx"
            )
            files_attempted += 1
            try:
                idx_text = self.sec_client.download_text(url)
            except Exception:
                attempts += 1
                cursor_day -= timedelta(days=1)
                continue
            rows = _parse_form4_master_idx(idx_text)
            discovered.extend(rows)
            files_scanned += 1
            success_days += 1
            attempts += 1
            cursor_day -= timedelta(days=1)

        # keep newest filings first
        discovered.sort(key=lambda x: (x["filed_at"], x["accession_no"]), reverse=True)
        deduped: list[dict[str, str]] = []
        seen_accessions: set[str] = set()
        for row in discovered:
            accession = row["accession_no"]
            if accession in seen_accessions:
                continue
            seen_accessions.add(accession)
            deduped.append(row)
            if max_filings_applied is not None and len(deduped) >= max_filings_applied:
                break

        ingest = SecForm4IngestionService(db=self.db, sec_client=self.sec_client)
        filings_processed = 0
        filings_upserted = 0
        transactions_inserted = 0
        parse_failures = 0

        for row in deduped:
            res: IngestForm4Result = ingest.ingest_from_index_row(
                cik=row["cik"],
                accession_no=row["accession_no"],
                form_type=row["form_type"],
                filed_at=row["filed_at"],
                filename=row["filename"],
            )
            filings_processed += int(res.filings_scanned)
            filings_upserted += int(res.filings_upserted)
            transactions_inserted += int(res.transactions_inserted)
            parse_failures += int(res.parse_failures)

        return DailyForm4UpdateSummary(
            files_attempted=files_attempted,
            files_scanned=files_scanned,
            filings_discovered=len(discovered),
            filings_processed=filings_processed,
            filings_upserted=filings_upserted,
            transactions_inserted=transactions_inserted,
            parse_failures=parse_failures,
            days_requested=requested_days,
            max_filings_requested=max_filings_requested,
            max_filings_applied=max_filings_applied,
            run_ts_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        )
