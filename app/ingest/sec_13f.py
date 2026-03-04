from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.clients.sec_client import SecClient, cik_int
from app.config import get_settings

SUPPORTED_FORMS = {"13F-HR", "13F-HR/A"}


def _is_amendment(form_type: str) -> int:
    return 1 if form_type.endswith("/A") else 0


def _row_hash(parts: list[str]) -> str:
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_text(node: ET.Element | None, tag_names: list[str]) -> str | None:
    if node is None:
        return None
    tag_set = {tag.lower() for tag in tag_names}

    def local_name(tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    for child in node.iter():
        name = local_name(child.tag).lower()
        if name in tag_set and child.text and child.text.strip():
            return child.text.strip()
    return None


def _parse_13f_xml_rows(xml_text: str) -> list[dict[str, str | float | None]]:
    root = ET.fromstring(xml_text)
    rows: list[dict[str, str | float | None]] = []

    # SEC infoTable XML can include namespaces; iterate by suffix to avoid hard-coded ns URIs.
    def local_name(tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    for node in root.iter():
        if local_name(node.tag).lower() != "infotable":
            continue
        issuer = _safe_text(node, ["nameOfIssuer"])
        class_title = _safe_text(node, ["titleOfClass"])
        cusip = _safe_text(node, ["cusip"])
        value = _safe_text(node, ["value"])
        shares = _safe_text(node, ["sshPrnamt"])
        share_type = _safe_text(node, ["sshPrnamtType"])
        option_type = _safe_text(node, ["putCall"])
        inv_disc = _safe_text(node, ["investmentDiscretion"])
        other_mgr = _safe_text(node, ["otherManager"])
        voting_sole = _safe_text(node, ["Sole"])
        voting_shared = _safe_text(node, ["Shared"])
        voting_none = _safe_text(node, ["None"])

        rows.append(
            {
                "issuer_name_raw": issuer,
                "class_title_raw": class_title,
                "cusip_raw": cusip,
                "value_usd_thousands": float(value) if value else None,
                "shares": float(shares) if shares else None,
                "share_type": share_type,
                "option_type": option_type,
                "investment_discretion": inv_disc,
                "other_manager_text": other_mgr,
                "voting_sole": float(voting_sole) if voting_sole else None,
                "voting_shared": float(voting_shared) if voting_shared else None,
                "voting_none": float(voting_none) if voting_none else None,
            }
        )

    return rows


def _extract_xml_segments(text_payload: str) -> list[str]:
    # Many SEC .txt filings wrap XML payloads inside <XML> ... </XML> blocks.
    blocks = re.findall(r"(?is)<xml>(.*?)</xml>", text_payload)
    if blocks:
        return [blk.strip() for blk in blocks if blk.strip()]
    return []


def _parse_13f_rows_from_payload(payload: str) -> list[dict[str, str | float | None]]:
    candidates: list[list[dict[str, str | float | None]]] = []

    # 1) Direct XML payload.
    try:
        rows = _parse_13f_xml_rows(payload)
        if rows:
            candidates.append(rows)
    except ET.ParseError:
        pass

    # 2) XML sections embedded in a .txt filing.
    for segment in _extract_xml_segments(payload):
        if "infotable" not in segment.lower() and "informationtable" not in segment.lower():
            continue
        try:
            rows = _parse_13f_xml_rows(segment)
            if rows:
                candidates.append(rows)
        except ET.ParseError:
            continue

    if not candidates:
        return []

    # Choose the richest parse result (true infotable usually has the largest row count).
    candidates.sort(key=len, reverse=True)
    return candidates[0]


@dataclass
class IngestResult:
    filings_upserted: int = 0
    holdings_inserted: int = 0


class Sec13FIngestionService:
    def __init__(self, db: Session, sec_client: SecClient) -> None:
        self.db = db
        self.sec_client = sec_client
        self.settings = get_settings()

    def _upsert_manager(self, cik: str, manager_name: str) -> int:
        existing = self.db.execute(
            text("SELECT manager_id FROM managers WHERE cik = :cik"),
            {"cik": cik},
        ).mappings().first()
        if existing:
            return int(existing["manager_id"])

        result = self.db.execute(
            text(
                """
                INSERT INTO managers (cik, manager_name, normalized_name)
                VALUES (:cik, :manager_name, :normalized_name)
                RETURNING manager_id
                """
            ),
            {
                "cik": cik,
                "manager_name": manager_name,
                "normalized_name": manager_name.upper(),
            },
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
                "is_amendment": _is_amendment(form_type),
            },
        )
        filing_id = int(result.scalar_one())
        self.db.commit()
        return filing_id

    def _candidate_infotable_paths(self, filing_index: dict) -> list[str]:
        directory = filing_index.get("directory", {})
        item_list = directory.get("item", [])
        if not isinstance(item_list, list):
            return []
        strong: list[str] = []
        medium: list[str] = []
        weak: list[str] = []
        for item in item_list:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            lowered = name.lower()
            if lowered.endswith(".xml") and "infotable" in lowered:
                strong.append(name)
            elif lowered.endswith(".txt") and "infotable" in lowered:
                strong.append(name)
            elif lowered.endswith(".xml") and ("13f" in lowered or "form13f" in lowered):
                medium.append(name)
            elif lowered.endswith(".txt") and ("13f" in lowered or "form13f" in lowered):
                medium.append(name)
            elif lowered.endswith(".xml") or lowered.endswith(".txt"):
                weak.append(name)
        return strong + medium + weak

    def _insert_holdings_rows(
        self,
        filing_id: int,
        manager_id: int,
        report_date: str,
        rows: list[dict[str, str | float | None]],
    ) -> int:
        inserted = 0
        params_list: list[dict[str, object]] = []
        insert_stmt = text(
            """
            INSERT INTO holdings_13f (
              filing_id, manager_id, security_id, report_date,
              issuer_name_raw, class_title_raw, cusip_raw, ticker_raw,
              value_usd_thousands, shares, share_type, option_type,
              investment_discretion, other_manager_text,
              voting_sole, voting_shared, voting_none,
              row_hash, mapping_status, mapping_confidence
            ) VALUES (
              :filing_id, :manager_id, NULL, :report_date,
              :issuer_name_raw, :class_title_raw, :cusip_raw, NULL,
              :value_usd_thousands, :shares, :share_type, :option_type,
              :investment_discretion, :other_manager_text,
              :voting_sole, :voting_shared, :voting_none,
              :row_hash, 'UNMAPPED', NULL
            )
            ON CONFLICT (filing_id, row_hash) DO NOTHING
            """
        )
        for row in rows:
            row_sig = _row_hash(
                [
                    str(filing_id),
                    str(row.get("issuer_name_raw") or ""),
                    str(row.get("class_title_raw") or ""),
                    str(row.get("cusip_raw") or ""),
                    str(row.get("value_usd_thousands") or ""),
                    str(row.get("shares") or ""),
                    str(row.get("share_type") or ""),
                    str(row.get("option_type") or ""),
                ]
            )
            params_list.append(
                {
                    "filing_id": filing_id,
                    "manager_id": manager_id,
                    "report_date": report_date,
                    "issuer_name_raw": row.get("issuer_name_raw"),
                    "class_title_raw": row.get("class_title_raw"),
                    "cusip_raw": row.get("cusip_raw"),
                    "value_usd_thousands": row.get("value_usd_thousands"),
                    "shares": row.get("shares"),
                    "share_type": row.get("share_type"),
                    "option_type": row.get("option_type"),
                    "investment_discretion": row.get("investment_discretion"),
                    "other_manager_text": row.get("other_manager_text"),
                    "voting_sole": row.get("voting_sole"),
                    "voting_shared": row.get("voting_shared"),
                    "voting_none": row.get("voting_none"),
                    "row_hash": row_sig,
                }
            )

        batch_size = 1000
        for i in range(0, len(params_list), batch_size):
            batch = params_list[i : i + batch_size]
            result = self.db.execute(insert_stmt, batch)
            inserted += max(int(result.rowcount or 0), 0)
        self.db.commit()
        return inserted

    def ingest_for_cik(self, cik: str, limit: int = 20) -> IngestResult:
        result = IngestResult()
        submissions = self.sec_client.get_submissions(cik)
        manager_name = str(submissions.get("name", "")).strip() or f"CIK {cik}"
        manager_id = self._upsert_manager(cik=cik, manager_name=manager_name)

        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_docs = recent.get("primaryDocument", [])

        # `filings.recent` is mixed-form and can be very large; select by matching forms first.
        matching_indexes = [i for i, form in enumerate(forms) if form in SUPPORTED_FORMS]
        if limit is not None:
            matching_indexes = matching_indexes[: max(0, int(limit))]

        for i in matching_indexes:
            form_type = forms[i]
            accession_no = accession_numbers[i]
            filed_at = filing_dates[i]
            report_date = report_dates[i] if i < len(report_dates) else None
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

            accession_nodash = accession_no.replace("-", "")
            try:
                index_doc = self.sec_client.get_filing_index(cik, accession_nodash)
                info_table_candidates = self._candidate_infotable_paths(index_doc)
                if not info_table_candidates:
                    continue

                best_rows: list[dict[str, str | float | None]] = []
                for candidate_name in info_table_candidates:
                    info_table_url = (
                        f"{self.settings.sec_archives_base_url}/edgar/data/{cik_int(cik)}/"
                        f"{accession_nodash}/{candidate_name}"
                    )
                    payload = self.sec_client.download_text(info_table_url)
                    rows = _parse_13f_rows_from_payload(payload)
                    if len(rows) > len(best_rows):
                        best_rows = rows

                if report_date and best_rows:
                    inserted = self._insert_holdings_rows(
                        filing_id=filing_id,
                        manager_id=manager_id,
                        report_date=report_date,
                        rows=best_rows,
                    )
                    result.holdings_inserted += inserted
            except ET.ParseError:
                # Keep metadata ingestion successful if one XML payload is malformed.
                continue
            except Exception:
                # Continue processing other filings; log out-of-band once logging framework is added.
                continue

        self.db.execute(
            text(
                """
                INSERT INTO api_request_log (provider, endpoint, status_code, ok, latency_ms, cache_hit)
                VALUES ('SEC', 'INGEST_SUMMARY', 200, 1, 0, 1)
                """
            )
        )
        self.db.commit()
        return result

    def ingest_for_ciks(self, ciks: list[str], limit: int = 20) -> dict[str, dict[str, int]]:
        summary: dict[str, dict[str, int]] = {}
        for cik in ciks:
            res = self.ingest_for_cik(cik=cik, limit=limit)
            summary[cik] = {
                "filings_upserted": res.filings_upserted,
                "holdings_inserted": res.holdings_inserted,
            }
        return summary

    @staticmethod
    def summary_json(summary: dict[str, dict[str, int]]) -> str:
        return json.dumps(summary, indent=2, sort_keys=True)
