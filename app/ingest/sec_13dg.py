from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.sec_client import SecClient, cik_int
from app.config import get_settings

SUPPORTED_FORMS = {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}
CUSIP_RE = re.compile(r"\b([0-9A-Z]{8,9})\b")
PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def _extract_cusip(text_body: str) -> str | None:
    m = CUSIP_RE.search(text_body.upper())
    return m.group(1) if m else None


def _extract_percent_owned(text_body: str) -> float | None:
    # Prefer text near item 11 / percent of class language.
    lowered = text_body.lower()
    keys = [
        "percent of class represented",
        "percent of class",
        "item 11",
    ]
    for key in keys:
        idx = lowered.find(key)
        if idx >= 0:
            window = text_body[idx : idx + 800]
            m = PCT_RE.search(window)
            if m:
                val = float(m.group(1))
                return val if 0 <= val <= 100 else None
    m = PCT_RE.search(text_body)
    if not m:
        return None
    val = float(m.group(1))
    return val if 0 <= val <= 100 else None


@dataclass
class Ingest13DGResult:
    filings_upserted: int = 0
    events_inserted: int = 0


class Sec13DGIngestionService:
    def __init__(self, db: Session, sec_client: SecClient) -> None:
        self.db = db
        self.sec_client = sec_client
        self.settings = get_settings()

    def _upsert_manager(self, cik: str, manager_name: str) -> int:
        row = self.db.execute(
            text("SELECT manager_id FROM managers WHERE cik = :cik"),
            {"cik": cik},
        ).mappings().first()
        if row:
            return int(row["manager_id"])
        result = self.db.execute(
            text(
                """
                INSERT INTO managers (cik, manager_name, normalized_name)
                VALUES (:cik, :manager_name, :normalized_name)
                """
            ),
            {"cik": cik, "manager_name": manager_name, "normalized_name": manager_name.upper()},
        )
        self.db.commit()
        return int(result.lastrowid)

    def _upsert_filing(
        self,
        manager_id: int,
        cik: str,
        accession_no: str,
        form_type: str,
        filed_at: str,
        period_end_date: str | None,
        primary_document: str | None,
    ) -> int | None:
        existing = self.db.execute(
            text("SELECT filing_id FROM filings WHERE accession_no = :accession_no"),
            {"accession_no": accession_no},
        ).mappings().first()
        if existing:
            return None

        accession_nodash = accession_no.replace("-", "")
        sec_url = (
            f"{self.settings.sec_archives_base_url}/edgar/data/{cik_int(cik)}/"
            f"{accession_nodash}/{primary_document or ''}"
        )
        result = self.db.execute(
            text(
                """
                INSERT INTO filings (
                  accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment
                ) VALUES (
                  :accession_no, :form_type, :cik, :manager_id, :filed_at, :period_end_date, :sec_url, :is_amendment
                )
                """
            ),
            {
                "accession_no": accession_no,
                "form_type": form_type,
                "cik": cik,
                "manager_id": manager_id,
                "filed_at": filed_at,
                "period_end_date": period_end_date,
                "sec_url": sec_url,
                "is_amendment": 1 if form_type.endswith("/A") else 0,
            },
        )
        self.db.commit()
        return int(result.lastrowid)

    def _classify_event(
        self,
        manager_id: int,
        cusip_raw: str | None,
        percent_owned: float | None,
        report_date: str,
    ) -> str:
        if not cusip_raw or percent_owned is None:
            return "OTHER"
        prev = self.db.execute(
            text(
                """
                SELECT percent_beneficial_owned
                FROM beneficial_ownership_events
                WHERE manager_id = :manager_id
                  AND cusip_raw = :cusip_raw
                  AND report_date < :report_date
                ORDER BY report_date DESC
                LIMIT 1
                """
            ),
            {"manager_id": manager_id, "cusip_raw": cusip_raw, "report_date": report_date},
        ).mappings().first()
        if not prev:
            return "NEW_5PCT" if percent_owned >= 5 else "OTHER"
        prev_pct = float(prev["percent_beneficial_owned"] or 0.0)
        if percent_owned < 5 <= prev_pct:
            return "EXIT_5PCT"
        if percent_owned > prev_pct:
            return "AMENDMENT_UP"
        if percent_owned < prev_pct:
            return "AMENDMENT_DOWN"
        return "OTHER"

    def ingest_for_cik(self, cik: str, limit: int = 20) -> Ingest13DGResult:
        result = Ingest13DGResult()
        submissions = self.sec_client.get_submissions(cik)
        manager_name = str(submissions.get("name", "")).strip() or f"CIK {cik}"
        manager_id = self._upsert_manager(cik=cik, manager_name=manager_name)

        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_docs = recent.get("primaryDocument", [])

        max_rows = min(limit, len(forms))
        for i in range(max_rows):
            form_type = forms[i]
            if form_type not in SUPPORTED_FORMS:
                continue
            accession_no = accession_numbers[i]
            filed_at = filing_dates[i]
            report_date = report_dates[i] if i < len(report_dates) else filed_at
            primary_doc = primary_docs[i] if i < len(primary_docs) else None

            filing_id = self._upsert_filing(
                manager_id=manager_id,
                cik=cik,
                accession_no=accession_no,
                form_type=form_type,
                filed_at=filed_at,
                period_end_date=report_date,
                primary_document=primary_doc,
            )
            if not filing_id:
                continue
            result.filings_upserted += 1
            if not primary_doc:
                continue

            filing_text_url = (
                f"{self.settings.sec_archives_base_url}/edgar/data/{cik_int(cik)}/"
                f"{accession_no.replace('-', '')}/{primary_doc}"
            )
            try:
                body = self.sec_client.download_text(filing_text_url)
                cusip_raw = _extract_cusip(body)
                percent_owned = _extract_percent_owned(body)
                event_type = self._classify_event(
                    manager_id=manager_id,
                    cusip_raw=cusip_raw,
                    percent_owned=percent_owned,
                    report_date=report_date,
                )
                self.db.execute(
                    text(
                        """
                        INSERT INTO beneficial_ownership_events (
                          filing_id, manager_id, security_id, report_date, event_type,
                          percent_beneficial_owned, shares_beneficial_owned,
                          cusip_raw, issuer_name_raw, ticker_raw, details_json,
                          mapping_status, mapping_confidence
                        ) VALUES (
                          :filing_id, :manager_id, NULL, :report_date, :event_type,
                          :percent_beneficial_owned, NULL,
                          :cusip_raw, NULL, NULL, :details_json,
                          'UNMAPPED', NULL
                        )
                        """
                    ),
                    {
                        "filing_id": filing_id,
                        "manager_id": manager_id,
                        "report_date": report_date,
                        "event_type": event_type,
                        "percent_beneficial_owned": percent_owned,
                        "cusip_raw": cusip_raw,
                        "details_json": None,
                    },
                )
                self.db.commit()
                result.events_inserted += 1
            except Exception:
                self.db.rollback()
                continue

        return result

