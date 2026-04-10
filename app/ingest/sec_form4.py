from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.sec_client import SecClient, cik_10, cik_int
from app.config import get_settings

FORM4_FORMS = {"4", "4/A"}
_OWNERSHIP_XML_RE = re.compile(r"(?is)<ownershipDocument\b.*?</ownershipDocument>")


def _clean_text(value: object) -> str | None:
    text_value = str(value or "").strip()
    return text_value or None


def _to_float(value: object) -> float | None:
    token = _clean_text(value)
    if token is None:
        return None
    token = token.replace(",", "")
    try:
        return float(token)
    except Exception:
        return None


def _to_flag(value: object) -> int:
    token = str(value or "").strip().lower()
    if token in {"1", "true", "yes", "y"}:
        return 1
    return 0


def _find_text(node: ET.Element, path: str) -> str | None:
    elem = node.find(path)
    if elem is None:
        return None
    return _clean_text(elem.text)


def _extract_ownership_xml(body: str) -> str | None:
    match = _OWNERSHIP_XML_RE.search(body)
    if match:
        return match.group(0)
    stripped = body.strip()
    if stripped.startswith("<ownershipDocument") and stripped.endswith("</ownershipDocument>"):
        return stripped
    return None


def _role_group(*, is_director: int, is_officer: int, is_ten_percent_owner: int, officer_title: str | None) -> str:
    title = (officer_title or "").strip().lower()
    if is_officer and ("chief executive officer" in title or title == "ceo" or " ceo" in title):
        return "CEO"
    if is_officer and ("chief financial officer" in title or title == "cfo" or " cfo" in title):
        return "CFO"
    if is_officer:
        return "OFFICER"
    if is_director:
        return "DIRECTOR"
    if is_ten_percent_owner:
        return "TEN_PCT_OWNER"
    return "OTHER"


def _signal_type(*, is_derivative: int, transaction_code: str | None, acquisition_disposition: str | None) -> str:
    if int(is_derivative or 0) == 1:
        return "DERIVATIVE"
    code = (transaction_code or "").strip().upper()
    ad = (acquisition_disposition or "").strip().upper()
    if code == "P" and ad != "D":
        return "OPEN_MARKET_BUY"
    if code == "S" and ad == "D":
        return "OPEN_MARKET_SELL"
    return "OTHER"


