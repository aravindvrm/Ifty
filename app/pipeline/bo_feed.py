from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.clients.sec_client import SecClient
from app.config import get_settings
from app.ingest.sec_13dg import Sec13DGIngestionService
from app.ingest.sec_13dg import SUPPORTED_FORMS as SUPPORTED_13DG_FORMS
from app.pipeline.bo_discovery import Sec13DGIndexDiscoveryService
from app.pipeline.universe import ManagerUniverseService
from app.resolution.security_resolver import SecurityResolverService


@dataclass
class Daily13DGUpdateSummary:
    managers_scanned: int
    filings_upserted: int
    events_inserted: int
    bo_events_mapped: int
    bo_batches: list[dict]
    universe_refreshed: int
    discovered_ciks: int
    skipped_unchanged_ciks: int
    discovery_mode: str
    discovery_files_attempted: int
    discovery_files_scanned: int
    discovery_filings_matched: int
    ingestion_failures: int
    retention_cleanup: dict[str, int | str]
    label_cleanup: dict[str, int]


@dataclass
class RetentionCleanupSummary:
    keep_days: int
    cutoff_date: str
    events_before: int
    events_after: int
    events_deleted: int
    filings_before: int
    filings_after: int
    filings_deleted: int


_FORM_VALUES_13DG = [
    "SC 13D",
    "SC 13D/A",
    "SC 13G",
    "SC 13G/A",
    "SCHEDULE 13D",
    "SCHEDULE 13D/A",
    "SCHEDULE 13G",
    "SCHEDULE 13G/A",
    "13D",
    "13D/A",
    "13G",
    "13G/A",
]


def _normalize_yyyy_mm_dd(raw: object) -> str | None:
    value = str(raw or "").strip()
    if len(value) >= 10:
        value = value[:10]
    parts = value.split("-")
    if len(parts) != 3:
        return None
    yyyy, mm, dd = parts
    if len(yyyy) != 4 or len(mm) != 2 or len(dd) != 2:
        return None
    if not (yyyy.isdigit() and mm.isdigit() and dd.isdigit()):
        return None
    return value


def cleanup_13dg_history(db: Session, keep_days: int, analyze: bool = True) -> RetentionCleanupSummary:
    keep_days = max(1, int(keep_days))
    cutoff_date = (datetime.now(UTC).date() - timedelta(days=keep_days)).isoformat()
    params = {"forms": [x.upper() for x in _FORM_VALUES_13DG], "cutoff_date": cutoff_date}

    events_before = int(
        db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM beneficial_ownership_events b
                JOIN filings f ON f.filing_id = b.filing_id
                WHERE UPPER(COALESCE(f.form_type, '')) IN :forms
                """
            ).bindparams(bindparam("forms", expanding=True)),
            params,
        ).scalar()
        or 0
    )
    filings_before = int(
        db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM filings f
                WHERE UPPER(COALESCE(f.form_type, '')) IN :forms
                """
            ).bindparams(bindparam("forms", expanding=True)),
            params,
        ).scalar()
        or 0
    )

    events_deleted = int(
        db.execute(
            text(
                """
                DELETE FROM beneficial_ownership_events
                WHERE filing_id IN (
                  SELECT filing_id
                  FROM filings
                  WHERE UPPER(COALESCE(form_type, '')) IN :forms
                    AND SUBSTR(COALESCE(filed_at, ''), 1, 10) < :cutoff_date
                )
                """
            ).bindparams(bindparam("forms", expanding=True)),
            params,
        ).rowcount
        or 0
    )
    filings_deleted = int(
        db.execute(
            text(
                """
                DELETE FROM filings
                WHERE UPPER(COALESCE(form_type, '')) IN :forms
                  AND SUBSTR(COALESCE(filed_at, ''), 1, 10) < :cutoff_date
                  AND NOT EXISTS (
                    SELECT 1
                    FROM beneficial_ownership_events b
                    WHERE b.filing_id = filings.filing_id
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM holdings_13f h
                    WHERE h.filing_id = filings.filing_id
                  )
                """
            ).bindparams(bindparam("forms", expanding=True)),
            params,
        ).rowcount
        or 0
    )
    if analyze:
        db.execute(text("ANALYZE beneficial_ownership_events"))
        db.execute(text("ANALYZE filings"))
    db.commit()

    events_after = int(
        db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM beneficial_ownership_events b
                JOIN filings f ON f.filing_id = b.filing_id
                WHERE UPPER(COALESCE(f.form_type, '')) IN :forms
                """
            ).bindparams(bindparam("forms", expanding=True)),
            params,
        ).scalar()
        or 0
    )
    filings_after = int(
        db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM filings f
                WHERE UPPER(COALESCE(f.form_type, '')) IN :forms
                """
            ).bindparams(bindparam("forms", expanding=True)),
            params,
        ).scalar()
        or 0
    )

    return RetentionCleanupSummary(
        keep_days=keep_days,
        cutoff_date=cutoff_date,
        events_before=events_before,
        events_after=events_after,
        events_deleted=events_deleted,
        filings_before=filings_before,
        filings_after=filings_after,
        filings_deleted=filings_deleted,
    )


