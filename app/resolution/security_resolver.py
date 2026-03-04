from __future__ import annotations

from dataclasses import dataclass
import time

from sqlalchemy import bindparam, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


@dataclass
class ResolveSummary:
    bootstrap_created: int = 0
    holdings_mapped: int = 0
    bo_events_mapped: int = 0
    holdings_batches: list[dict] | None = None
    bo_batches: list[dict] | None = None


@dataclass
class ResolutionCandidate:
    security_id: int
    confidence: float
    status: str


class SecurityResolverService:
    def __init__(self, db: Session) -> None:
        self.db = db
        bind = getattr(db, "bind", None)
        self._dialect = (bind.dialect.name if bind is not None else "").lower()

    @staticmethod
    def _normalize_cusip(value: str | None) -> str | None:
        if not value:
            return None
        upper_raw = value.upper().strip()
        if (
            upper_raw.startswith("ITEM")
            or upper_raw.startswith("CUSIP")
            or upper_raw.startswith(")")
            or upper_raw.startswith("(")
            or " VARIABLE " in upper_raw
            or " REMARKET" in upper_raw
        ):
            return None
        cleaned = "".join(ch for ch in upper_raw if ch.isalnum())
        if len(cleaned) < 8:
            return None
        if cleaned and not any(ch.isdigit() for ch in cleaned):
            return None
        return cleaned or None

    @staticmethod
    def _normalize_ticker(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.upper().strip().replace(" ", "")
        return cleaned or None

    @staticmethod
    def _is_statement_timeout(exc: Exception) -> bool:
        message = str(exc).lower()
        return "statement timeout" in message or "querycanceled" in message

    def bootstrap_security_master_from_filings(self, limit: int | None = None) -> int:
        limit_n = max(1, int(limit or 5000))
        sample_n = max(500, min(20000, limit_n * 2))

        rows = self.db.execute(
            text(
                """
                SELECT src_type, row_id, cusip_raw, report_date
                FROM (
                  SELECT
                    'H' AS src_type,
                    holding_13f_id AS row_id,
                    cusip_raw,
                    report_date
                  FROM holdings_13f
                  WHERE security_id IS NULL
                    AND cusip_raw IS NOT NULL
                    AND TRIM(cusip_raw) <> ''
                  ORDER BY report_date DESC, holding_13f_id DESC
                  LIMIT :sample_n
                ) h
                UNION ALL
                SELECT src_type, row_id, cusip_raw, report_date
                FROM (
                  SELECT
                    'B' AS src_type,
                    bo_event_id AS row_id,
                    cusip_raw,
                    report_date
                  FROM beneficial_ownership_events
                  WHERE security_id IS NULL
                    AND cusip_raw IS NOT NULL
                    AND TRIM(cusip_raw) <> ''
                  ORDER BY report_date DESC NULLS LAST, bo_event_id DESC
                  LIMIT :sample_n
                ) b
                """
            ),
            {"sample_n": sample_n},
        ).mappings().all()

        if not rows:
            return 0

        def _row_sort_key(r: dict) -> tuple[str, int]:
            report_date = str(r.get("report_date") or "")
            row_id = int(r.get("row_id") or 0)
            return (report_date, row_id)

        candidates: list[str] = []
        seen: set[str] = set()
        for row in sorted(rows, key=_row_sort_key, reverse=True):
            cusip = self._normalize_cusip(row.get("cusip_raw"))
            if not cusip or cusip in seen:
                continue
            seen.add(cusip)
            candidates.append(cusip)
            if len(candidates) >= limit_n:
                break

        if not candidates:
            return 0

        existing_rows = self.db.execute(
            text(
                """
                SELECT id_value
                FROM security_identifiers
                WHERE id_type = 'CUSIP'
                  AND id_value IN :candidates
                """
            ).bindparams(bindparam("candidates", expanding=True)),
            {"candidates": candidates},
        ).all()
        existing = {str(x[0]) for x in existing_rows if x and x[0]}
        missing = [cusip for cusip in candidates if cusip not in existing]
        if not missing:
            return 0

        anchor = self.db.execute(
            text(
                """
                SELECT issuer_id
                FROM issuers
                WHERE issuer_name = 'CUSIP_ANCHOR_ISSUER'
                ORDER BY issuer_id
                LIMIT 1
                """
            )
        ).mappings().first()
        if anchor:
            anchor_issuer_id = int(anchor["issuer_id"])
        else:
            ins_anchor = self.db.execute(
                text(
                    """
                    INSERT INTO issuers (issuer_name, status)
                    VALUES ('CUSIP_ANCHOR_ISSUER', 'ACTIVE')
                    RETURNING issuer_id
                    """
                )
            )
            anchor_issuer_id = int(ins_anchor.scalar_one())

        created = 0
        for cusip in missing:
            sec_row = self.db.execute(
                text(
                    """
                    INSERT INTO securities (
                      issuer_id, instrument_type, security_name, share_class, active_from, is_active
                    ) VALUES (
                      :issuer_id, 'EQUITY', :security_name, NULL, '1900-01-01', 1
                    )
                    RETURNING security_id
                    """
                ),
                {"issuer_id": anchor_issuer_id, "security_name": f"CUSIP {cusip}"},
            ).mappings().first()
            security_id = int(sec_row["security_id"])

            ins = self.db.execute(
                text(
                    """
                    INSERT INTO security_identifiers (
                      security_id, id_type, id_value, mic, valid_from, valid_to, source_system, confidence
                    ) VALUES (
                      :security_id, 'CUSIP', :cusip, NULL, '1900-01-01', NULL, 'AUTO_BOOTSTRAP_CUSIP', 1.0
                    )
                    ON CONFLICT (id_type, id_value) DO NOTHING
                    """
                ),
                {"security_id": security_id, "cusip": cusip},
            )
            created += max(int(ins.rowcount or 0), 0)

        self.db.commit()
        return created

    def _identifier_lookup(
        self,
        id_type: str,
        id_value: str,
        as_of_date: str,
    ) -> ResolutionCandidate | None:
        if id_type == "CUSIP":
            value_norm = self._normalize_cusip(id_value)
            compare_expr = "UPPER(REPLACE(REPLACE(REPLACE(id_value, ' ', ''), '-', ''), '.', ''))"
        else:
            value_norm = self._normalize_ticker(id_value)
            compare_expr = "UPPER(REPLACE(id_value, ' ', ''))"
        if not value_norm:
            return None

        row = self.db.execute(
            text(
                f"""
                SELECT security_id, confidence
                FROM security_identifiers
                WHERE id_type = :id_type
                  AND {compare_expr} = :id_value_norm
                  AND date(:as_of_date) >= date(valid_from)
                  AND (valid_to IS NULL OR date(:as_of_date) < date(valid_to))
                ORDER BY confidence DESC, valid_from DESC
                LIMIT 1
                """
            ),
            {"id_type": id_type, "id_value_norm": value_norm, "as_of_date": as_of_date},
        ).mappings().first()
        if row:
            conf = float(row["confidence"] or 1.0)
            return ResolutionCandidate(
                security_id=int(row["security_id"]),
                confidence=conf,
                status="MAPPED" if conf >= 0.8 else "MAPPED_LOW_CONF",
            )
        return None

    def _historical_alias_lookup(
        self,
        id_type: str,
        id_value: str,
        as_of_date: str,
        base_confidence: float,
    ) -> ResolutionCandidate | None:
        if id_type == "CUSIP":
            value_norm = self._normalize_cusip(id_value)
            compare_expr = "UPPER(REPLACE(REPLACE(REPLACE(id_value, ' ', ''), '-', ''), '.', ''))"
        else:
            value_norm = self._normalize_ticker(id_value)
            compare_expr = "UPPER(REPLACE(id_value, ' ', ''))"
        if not value_norm:
            return None

        row = self.db.execute(
            text(
                f"""
                SELECT security_id
                FROM security_identifiers
                WHERE id_type = :id_type
                  AND {compare_expr} = :id_value_norm
                ORDER BY valid_from DESC
                LIMIT 1
                """
            ),
            {"id_type": id_type, "id_value_norm": value_norm},
        ).mappings().first()
        if not row:
            return None

        from_security_id = int(row["security_id"])
        link = self.db.execute(
            text(
                """
                SELECT to_security_id, confidence
                FROM security_alias_links
                WHERE from_security_id = :from_security_id
                  AND date(effective_date) <= date(:as_of_date)
                ORDER BY effective_date DESC, confidence DESC
                LIMIT 1
                """
            ),
            {"from_security_id": from_security_id, "as_of_date": as_of_date},
        ).mappings().first()
        if link:
            conf = min(base_confidence, float(link["confidence"] or base_confidence))
            return ResolutionCandidate(
                security_id=int(link["to_security_id"]),
                confidence=conf,
                status="MAPPED" if conf >= 0.8 else "MAPPED_LOW_CONF",
            )
        return None

    def _issuer_class_lookup(self, issuer_name_raw: str | None, class_title_raw: str | None) -> ResolutionCandidate | None:
        if not issuer_name_raw:
            return None
        row = self.db.execute(
            text(
                """
                SELECT security_id
                FROM securities
                WHERE UPPER(COALESCE(security_name, '')) = UPPER(:issuer_name_raw)
                  AND (
                    :class_title_raw IS NULL
                    OR UPPER(COALESCE(share_class, '')) = UPPER(:class_title_raw)
                    OR COALESCE(share_class, '') = ''
                  )
                ORDER BY security_id DESC
                LIMIT 1
                """
            ),
            {"issuer_name_raw": issuer_name_raw.strip(), "class_title_raw": (class_title_raw or "").strip() or None},
        ).mappings().first()
        if row:
            return ResolutionCandidate(security_id=int(row["security_id"]), confidence=0.55, status="MAPPED_LOW_CONF")
        return None

    def _resolve(
        self,
        cusip_raw: str | None,
        ticker_raw: str | None,
        as_of_date: str,
        issuer_name_raw: str | None = None,
        class_title_raw: str | None = None,
    ) -> ResolutionCandidate | None:
        if cusip_raw:
            direct = self._identifier_lookup(id_type="CUSIP", id_value=cusip_raw, as_of_date=as_of_date)
            if direct:
                return direct
            hist = self._historical_alias_lookup(
                id_type="CUSIP",
                id_value=cusip_raw,
                as_of_date=as_of_date,
                base_confidence=0.9,
            )
            if hist:
                return hist

        if ticker_raw:
            direct = self._identifier_lookup(id_type="TICKER", id_value=ticker_raw, as_of_date=as_of_date)
            if direct:
                adj = min(direct.confidence, 0.75)
                return ResolutionCandidate(
                    security_id=direct.security_id,
                    confidence=adj,
                    status="MAPPED" if adj >= 0.8 else "MAPPED_LOW_CONF",
                )
            hist = self._historical_alias_lookup(
                id_type="TICKER",
                id_value=ticker_raw,
                as_of_date=as_of_date,
                base_confidence=0.6,
            )
            if hist:
                return hist

        return self._issuer_class_lookup(issuer_name_raw=issuer_name_raw, class_title_raw=class_title_raw)

    def resolve_13f(self, limit: int | None = None) -> tuple[int, list[dict]]:
        if self._dialect == "postgresql":
            quarter_limit = max(1, min(int(limit or 8), 24))
            initial_batch_size = 10000
            min_batch_size = 500
            quarters = [
                str(r[0])
                for r in self.db.execute(
                    text(
                        """
                        SELECT period_end_date
                        FROM filings
                        WHERE form_type IN ('13F-HR', '13F-HR/A')
                          AND period_end_date IS NOT NULL
                        GROUP BY period_end_date
                        ORDER BY period_end_date DESC
                        LIMIT :quarter_limit
                        """
                    ),
                    {"quarter_limit": quarter_limit},
                ).all()
                if r and r[0] is not None
            ]
            total_updated = 0
            batches: list[dict] = []
            for report_date in quarters:
                eligible = int(
                    self.db.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM holdings_13f
                            WHERE security_id IS NULL
                              AND report_date = :report_date
                              AND cusip_raw IS NOT NULL
                              AND TRIM(cusip_raw) <> ''
                              AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g'))) >= 8
                              AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                            """
                        ),
                        {"report_date": report_date},
                    ).scalar()
                    or 0
                )
                t0 = time.perf_counter()
                updated = 0
                chunk_count = 0
                batch_size = initial_batch_size
                while True:
                    try:
                        batch_updated = int(
                            self.db.execute(
                                text(
                                    """
                                    WITH raw AS (
                                      SELECT
                                        h.ctid AS row_ctid,
                                        SUBSTRING(
                                          UPPER(REGEXP_REPLACE(TRIM(h.cusip_raw), '[^A-Z0-9]', '', 'g'))
                                          FROM 1 FOR 9
                                        ) AS norm_cusip
                                      FROM holdings_13f h
                                      WHERE h.security_id IS NULL
                                        AND h.report_date = :report_date
                                        AND h.cusip_raw IS NOT NULL
                                        AND TRIM(h.cusip_raw) <> ''
                                        AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(h.cusip_raw), '[^A-Z0-9]', '', 'g'))) >= 8
                                        AND UPPER(REGEXP_REPLACE(TRIM(h.cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                                      ORDER BY h.holding_13f_id ASC
                                      LIMIT :batch_size
                                    ),
                                    candidate AS (
                                      SELECT
                                        raw.row_ctid,
                                        si.security_id AS target_security_id
                                      FROM raw
                                      JOIN security_identifiers si
                                        ON si.id_type = 'CUSIP'
                                       AND si.id_value = raw.norm_cusip
                                    ),
                                    upd AS (
                                      UPDATE holdings_13f h
                                      SET security_id = c.target_security_id,
                                          mapping_status = 'MAPPED',
                                          mapping_confidence = 1.0
                                      FROM candidate c
                                      WHERE h.ctid = c.row_ctid
                                      RETURNING 1
                                    )
                                    SELECT COUNT(*) FROM upd
                                    """
                                ),
                                {"report_date": report_date, "batch_size": batch_size},
                            ).scalar()
                            or 0
                        )
                    except OperationalError as exc:
                        self.db.rollback()
                        if not self._is_statement_timeout(exc):
                            raise
                        if batch_size <= min_batch_size:
                            raise
                        batch_size = max(min_batch_size, batch_size // 2)
                        print(
                            "resolve_13f_batch_reduce "
                            f"report_date={report_date} "
                            f"new_batch_size={batch_size}"
                        )
                        continue
                    self.db.commit()
                    if batch_updated <= 0:
                        break
                    updated += batch_updated
                    chunk_count += 1
                total_updated += updated
                runtime_ms = int((time.perf_counter() - t0) * 1000)
                batch = {
                    "report_date": report_date,
                    "eligible_rows": eligible,
                    "updated_rows": updated,
                    "chunk_count": chunk_count,
                    "runtime_ms": runtime_ms,
                }
                batches.append(batch)
                print(
                    "resolve_13f_batch "
                    f"report_date={report_date} "
                    f"eligible_rows={eligible} "
                    f"updated_rows={updated} "
                    f"chunk_count={chunk_count} "
                    f"runtime_ms={runtime_ms}"
                )
            return total_updated, batches

        sql = """
            SELECT holding_13f_id, cusip_raw, ticker_raw, report_date, issuer_name_raw, class_title_raw
            FROM holdings_13f
            WHERE security_id IS NULL
            ORDER BY report_date DESC, holding_13f_id DESC
        """
        if limit is not None:
            sql += " LIMIT :limit_n"
            rows = self.db.execute(text(sql), {"limit_n": limit}).mappings().all()
        else:
            rows = self.db.execute(text(sql)).mappings().all()

        mapped = 0
        for row in rows:
            candidate = self._resolve(
                cusip_raw=row["cusip_raw"],
                ticker_raw=row["ticker_raw"],
                as_of_date=row["report_date"],
                issuer_name_raw=row["issuer_name_raw"],
                class_title_raw=row["class_title_raw"],
            )
            if not candidate:
                continue
            self.db.execute(
                text(
                    """
                    UPDATE holdings_13f
                    SET security_id = :security_id,
                        mapping_status = :mapping_status,
                        mapping_confidence = :mapping_confidence
                    WHERE holding_13f_id = :holding_13f_id
                    """
                ),
                {
                    "security_id": candidate.security_id,
                    "mapping_status": candidate.status,
                    "mapping_confidence": candidate.confidence,
                    "holding_13f_id": int(row["holding_13f_id"]),
                },
            )
            mapped += 1
        self.db.commit()
        return mapped, []

    def resolve_13dg(self, limit: int | None = None) -> tuple[int, list[dict]]:
        if self._dialect == "postgresql":
            quarter_limit = max(1, min(int(limit or 8), 32))
            initial_batch_size = 5000
            min_batch_size = 250
            quarters = [
                r[0]
                for r in self.db.execute(
                    text(
                        """
                        SELECT report_date
                        FROM beneficial_ownership_events
                        WHERE report_date IS NOT NULL
                        GROUP BY report_date
                        ORDER BY report_date DESC
                        LIMIT :quarter_limit
                        """
                    ),
                    {"quarter_limit": quarter_limit},
                ).all()
            ]
            total_updated = 0
            batches: list[dict] = []
            for report_date in quarters:
                if report_date is None:
                    eligible = int(
                        self.db.execute(
                            text(
                                """
                                SELECT COUNT(*)
                                FROM beneficial_ownership_events
                                WHERE security_id IS NULL
                                  AND report_date IS NULL
                                  AND cusip_raw IS NOT NULL
                                  AND TRIM(cusip_raw) <> ''
                                  AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g'))) = 9
                                  AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                                  AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^ITEM'
                                  AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^CUSIP'
                                """
                            )
                        ).scalar()
                        or 0
                    )
                else:
                    p = {"report_date": report_date}
                    eligible = int(
                        self.db.execute(
                            text(
                                """
                                SELECT COUNT(*)
                                FROM beneficial_ownership_events
                                WHERE security_id IS NULL
                                  AND report_date = :report_date
                                  AND cusip_raw IS NOT NULL
                                  AND TRIM(cusip_raw) <> ''
                                  AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g'))) = 9
                                  AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                                  AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^ITEM'
                                  AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^CUSIP'
                                """
                            ),
                            p,
                        ).scalar()
                        or 0
                    )
                t0 = time.perf_counter()
                updated = 0
                chunk_count = 0
                batch_size = initial_batch_size
                if report_date is None:
                    while True:
                        try:
                            batch_updated = int(
                                self.db.execute(
                                    text(
                                        """
                                        WITH raw AS (
                                          SELECT
                                            b.ctid AS row_ctid,
                                            SUBSTRING(
                                              UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g'))
                                              FROM 1 FOR 9
                                            ) AS norm_cusip
                                          FROM beneficial_ownership_events b
                                          WHERE b.security_id IS NULL
                                            AND b.report_date IS NULL
                                            AND b.cusip_raw IS NOT NULL
                                            AND TRIM(b.cusip_raw) <> ''
                                            AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g'))) = 9
                                            AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                                            AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^ITEM'
                                            AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^CUSIP'
                                          ORDER BY b.bo_event_id ASC
                                          LIMIT :batch_size
                                        ),
                                        candidate AS (
                                          SELECT
                                            raw.row_ctid,
                                            si.security_id AS target_security_id
                                          FROM raw
                                          JOIN security_identifiers si
                                            ON si.id_type = 'CUSIP'
                                           AND si.id_value = raw.norm_cusip
                                        ),
                                        upd AS (
                                          UPDATE beneficial_ownership_events b
                                          SET security_id = c.target_security_id,
                                              mapping_status = 'MAPPED',
                                              mapping_confidence = 1.0
                                          FROM candidate c
                                          WHERE b.ctid = c.row_ctid
                                          RETURNING 1
                                        )
                                        SELECT COUNT(*) FROM upd
                                        """
                                    ),
                                    {"batch_size": batch_size},
                                ).scalar()
                                or 0
                            )
                        except OperationalError as exc:
                            self.db.rollback()
                            if not self._is_statement_timeout(exc):
                                raise
                            if batch_size <= min_batch_size:
                                raise
                            batch_size = max(min_batch_size, batch_size // 2)
                            print(
                                "resolve_13dg_batch_reduce "
                                "report_date=NULL "
                                f"new_batch_size={batch_size}"
                            )
                            continue
                        self.db.commit()
                        if batch_updated <= 0:
                            break
                        updated += batch_updated
                        chunk_count += 1
                else:
                    p = {"report_date": report_date}
                    while True:
                        try:
                            batch_updated = int(
                                self.db.execute(
                                    text(
                                        """
                                        WITH raw AS (
                                          SELECT
                                            b.ctid AS row_ctid,
                                            SUBSTRING(
                                              UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g'))
                                              FROM 1 FOR 9
                                            ) AS norm_cusip
                                          FROM beneficial_ownership_events b
                                          WHERE b.security_id IS NULL
                                            AND b.report_date = :report_date
                                            AND b.cusip_raw IS NOT NULL
                                            AND TRIM(b.cusip_raw) <> ''
                                            AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g'))) = 9
                                            AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                                            AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^ITEM'
                                            AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^CUSIP'
                                          ORDER BY b.bo_event_id ASC
                                          LIMIT :batch_size
                                        ),
                                        candidate AS (
                                          SELECT
                                            raw.row_ctid,
                                            si.security_id AS target_security_id
                                          FROM raw
                                          JOIN security_identifiers si
                                            ON si.id_type = 'CUSIP'
                                           AND si.id_value = raw.norm_cusip
                                        ),
                                        upd AS (
                                          UPDATE beneficial_ownership_events b
                                          SET security_id = c.target_security_id,
                                              mapping_status = 'MAPPED',
                                              mapping_confidence = 1.0
                                          FROM candidate c
                                          WHERE b.ctid = c.row_ctid
                                          RETURNING 1
                                        )
                                        SELECT COUNT(*) FROM upd
                                        """
                                    ),
                                    {"report_date": report_date, "batch_size": batch_size},
                                ).scalar()
                                or 0
                            )
                        except OperationalError as exc:
                            self.db.rollback()
                            if not self._is_statement_timeout(exc):
                                raise
                            if batch_size <= min_batch_size:
                                raise
                            batch_size = max(min_batch_size, batch_size // 2)
                            print(
                                "resolve_13dg_batch_reduce "
                                f"report_date={report_date} "
                                f"new_batch_size={batch_size}"
                            )
                            continue
                        self.db.commit()
                        if batch_updated <= 0:
                            break
                        updated += batch_updated
                        chunk_count += 1
                total_updated += updated
                runtime_ms = int((time.perf_counter() - t0) * 1000)
                batch = {
                    "report_date": report_date,
                    "eligible_rows": eligible,
                    "updated_rows": updated,
                    "chunk_count": chunk_count,
                    "runtime_ms": runtime_ms,
                }
                batches.append(batch)
                print(
                    "resolve_13dg_batch "
                    f"report_date={report_date} "
                    f"eligible_rows={eligible} "
                    f"updated_rows={updated} "
                    f"chunk_count={chunk_count} "
                    f"runtime_ms={runtime_ms}"
                )
            return total_updated, batches

        sql = """
            SELECT bo_event_id, cusip_raw, ticker_raw, report_date, issuer_name_raw
            FROM beneficial_ownership_events
            WHERE security_id IS NULL
            ORDER BY report_date DESC, bo_event_id DESC
        """
        if limit is not None:
            sql += " LIMIT :limit_n"
            rows = self.db.execute(text(sql), {"limit_n": limit}).mappings().all()
        else:
            rows = self.db.execute(text(sql)).mappings().all()

        mapped = 0
        for row in rows:
            candidate = self._resolve(
                cusip_raw=row["cusip_raw"],
                ticker_raw=row["ticker_raw"],
                as_of_date=row["report_date"],
                issuer_name_raw=row["issuer_name_raw"],
            )
            if not candidate:
                continue
            self.db.execute(
                text(
                    """
                    UPDATE beneficial_ownership_events
                    SET security_id = :security_id,
                        mapping_status = :mapping_status,
                        mapping_confidence = :mapping_confidence
                    WHERE bo_event_id = :bo_event_id
                    """
                ),
                {
                    "security_id": candidate.security_id,
                    "mapping_status": candidate.status,
                    "mapping_confidence": candidate.confidence,
                    "bo_event_id": int(row["bo_event_id"]),
                },
            )
            mapped += 1
        self.db.commit()
        return mapped, []

    def resolve_all(self, limit: int | None = None) -> ResolveSummary:
        if self._dialect == "postgresql":
            self.db.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_identifiers_type_value
                    ON security_identifiers (id_type, id_value)
                    """
                )
            )
            self.db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_13f_report_date
                    ON holdings_13f (report_date)
                    """
                )
            )
            self.db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_13f_security_report_date
                    ON holdings_13f (security_id, report_date)
                    """
                )
            )
            self.db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_ident_idtype_idvalue
                    ON security_identifiers (id_type, id_value)
                    """
                )
            )
            self.db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_13f_unmapped_cusip
                    ON holdings_13f (report_date DESC, holding_13f_id DESC)
                    WHERE security_id IS NULL AND cusip_raw IS NOT NULL
                    """
                )
            )
            self.db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_bo_unmapped_cusip
                    ON beneficial_ownership_events (report_date DESC, bo_event_id DESC)
                    WHERE security_id IS NULL AND cusip_raw IS NOT NULL
                    """
                )
            )
            self.db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_ident_cusip_norm
                    ON security_identifiers (
                      UPPER(REGEXP_REPLACE(id_value, '[^A-Z0-9]', '', 'g')),
                      valid_from,
                      valid_to
                    )
                    WHERE id_type = 'CUSIP'
                    """
                )
            )
            self.db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_13f_cusip_norm
                    ON holdings_13f (UPPER(REGEXP_REPLACE(cusip_raw, '[^A-Z0-9]', '', 'g')), report_date)
                    WHERE cusip_raw IS NOT NULL
                    """
                )
            )
            self.db.commit()

        bootstrap_created = 0
        try:
            bootstrap_created = self.bootstrap_security_master_from_filings(limit=limit)
        except OperationalError as exc:
            self.db.rollback()
            message = str(exc).lower()
            if "statement timeout" in message or "querycanceled" in message:
                print("bootstrap_security_master skipped reason=statement_timeout")
            else:
                raise
        holdings_mapped, holdings_batches = self.resolve_13f(limit=limit)
        bo_events_mapped, bo_batches = self.resolve_13dg(limit=limit)
        return ResolveSummary(
            bootstrap_created=bootstrap_created,
            holdings_mapped=holdings_mapped,
            bo_events_mapped=bo_events_mapped,
            holdings_batches=holdings_batches,
            bo_batches=bo_batches,
        )