def _row_hash(payload: list[object]) -> str:
    raw = "|".join("" if x is None else str(x) for x in payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class IngestForm4Result:
    filings_upserted: int = 0
    filings_scanned: int = 0
    transactions_inserted: int = 0
    parse_failures: int = 0


class SecForm4IngestionService:
    def __init__(self, db: Session, sec_client: SecClient) -> None:
        self.db = db
        self.sec_client = sec_client
        self.settings = get_settings()

    def _upsert_filing(
        self,
        *,
        accession_no: str,
        form_type: str,
        cik: str,
        filed_at: str,
        period_end_date: str | None,
        sec_url: str,
    ) -> tuple[int, bool]:
        existing = self.db.execute(
            text("SELECT filing_id FROM filings WHERE accession_no = :accession_no"),
            {"accession_no": accession_no},
        ).mappings().first()
        if existing:
            return int(existing["filing_id"]), False
        result = self.db.execute(
            text(
                """
                INSERT INTO filings (
                  accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment
                ) VALUES (
                  :accession_no, :form_type, :cik, NULL, :filed_at, :period_end_date, :sec_url, :is_amendment
                )
                RETURNING filing_id
                """
            ),
            {
                "accession_no": accession_no,
                "form_type": form_type,
                "cik": cik_10(cik),
                "filed_at": filed_at,
                "period_end_date": period_end_date,
                "sec_url": sec_url,
                "is_amendment": 1 if str(form_type).upper().endswith("/A") else 0,
            },
        )
        filing_id = int(result.scalar_one())
        self.db.commit()
        return filing_id, True

    def _resolve_security_id(self, ticker: str | None) -> int | None:
        symbol = (ticker or "").strip().upper()
        if not symbol:
            return None
        row = self.db.execute(
            text(
                """
                SELECT si.security_id
                FROM security_identifiers si
                JOIN securities s ON s.security_id = si.security_id
                WHERE si.id_type = 'TICKER'
                  AND UPPER(si.id_value) = :ticker
                  AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                  AND UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
                ORDER BY si.valid_from DESC
                LIMIT 1
                """
            ),
            {"ticker": symbol},
        ).mappings().first()
        if not row:
            return None
        return int(row["security_id"])

    def _parse_transactions(self, xml_text: str) -> dict[str, object]:
        root = ET.fromstring(xml_text)
        issuer = root.find("issuer")
        issuer_cik = _find_text(issuer, "issuerCik") if issuer is not None else None
        issuer_name = _find_text(issuer, "issuerName") if issuer is not None else None
        issuer_symbol = _find_text(issuer, "issuerTradingSymbol") if issuer is not None else None
        period_of_report = _find_text(root, "periodOfReport")

        first_owner = root.find("reportingOwner")
        owner_cik: str | None = None
        owner_name: str | None = None
        officer_title: str | None = None
        is_director = 0
        is_officer = 0
        is_ten_percent_owner = 0
        is_other = 0
        if first_owner is not None:
            owner_cik = _find_text(first_owner, "reportingOwnerId/rptOwnerCik")
            owner_name = _find_text(first_owner, "reportingOwnerId/rptOwnerName")
            is_director = _to_flag(_find_text(first_owner, "reportingOwnerRelationship/isDirector"))
            is_officer = _to_flag(_find_text(first_owner, "reportingOwnerRelationship/isOfficer"))
            is_ten_percent_owner = _to_flag(_find_text(first_owner, "reportingOwnerRelationship/isTenPercentOwner"))
            is_other = _to_flag(_find_text(first_owner, "reportingOwnerRelationship/isOther"))
            officer_title = _find_text(first_owner, "reportingOwnerRelationship/officerTitle")
        role_group = _role_group(
            is_director=is_director,
            is_officer=is_officer,
            is_ten_percent_owner=is_ten_percent_owner,
            officer_title=officer_title,
        )

        transactions: list[dict[str, object]] = []
        table_specs = [
            ("nonDerivativeTable/nonDerivativeTransaction", 0),
            ("derivativeTable/derivativeTransaction", 1),
        ]
        for path, derivative_flag in table_specs:
            for tx in root.findall(path):
                transaction_date = _find_text(tx, "transactionDate/value") or period_of_report
                if not transaction_date:
                    continue
                transaction_code = _find_text(tx, "transactionCoding/transactionCode")
                transaction_shares = _to_float(_find_text(tx, "transactionAmounts/transactionShares/value"))
                transaction_price = _to_float(_find_text(tx, "transactionAmounts/transactionPricePerShare/value"))
                acquisition_disposition = _find_text(
                    tx, "transactionAmounts/transactionAcquiredDisposedCode/value"
                )
                shares_owned_following = _to_float(
                    _find_text(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
                )
                ownership_nature = _find_text(tx, "ownershipNature/directOrIndirectOwnership/value")
                transaction_value_usd = (
                    (transaction_shares or 0.0) * (transaction_price or 0.0)
                    if transaction_shares is not None and transaction_price is not None
                    else None
                )
                transactions.append(
                    {
                        "transaction_date": transaction_date,
                        "transaction_code": transaction_code,
                        "transaction_shares": transaction_shares,
                        "transaction_price": transaction_price,
                        "acquisition_disposition": acquisition_disposition,
                        "shares_owned_following": shares_owned_following,
                        "ownership_nature": ownership_nature,
                        "is_derivative": derivative_flag,
                        "transaction_value_usd": transaction_value_usd,
                        "signal_type": _signal_type(
                            is_derivative=derivative_flag,
                            transaction_code=transaction_code,
                            acquisition_disposition=acquisition_disposition,
                        ),
                    }
                )

        return {
            "period_of_report": period_of_report,
            "issuer_cik": issuer_cik,
            "issuer_name": issuer_name,
            "issuer_symbol": issuer_symbol,
            "reporting_owner_cik": owner_cik,
            "reporting_owner_name": owner_name,
            "reporting_owner_title": officer_title,
            "is_director": is_director,
            "is_officer": is_officer,
            "is_ten_percent_owner": is_ten_percent_owner,
            "is_other": is_other,
            "role_group": role_group,
            "transactions": transactions,
        }

    def ingest_from_index_row(
        self,
        *,
        cik: str,
        accession_no: str,
        form_type: str,
        filed_at: str,
        filename: str,
    ) -> IngestForm4Result:
        result = IngestForm4Result(filings_scanned=1)
        accession_no_dashless = accession_no.replace("-", "")
        cik_no_leading_zeros = cik_int(cik)
        preferred_txt_url = (
            f"{self.settings.sec_archives_base_url}/edgar/data/{cik_no_leading_zeros}/"
            f"{accession_no_dashless}/{accession_no}.txt"
        )
        filename_url = f"{self.settings.sec_archives_base_url}/{filename.lstrip('/')}"
        candidate_urls: list[str] = []
        for url in (preferred_txt_url, filename_url):
            if url and url not in candidate_urls:
                candidate_urls.append(url)

        sec_url = preferred_txt_url
        filing_id, created = self._upsert_filing(
            accession_no=accession_no,
            form_type=form_type,
            cik=cik,
            filed_at=filed_at,
            period_end_date=filed_at,
            sec_url=sec_url,
        )
        if created:
            result.filings_upserted += 1

        existing = self.db.execute(
            text(
                """
                SELECT 1
                FROM insider_transactions
                WHERE filing_id = :filing_id
                LIMIT 1
                """
            ),
            {"filing_id": filing_id},
        ).first()
        if existing:
            return result

        try:
            xml_text: str | None = None
            resolved_sec_url: str | None = None
            for candidate_url in candidate_urls:
                try:
                    filing_text = self.sec_client.download_text(candidate_url)
                except Exception:
                    continue
                maybe_xml = _extract_ownership_xml(filing_text)
                if maybe_xml:
                    xml_text = maybe_xml
                    resolved_sec_url = candidate_url
                    break

            if not xml_text:
                result.parse_failures += 1
                return result

            if resolved_sec_url and resolved_sec_url != sec_url:
                self.db.execute(
                    text(
                        """
                        UPDATE filings
                        SET sec_url = :sec_url
                        WHERE filing_id = :filing_id
                        """
                    ),
                    {"filing_id": filing_id, "sec_url": resolved_sec_url},
                )
            parsed = self._parse_transactions(xml_text)
            security_id = self._resolve_security_id(parsed.get("issuer_symbol"))
            period_of_report = _clean_text(parsed.get("period_of_report")) or filed_at
            for tx in parsed.get("transactions", []):
                tx = dict(tx)
                row_hash = _row_hash(
                    [
                        parsed.get("issuer_cik"),
                        parsed.get("issuer_symbol"),
                        parsed.get("reporting_owner_cik"),
                        tx.get("transaction_date"),
                        tx.get("transaction_code"),
                        tx.get("transaction_shares"),
                        tx.get("transaction_price"),
                        tx.get("acquisition_disposition"),
                        tx.get("ownership_nature"),
                        tx.get("is_derivative"),
                    ]
                )
                insert_result = self.db.execute(
                    text(
                        """
                        INSERT INTO insider_transactions (
                          filing_id, security_id, issuer_cik, issuer_name, issuer_trading_symbol,
                          reporting_owner_cik, reporting_owner_name, reporting_owner_title, role_group,
                          is_director, is_officer, is_ten_percent_owner, is_other,
                          transaction_date, transaction_code, acquisition_disposition,
                          ownership_nature, is_derivative, transaction_shares, transaction_price,
                          shares_owned_following, transaction_value_usd, signal_type, row_hash
                        ) VALUES (
                          :filing_id, :security_id, :issuer_cik, :issuer_name, :issuer_trading_symbol,
                          :reporting_owner_cik, :reporting_owner_name, :reporting_owner_title, :role_group,
                          :is_director, :is_officer, :is_ten_percent_owner, :is_other,
                          :transaction_date, :transaction_code, :acquisition_disposition,
                          :ownership_nature, :is_derivative, :transaction_shares, :transaction_price,
                          :shares_owned_following, :transaction_value_usd, :signal_type, :row_hash
                        )
                        ON CONFLICT (filing_id, row_hash) DO NOTHING
                        """
                    ),
                    {
                        "filing_id": filing_id,
                        "security_id": security_id,
                        "issuer_cik": parsed.get("issuer_cik"),
                        "issuer_name": parsed.get("issuer_name"),
                        "issuer_trading_symbol": parsed.get("issuer_symbol"),
                        "reporting_owner_cik": parsed.get("reporting_owner_cik"),
                        "reporting_owner_name": parsed.get("reporting_owner_name"),
                        "reporting_owner_title": parsed.get("reporting_owner_title"),
                        "role_group": parsed.get("role_group"),
                        "is_director": int(parsed.get("is_director") or 0),
                        "is_officer": int(parsed.get("is_officer") or 0),
                        "is_ten_percent_owner": int(parsed.get("is_ten_percent_owner") or 0),
                        "is_other": int(parsed.get("is_other") or 0),
                        "transaction_date": _clean_text(tx.get("transaction_date")) or period_of_report,
                        "transaction_code": tx.get("transaction_code"),
                        "acquisition_disposition": tx.get("acquisition_disposition"),
                        "ownership_nature": tx.get("ownership_nature"),
                        "is_derivative": int(tx.get("is_derivative") or 0),
                        "transaction_shares": tx.get("transaction_shares"),
                        "transaction_price": tx.get("transaction_price"),
                        "shares_owned_following": tx.get("shares_owned_following"),
                        "transaction_value_usd": tx.get("transaction_value_usd"),
                        "signal_type": tx.get("signal_type"),
                        "row_hash": row_hash,
                    },
                )
                result.transactions_inserted += int(insert_result.rowcount or 0)
            # keep filing period updated when parsed period exists
            if period_of_report:
                self.db.execute(
                    text(
                        """
                        UPDATE filings
                        SET period_end_date = :period_end_date
                        WHERE filing_id = :filing_id
                        """
                    ),
                    {"filing_id": filing_id, "period_end_date": period_of_report},
                )
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            result.parse_failures += 1
            return result