def sanitize_13dg_event_labels(db: Session, analyze: bool = True) -> dict[str, int]:
    params = {"forms": [x.upper() for x in _FORM_VALUES_13DG]}
    bad_cusip_rows = int(
        db.execute(
            text(
                """
                UPDATE beneficial_ownership_events
                SET
                  cusip_raw = NULL,
                  security_id = NULL,
                  mapping_status = 'UNMAPPED',
                  mapping_confidence = NULL
                WHERE bo_event_id IN (
                  SELECT b.bo_event_id
                  FROM beneficial_ownership_events b
                  JOIN filings f ON f.filing_id = b.filing_id
                  WHERE UPPER(COALESCE(f.form_type, '')) IN :forms
                    AND b.cusip_raw IS NOT NULL
                    AND TRIM(b.cusip_raw) <> ''
                    AND (
                      UPPER(TRIM(b.cusip_raw)) LIKE 'ITEM%'
                      OR UPPER(TRIM(b.cusip_raw)) LIKE ')%'
                      OR UPPER(TRIM(b.cusip_raw)) LIKE '(%'
                      OR UPPER(TRIM(b.cusip_raw)) LIKE 'CUSIP%'
                      OR UPPER(TRIM(b.cusip_raw)) LIKE '% VARIABLE %'
                      OR UPPER(TRIM(b.cusip_raw)) LIKE '% REMARKET%'
                      OR LENGTH(UPPER(REPLACE(REPLACE(REPLACE(REPLACE(TRIM(b.cusip_raw), ' ', ''), '-', ''), '.', ''), '/', ''))) < 9
                    )
                )
                """
            ).bindparams(bindparam("forms", expanding=True)),
            params,
        ).rowcount
        or 0
    )
    bad_issuer_rows = int(
        db.execute(
            text(
                """
                UPDATE beneficial_ownership_events
                SET issuer_name_raw = NULL
                WHERE issuer_name_raw IS NOT NULL
                  AND TRIM(issuer_name_raw) <> ''
                  AND filing_id IN (
                    SELECT f.filing_id
                    FROM filings f
                    WHERE UPPER(COALESCE(f.form_type, '')) IN :forms
                  )
                  AND (
                    UPPER(TRIM(issuer_name_raw)) LIKE ')%'
                    OR UPPER(TRIM(issuer_name_raw)) LIKE '(%'
                    OR UPPER(TRIM(issuer_name_raw)) LIKE 'ITEM%'
                    OR UPPER(TRIM(issuer_name_raw)) LIKE 'CUSIP%'
                    OR UPPER(TRIM(issuer_name_raw)) LIKE '% VARIABLE %'
                    OR UPPER(TRIM(issuer_name_raw)) LIKE '% REMARKET%'
                  )
                """
            ).bindparams(bindparam("forms", expanding=True)),
            params,
        ).rowcount
        or 0
    )
    if analyze and (bad_cusip_rows > 0 or bad_issuer_rows > 0):
        db.execute(text("ANALYZE beneficial_ownership_events"))
    db.commit()
    return {
        "bad_cusip_rows": bad_cusip_rows,
        "bad_issuer_rows": bad_issuer_rows,
    }


