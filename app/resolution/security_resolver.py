from __future__ import annotations

from dataclasses import dataclass
import time

from sqlalchemy import text
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

    def bootstrap_security_master_from_filings(self, limit: int | None = None) -> int:
        if self._dialect == "postgresql":
            limit_clause = ""
            params: dict[str, int] = {}
            if limit is not None:
                limit_clause = "LIMIT :limit_n"
                params["limit_n"] = limit

            inserted = self.db.execute(
                text(
                    f"""
                    WITH anchor_issuer AS (
                      INSERT INTO issuers (issuer_name, status)
                      SELECT 'CUSIP_ANCHOR_ISSUER', 'ACTIVE'
                      WHERE NOT EXISTS (
                        SELECT 1 FROM issuers WHERE issuer_name = 'CUSIP_ANCHOR_ISSUER'
                      )
                      RETURNING issuer_id
                    ),
                    issuer_pick AS (
                      SELECT issuer_id FROM anchor_issuer
                      UNION ALL
                      SELECT issuer_id
                      FROM issuers
                      WHERE issuer_name = 'CUSIP_ANCHOR_ISSUER'
                      ORDER BY issuer_id
                      LIMIT 1
                    ),
                    normalized AS (
                      SELECT DISTINCT cusip_norm
                      FROM (
                        SELECT SUBSTRING(UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) FROM 1 FOR 9) AS cusip_norm
                        FROM holdings_13f
                        WHERE cusip_raw IS NOT NULL
                          AND TRIM(cusip_raw) <> ''
                          AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g'))) >= 8
                          AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                        UNION
                        SELECT SUBSTRING(UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) FROM 1 FOR 9) AS cusip_norm
                        FROM beneficial_ownership_events
                        WHERE cusip_raw IS NOT NULL
                          AND TRIM(cusip_raw) <> ''
                          AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g'))) = 9
                          AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                          AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^ITEM'
                          AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^CUSIP'
                      ) all_cusips
                      ORDER BY 1
                      {limit_clause}
                    ),
                    missing AS (
                      SELECT n.cusip_norm
                      FROM normalized n
                      LEFT JOIN security_identifiers si
                        ON si.id_type = 'CUSIP'
                       AND si.id_value = n.cusip_norm
                      WHERE si.identifier_id IS NULL
                    ),
                    alloc AS (
                      SELECT
                        m.cusip_norm,
                        nextval('securities_security_id_seq') AS security_id
                      FROM missing m
                    ),
                    ins_securities AS (
                      INSERT INTO securities (
                        security_id, issuer_id, instrument_type, security_name, share_class, active_from, is_active
                      )
                      SELECT
                        a.security_id,
                        (SELECT issuer_id FROM issuer_pick),
                        'EQUITY',
                        'CUSIP ' || a.cusip_norm,
                        NULL,
                        '1900-01-01',
                        1
                      FROM alloc a
                      RETURNING security_id
                    ),
                    ins_identifiers AS (
                      INSERT INTO security_identifiers (
                        security_id, id_type, id_value, mic, valid_from, valid_to, source_system, confidence
                      )
                      SELECT
                        a.security_id,
                        'CUSIP',
                        a.cusip_norm,
                        NULL,
                        '1900-01-01',
                        NULL,
                        'AUTO_BOOTSTRAP_CUSIP',
                        1.0
                      FROM alloc a
                      ON CONFLICT (id_type, id_value) DO NOTHING
                      RETURNING identifier_id
                    )
                    SELECT COUNT(*) FROM ins_identifiers
                    """
                ),
                params,
            ).scalar()
            self.db.commit()
            return int(inserted or 0)

        sql = """
            SELECT DISTINCT cusip_raw, issuer_name_raw, class_title_raw, report_date
            FROM (
              SELECT cusip_raw, issuer_name_raw, class_title_raw, report_date
              FROM holdings_13f
              WHERE security_id IS NULL
                AND cusip_raw IS NOT NULL
                AND TRIM(cusip_raw) <> ''
              UNION ALL
              SELECT cusip_raw, issuer_name_raw, NULL AS class_title_raw, report_date
              FROM beneficial_ownership_events
              WHERE security_id IS NULL
                AND cusip_raw IS NOT NULL
                AND TRIM(cusip_raw) <> ''
            ) src
            ORDER BY report_date DESC
        """
        if limit is not None:
            sql += " LIMIT :limit_n"
            rows = self.db.execute(text(sql), {"limit_n": limit}).mappings().all()
        else:
            rows = self.db.execute(text(sql)).mappings().all()

        created = 0
        for row in rows:
            cusip = self._normalize_cusip(row["cusip_raw"])
            if not cusip:
                continue
            existing = self.db.execute(
                text(
                    """
                    SELECT security_id
                    FROM security_identifiers
                    WHERE id_type = 'CUSIP'
                      AND UPPER(REPLACE(REPLACE(REPLACE(id_value, ' ', ''), '-', ''), '.', '')) = :cusip
                    ORDER BY valid_from DESC
                    LIMIT 1
                    """
                ),
                {"cusip": cusip},
            ).mappings().first()
            if existing:
                continue

            issuer_name = (row["issuer_name_raw"] or "").strip() or f"UNKNOWN {cusip}"
            issuer = self.db.execute(
                text("SELECT issuer_id FROM issuers WHERE UPPER(issuer_name) = UPPER(:issuer_name) LIMIT 1"),
                {"issuer_name": issuer_name},
            ).mappings().first()
            if issuer:
                issuer_id = int(issuer["issuer_id"])
            else:
                ins_issuer = self.db.execute(
                    text(
                        """
                        INSERT INTO issuers (issuer_name, status)
                        VALUES (:issuer_name, 'ACTIVE')
                        RETURNING issuer_id
                        """
                    ),
                    {"issuer_name": issuer_name},
                )
                issuer_id = int(ins_issuer.scalar_one())

            security_name = issuer_name
            class_title = (row["class_title_raw"] or "").strip() or None
            ins_security = self.db.execute(
                text(
                    """
                    INSERT INTO securities (
                      issuer_id, instrument_type, security_name, share_class, active_from, is_active
                    ) VALUES (
                      :issuer_id, 'EQUITY', :security_name, :share_class, :active_from, 1
                    )
                    RETURNING security_id
                    """
                ),
                {
                    "issuer_id": issuer_id,
                    "security_name": security_name,
                    "share_class": class_title,
                    "active_from": row["report_date"],
                },
            )
            security_id = int(ins_security.scalar_one())

            self.db.execute(
                text(
                    """
                    INSERT INTO security_identifiers (
                      security_id, id_type, id_value, mic, valid_from, valid_to, source_system, confidence
                    ) VALUES (
                      :security_id, 'CUSIP', :cusip, NULL, :valid_from, NULL, 'AUTO_BOOTSTRAP_13F', 0.95
                    )
                    """
                ),
                {
                    "security_id": security_id,
                    "cusip": cusip,
                    "valid_from": row["report_date"],
                },
            )
            created += 1

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
            quarter_sql = """
                SELECT DISTINCT report_date
                FROM holdings_13f
                WHERE security_id IS NULL
                  AND cusip_raw IS NOT NULL
                  AND TRIM(cusip_raw) <> ''
                ORDER BY report_date DESC
            """
            params: dict[str, int] = {}
            if limit is not None:
                quarter_sql += " LIMIT :limit_n"
                params["limit_n"] = limit
            quarters = [str(r[0]) for r in self.db.execute(text(quarter_sql), params).all()]
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
                updated = int(
                    self.db.execute(
                        text(
                            """
                            WITH upd AS (
                              UPDATE holdings_13f h
                              SET security_id = si.security_id,
                                  mapping_status = 'MAPPED',
                                  mapping_confidence = 1.0
                              FROM security_identifiers si
                              WHERE h.security_id IS NULL
                                AND h.report_date = :report_date
                                AND h.cusip_raw IS NOT NULL
                                AND TRIM(h.cusip_raw) <> ''
                                AND UPPER(REGEXP_REPLACE(TRIM(h.cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                                AND si.id_type = 'CUSIP'
                                AND si.id_value = SUBSTRING(
                                  UPPER(REGEXP_REPLACE(TRIM(h.cusip_raw), '[^A-Z0-9]', '', 'g'))
                                  FROM 1 FOR 9
                                )
                              RETURNING 1
                            )
                            SELECT COUNT(*) FROM upd
                            """
                        ),
                        {"report_date": report_date},
                    ).scalar()
                    or 0
                )
                self.db.commit()
                total_updated += updated
                runtime_ms = int((time.perf_counter() - t0) * 1000)
                batch = {
                    "report_date": report_date,
                    "eligible_rows": eligible,
                    "updated_rows": updated,
                    "runtime_ms": runtime_ms,
                }
                batches.append(batch)
                print(
                    "resolve_13f_batch "
                    f"report_date={report_date} "
                    f"eligible_rows={eligible} "
                    f"updated_rows={updated} "
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
            quarter_sql = """
                SELECT DISTINCT report_date
                FROM beneficial_ownership_events
                WHERE security_id IS NULL
                  AND cusip_raw IS NOT NULL
                  AND TRIM(cusip_raw) <> ''
                  AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g'))) = 9
                  AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                  AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^ITEM'
                  AND UPPER(REGEXP_REPLACE(TRIM(cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^CUSIP'
                ORDER BY report_date DESC NULLS LAST
            """
            params: dict[str, int] = {}
            if limit is not None:
                quarter_sql += " LIMIT :limit_n"
                params["limit_n"] = limit
            quarters = [r[0] for r in self.db.execute(text(quarter_sql), params).all()]
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
                if report_date is None:
                    updated = int(
                        self.db.execute(
                            text(
                                """
                                WITH upd AS (
                                  UPDATE beneficial_ownership_events b
                                  SET security_id = si.security_id,
                                      mapping_status = 'MAPPED',
                                      mapping_confidence = 1.0
                                  FROM security_identifiers si
                                  WHERE b.security_id IS NULL
                                    AND b.report_date IS NULL
                                    AND b.cusip_raw IS NOT NULL
                                    AND TRIM(b.cusip_raw) <> ''
                                    AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g'))) = 9
                                    AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                                    AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^ITEM'
                                    AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^CUSIP'
                                    AND si.id_type = 'CUSIP'
                                    AND si.id_value = SUBSTRING(
                                      UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g'))
                                      FROM 1 FOR 9
                                    )
                                  RETURNING 1
                                )
                                SELECT COUNT(*) FROM upd
                                """
                            )
                        ).scalar()
                        or 0
                    )
                else:
                    p = {"report_date": report_date}
                    updated = int(
                        self.db.execute(
                            text(
                                """
                                WITH upd AS (
                                  UPDATE beneficial_ownership_events b
                                  SET security_id = si.security_id,
                                      mapping_status = 'MAPPED',
                                      mapping_confidence = 1.0
                                  FROM security_identifiers si
                                  WHERE b.security_id IS NULL
                                    AND b.report_date = :report_date
                                    AND b.cusip_raw IS NOT NULL
                                    AND TRIM(b.cusip_raw) <> ''
                                    AND LENGTH(UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g'))) = 9
                                    AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) ~ '[0-9]'
                                    AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^ITEM'
                                    AND UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g')) !~ '^CUSIP'
                                    AND si.id_type = 'CUSIP'
                                    AND si.id_value = SUBSTRING(
                                      UPPER(REGEXP_REPLACE(TRIM(b.cusip_raw), '[^A-Z0-9]', '', 'g'))
                                      FROM 1 FOR 9
                                    )
                                  RETURNING 1
                                )
                                SELECT COUNT(*) FROM upd
                                """
                            ),
                            p,
                        ).scalar()
                        or 0
                    )
                self.db.commit()
                total_updated += updated
                runtime_ms = int((time.perf_counter() - t0) * 1000)
                batch = {
                    "report_date": report_date,
                    "eligible_rows": eligible,
                    "updated_rows": updated,
                    "runtime_ms": runtime_ms,
                }
                batches.append(batch)
                print(
                    "resolve_13dg_batch "
                    f"report_date={report_date} "
                    f"eligible_rows={eligible} "
                    f"updated_rows={updated} "
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

        bootstrap_created = self.bootstrap_security_master_from_filings(limit=limit)
        holdings_mapped, holdings_batches = self.resolve_13f(limit=limit)
        bo_events_mapped, bo_batches = self.resolve_13dg(limit=limit)
        return ResolveSummary(
            bootstrap_created=bootstrap_created,
            holdings_mapped=holdings_mapped,
            bo_events_mapped=bo_events_mapped,
            holdings_batches=holdings_batches,
            bo_batches=bo_batches,
        )
