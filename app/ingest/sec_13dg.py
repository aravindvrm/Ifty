from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.sec_client import SecClient, cik_int
from app.config import get_settings

SUPPORTED_FORMS = {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}
_FORM_ALIASES = {
    "SCHEDULE 13D": "SC 13D",
    "SCHEDULE 13D/A": "SC 13D/A",
    "SCHEDULE 13G": "SC 13G",
    "SCHEDULE 13G/A": "SC 13G/A",
    "13D": "SC 13D",
    "13D/A": "SC 13D/A",
    "13G": "SC 13G",
    "13G/A": "SC 13G/A",
}
_CUSIP_CONTEXT_RE = re.compile(
    r"(?is)\bCUSIP(?:\s+NO\.?|\s+NUMBER)?\s*[:#]?\s*([0-9A-Z][0-9A-Z\-\s]{6,20})"
)
_CUSIP_TOKEN_RE = re.compile(r"\b([0-9A-Z]{8,9})\b")
PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_ISSUER_RE = re.compile(
    r"(?is)\b(?:Name\s+of\s+Issuer|Issuer\s+Name)\b\s*[:\-]?\s*([^\n\r]{3,140})"
)
_CUSIP_STOPWORDS = {
    "DOCUMENT",
    "DOCUMENTS",
    "CUSIP",
    "NUMBER",
    "NUMBERS",
    "CLASS",
    "SECURITY",
    "SECURITIES",
    "COMMON",
    "STOCK",
    "SHARES",
    "PERCENT",
    "TITLE",
}
_ISSUER_BAD_EXACT = {
    "DOCUMENT",
    "CUSIP",
    "NAME",
    "ISSUER",
}


def _cusip_char_value(ch: str) -> int | None:
    if ch.isdigit():
        return int(ch)
    if "A" <= ch <= "Z":
        return ord(ch) - ord("A") + 10
    if ch == "*":
        return 36
    if ch == "@":
        return 37
    if ch == "#":
        return 38
    return None