class Daily13DGFeedUpdateService:
    def __init__(self, db: Session, sec_client: SecClient) -> None:
        self.db = db
        self.sec_client = sec_client

    def _existing_latest_13dg_filed_dates(self, ciks: list[str]) -> dict[str, str]:
        if not ciks:
            return {}
        rows = self.db.execute(
            text(
                """
                SELECT cik, MAX(filed_at) AS latest_filed_at
                FROM filings
                WHERE cik IN :ciks
                  AND form_type IN :forms
                GROUP BY cik
                """
            ).bindparams(bindparam("ciks", expanding=True), bindparam("forms", expanding=True)),
            {"ciks": ciks, "forms": list(SUPPORTED_13DG_FORMS)},
        ).mappings().all()
        out: dict[str, str] = {}
        for row in rows:
            cik = str(row.get("cik") or "").strip()
            if not cik:
                continue
            normalized = _normalize_yyyy_mm_dd(row.get("latest_filed_at"))
            if normalized:
                out[cik.zfill(10)] = normalized
        return out

    def run(
        self,
        *,
        top_n: int = 300,
        per_manager_limit: int = 20,
        resolve_limit: int | None = 6,
        refresh_universe_first: bool = False,
        refresh_universe_if_empty: bool = True,
        include_universe: bool = False,
        index_discovery_mode: str = "daily",
        discovery_days: int = 21,
        discovery_quarters: int = 6,
        discovery_max_ciks: int = 300,
        skip_unchanged_ciks: bool = True,
        retention_days: int | None = None,
        apply_retention: bool = True,
    ) -> Daily13DGUpdateSummary:
        settings = get_settings()
        effective_retention_days = int(retention_days or settings.retention_13dg_days)
        universe = ManagerUniverseService(db=self.db)
        universe_refreshed = 0

        if include_universe and refresh_universe_first:
            universe.refresh_top_n(top_n=top_n)
            universe_refreshed = 1

        universe_ciks: list[str] = universe.get_active_ciks() if include_universe else []
        if include_universe and not universe_ciks and refresh_universe_if_empty:
            universe.refresh_top_n(top_n=top_n)
            universe_refreshed = 1
            universe_ciks = universe.get_active_ciks()

        discovery_summary = Sec13DGIndexDiscoveryService(sec_client=self.sec_client).discover(
            mode=index_discovery_mode,
            days=discovery_days,
            quarters=discovery_quarters,
            max_ciks=discovery_max_ciks,
        )
        discovered_ciks = [str(cik).zfill(10) for cik in (discovery_summary.ciks or []) if str(cik).strip()]
        discovered_latest_by_cik = {
            str(cik).zfill(10): dt
            for cik, dt in (discovery_summary.latest_filed_date_by_cik or {}).items()
            if str(cik).strip()
        }

        ciks: list[str] = []
        seen: set[str] = set()
        for raw_cik in universe_ciks + discovered_ciks:
            cik = str(raw_cik or "").strip()
            if not cik:
                continue
            cik = cik.zfill(10)
            if cik in seen:
                continue
            ciks.append(cik)
            seen.add(cik)

        skipped_unchanged_ciks = 0
        if skip_unchanged_ciks and ciks and discovered_latest_by_cik:
            existing_latest = self._existing_latest_13dg_filed_dates(ciks=list(discovered_latest_by_cik.keys()))
            filtered: list[str] = []
            for cik in ciks:
                candidate_date = discovered_latest_by_cik.get(cik)
                existing_date = existing_latest.get(cik)
                if candidate_date and existing_date and existing_date >= candidate_date:
                    skipped_unchanged_ciks += 1
                    continue
                filtered.append(cik)
            ciks = filtered

        ingest_service = Sec13DGIngestionService(db=self.db, sec_client=self.sec_client)
        filings_upserted = 0
        events_inserted = 0
        ingestion_failures = 0
        for cik in ciks:
            try:
                result = ingest_service.ingest_for_cik(cik=cik, limit=per_manager_limit)
                filings_upserted += int(result.filings_upserted or 0)
                events_inserted += int(result.events_inserted or 0)
            except Exception:
                ingestion_failures += 1
                self.db.rollback()
                continue

        label_cleanup = sanitize_13dg_event_labels(db=self.db, analyze=False)

        resolver = SecurityResolverService(db=self.db)
        bo_events_mapped, bo_batches = resolver.resolve_13dg(limit=resolve_limit)
        retention_summary: dict[str, int | str] = {
            "keep_days": effective_retention_days,
            "cutoff_date": "",
            "events_before": 0,
            "events_after": 0,
            "events_deleted": 0,
            "filings_before": 0,
            "filings_after": 0,
            "filings_deleted": 0,
        }
        if apply_retention and effective_retention_days > 0:
            cleanup = cleanup_13dg_history(db=self.db, keep_days=effective_retention_days, analyze=True)
            retention_summary = {
                "keep_days": cleanup.keep_days,
                "cutoff_date": cleanup.cutoff_date,
                "events_before": cleanup.events_before,
                "events_after": cleanup.events_after,
                "events_deleted": cleanup.events_deleted,
                "filings_before": cleanup.filings_before,
                "filings_after": cleanup.filings_after,
                "filings_deleted": cleanup.filings_deleted,
            }

        return Daily13DGUpdateSummary(
            managers_scanned=len(ciks),
            filings_upserted=filings_upserted,
            events_inserted=events_inserted,
            bo_events_mapped=int(bo_events_mapped or 0),
            bo_batches=bo_batches or [],
            universe_refreshed=universe_refreshed,
            discovered_ciks=len(discovered_ciks),
            skipped_unchanged_ciks=skipped_unchanged_ciks,
            discovery_mode=discovery_summary.mode,
            discovery_files_attempted=int(discovery_summary.files_attempted or 0),
            discovery_files_scanned=int(discovery_summary.files_scanned or 0),
            discovery_filings_matched=int(discovery_summary.filings_matched or 0),
            ingestion_failures=ingestion_failures,
            retention_cleanup=retention_summary,
            label_cleanup=label_cleanup,
        )