def _is_valid_cusip9(candidate: str) -> bool:
    if len(candidate) != 9:
        return False
    if not candidate[-1].isdigit():
        return False
    total = 0
    for i, ch in enumerate(candidate[:8]):
        value = _cusip_char_value(ch)
        if value is None:
            return False
        # Multiply every 2nd character (positions 2,4,6,8).
        if (i % 2) == 1:
            value *= 2
        total += (value // 10) + (value % 10)
    check = (10 - (total % 10)) % 10
    return check == int(candidate[-1])


def normalize_13dg_form_type(raw_form_type: str | None) -> str | None:
    value = " ".join(str(raw_form_type or "").upper().strip().split())
    if not value:
        return None
    normalized = _FORM_ALIASES.get(value, value)
    if normalized in SUPPORTED_FORMS:
        return normalized
    return None


def _is_bad_issuer_candidate(candidate: str) -> bool:
    upper = candidate.upper()
    collapsed = upper.replace(" ", "")
    if upper.startswith(")") or upper.startswith("("):
        return True
    if upper.startswith("CUSIP"):
        return True
    if upper in _ISSUER_BAD_EXACT:
        return True
    if re.match(r"^ITEM\d+TO\d+$", collapsed):
        return True
    if " VARIABLE " in upper or " REMARKET" in upper:
        return True
    return False


def _normalize_cusip_candidate(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = "".join(ch for ch in raw.upper() if ch.isalnum())
    if len(cleaned) < 9:
        return None
    cleaned = cleaned[:9]
    if cleaned in _CUSIP_STOPWORDS:
        return None
    # Guardrail: reject obvious header tokens like DOCUMENT.
    if not any(ch.isdigit() for ch in cleaned):
        return None
    if not _is_valid_cusip9(cleaned):
        return None
    return cleaned


def _extract_cusip(text_body: str) -> str | None:
    upper = text_body.upper()

    # XML/XBRL schedule docs often expose explicit CUSIP tags.
    for tag_pattern in [
        re.compile(r"(?is)<\s*cusipnumber\s*>([^<]{6,24})<\s*/\s*cusipnumber\s*>"),
        re.compile(r"(?is)<\s*cusip\s*>([^<]{6,24})<\s*/\s*cusip\s*>"),
    ]:
        for match in tag_pattern.finditer(text_body):
            cleaned = _normalize_cusip_candidate(match.group(1))
            if cleaned:
                return cleaned

    for match in _CUSIP_CONTEXT_RE.finditer(upper):
        raw_candidate = match.group(1)
        cleaned = _normalize_cusip_candidate(raw_candidate)
        if cleaned:
            return cleaned

    for match in _CUSIP_TOKEN_RE.finditer(upper):
        cleaned = _normalize_cusip_candidate(match.group(1))
        if cleaned:
            return cleaned
    return None


def _extract_issuer_name(text_body: str) -> str | None:
    xml_match = re.search(
        r"(?is)<\s*nameofissuer\s*>([^<]{3,200})<\s*/\s*nameofissuer\s*>",
        text_body,
    )
    if xml_match:
        candidate = (xml_match.group(1) or "").strip()
        candidate = re.sub(r"\s+", " ", candidate).strip(" -:;,.")
        if candidate and not _is_bad_issuer_candidate(candidate):
            return candidate[:140]

    for match in _ISSUER_RE.finditer(text_body):
        candidate = (match.group(1) or "").strip()
        if not candidate:
            continue
        candidate = re.sub(r"(?is)<[^>]+>", " ", candidate)
        candidate = re.sub(r"&[A-Z0-9#]+;", " ", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"[^-A-Z0-9&.,'()/ ]", " ", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+", " ", candidate)
        candidate = candidate.strip(" -:;,.")
        if len(candidate) < 3:
            continue
        upper_candidate = candidate.upper()
        if _is_bad_issuer_candidate(upper_candidate):
            continue
        if any(token in upper_candidate for token in {"</", "/TR", "/TD", "FONT", "DIV", "TABLE"}):
            continue
        if not re.search(r"[A-Z]", upper_candidate):
            continue
        return candidate[:140]
    return None


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
                RETURNING manager_id
                """
            ),
            {"cik": cik, "manager_name": manager_name, "normalized_name": manager_name.upper()},
        )
        manager_id = int(result.scalar_one())
        self.db.commit()
        return manager_id

    def _upsert_filing(
        self,
        manager_id: int,
        cik: str,
        accession_no: str,
        form_type: str,
        filed_at: str,
        period_end_date: str | None,
        primary_document: str | None,
    ) -> tuple[int, bool]:
        existing = self.db.execute(
            text("SELECT filing_id FROM filings WHERE accession_no = :accession_no"),
            {"accession_no": accession_no},
        ).mappings().first()
        if existing:
            return int(existing["filing_id"]), False

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
                RETURNING filing_id
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
        filing_id = int(result.scalar_one())
        self.db.commit()
        return filing_id, True

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
        normalized_forms = [normalize_13dg_form_type(form) for form in forms]
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_docs = recent.get("primaryDocument", [])

        # `filings.recent` is mixed-form; select matching 13D/G forms first.
        matching_indexes = [i for i, form in enumerate(normalized_forms) if form in SUPPORTED_FORMS]
        if limit is not None:
            matching_indexes = matching_indexes[: max(0, int(limit))]

        for i in matching_indexes:
            form_type = normalized_forms[i]
            if form_type is None:
                continue
            accession_no = accession_numbers[i]
            filed_at = str(filing_dates[i] or "").strip()
            report_date_raw = str(report_dates[i] or "").strip() if i < len(report_dates) else ""
            report_date = report_date_raw or filed_at
            primary_doc = primary_docs[i] if i < len(primary_docs) else None
            if not report_date:
                # Defensive guard: skip malformed recent rows with no usable date.
                continue

            filing_id, filing_created = self._upsert_filing(
                manager_id=manager_id,
                cik=cik,
                accession_no=accession_no,
                form_type=form_type,
                filed_at=filed_at,
                period_end_date=report_date,
                primary_document=primary_doc,
            )
            if filing_created:
                result.filings_upserted += 1

            has_event = self.db.execute(
                text(
                    """
                    SELECT 1
                    FROM beneficial_ownership_events
                    WHERE filing_id = :filing_id
                    LIMIT 1
                    """
                ),
                {"filing_id": filing_id},
            ).first()
            if has_event:
                continue
            if not primary_doc:
                continue

            filing_text_url = (
                f"{self.settings.sec_archives_base_url}/edgar/data/{cik_int(cik)}/"
                f"{accession_no.replace('-', '')}/{primary_doc}"
            )
            try:
                body = self.sec_client.download_text(filing_text_url)
                cusip_raw = _extract_cusip(body)
                issuer_name_raw = _extract_issuer_name(body)
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
                          :cusip_raw, :issuer_name_raw, NULL, :details_json,
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
                        "issuer_name_raw": issuer_name_raw,
                        "details_json": (
                            json.dumps({"parse_version": 2})
                            if (cusip_raw or issuer_name_raw or percent_owned is not None)
                            else None
                        ),
                    },
                )
                self.db.commit()
                result.events_inserted += 1
            except Exception:
                self.db.rollback()
                continue

        return result
