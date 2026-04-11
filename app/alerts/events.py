from __future__ import annotations

from datetime import UTC, date, datetime
import json
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


def _table_exists(db: Session, table_name: str) -> bool:
    dialect = str(
        getattr(getattr(db, "bind", None), "dialect", None).name if getattr(db, "bind", None) else ""
    ).lower()
    if dialect.startswith("postgres"):
        exists = db.execute(
            text("SELECT to_regclass(:relname) IS NOT NULL"),
            {"relname": f"public.{table_name}"},
        ).scalar()
        return bool(exists)
    row = db.execute(
        text(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return bool(row)


def _bo_event_label(event_type: object) -> str:
    value = str(event_type or "").upper()
    if value == "NEW_5PCT":
        return "5% New"
    if value == "AMENDMENT_UP":
        return "Amendment Up"
    if value == "AMENDMENT_DOWN":
        return "Amendment Down"
    if value == "EXIT_5PCT":
        return "Exit < 5%"
    return "Other"


def _fmt_usd_compact(value: object | None) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "-"
    sign = "-" if num < 0 else ""
    mag = abs(num)
    if mag >= 1_000_000_000:
        return f"{sign}${mag / 1_000_000_000:.2f}B"
    if mag >= 1_000_000:
        return f"{sign}${mag / 1_000_000:.2f}M"
    if mag >= 1_000:
        return f"{sign}${mag / 1_000:.1f}K"
    return f"{sign}${mag:.0f}"


def _item_alert_enabled(item: dict[str, Any], *, source: str) -> bool:
    source_u = str(source or "").strip().upper()
    key = "include_13dg" if source_u == "13DG" else "include_insider"
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        return True
    alerts = metadata.get("alerts")
    if not isinstance(alerts, dict):
        return True
    raw = alerts.get(key)
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    text = str(raw).strip().lower()
    if text in {"0", "false", "no", "off"}:
        return False
    if text in {"1", "true", "yes", "on"}:
        return True
    return True


def _normalize_watchlists(
    db: Session,
    *,
    owner_user_id: str,
    only_watchlist_id: str | None,
) -> list[dict[str, Any]]:
    if not _table_exists(db=db, table_name="watchlists"):
        return []
    if not _table_exists(db=db, table_name="watchlist_items"):
        return []

    params: dict[str, object] = {"owner_user_id": owner_user_id}
    where_clauses = ["owner_user_id = :owner_user_id"]
    if only_watchlist_id:
        where_clauses.append("watchlist_id = :watchlist_id")
        params["watchlist_id"] = only_watchlist_id
    rows = db.execute(
        text(
            f"""
            SELECT watchlist_id, name, watchlist_type
            FROM watchlists
            WHERE {' AND '.join(where_clauses)}
            ORDER BY created_at DESC, name ASC
            """
        ),
        params,
    ).mappings().all()
    if not rows:
        return []
    watchlist_ids = [str(row["watchlist_id"]) for row in rows]
    items = db.execute(
        text(
            """
            SELECT watchlist_id, item_type, item_key, item_label, metadata_json
            FROM watchlist_items
            WHERE watchlist_id IN :watchlist_ids
            ORDER BY added_at DESC
            """
        ).bindparams(bindparam("watchlist_ids", expanding=True)),
        {"watchlist_ids": watchlist_ids},
    ).mappings().all()
    by_watchlist: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        metadata: dict[str, Any] | None = None
        metadata_json = item.get("metadata_json")
        if metadata_json:
            try:
                parsed = json.loads(str(metadata_json))
                if isinstance(parsed, dict):
                    metadata = parsed
            except Exception:
                metadata = None
        by_watchlist.setdefault(str(item["watchlist_id"]), []).append(
            {
                "watchlist_id": str(item["watchlist_id"]),
                "item_type": str(item.get("item_type") or "").upper(),
                "item_key": str(item.get("item_key") or ""),
                "item_label": str(item.get("item_label") or ""),
                "metadata": metadata,
            }
        )

    out: list[dict[str, Any]] = []
    for row in rows:
        watchlist_id = str(row["watchlist_id"])
        out.append(
            {
                "watchlist_id": watchlist_id,
                "watchlist_name": str(row["name"] or ""),
                "watchlist_type": str(row["watchlist_type"] or "").upper(),
                "items": by_watchlist.get(watchlist_id, []),
            }
        )
    return out


def _collect_13dg_for_watchlist(
    db: Session,
    *,
    watchlist_id: str,
    watchlist_name: str,
    since_date: str,
    security_keys: set[str],
    manager_ids: set[int],
    item_lookup: dict[str, dict[str, Any]],
    limit_n: int,
) -> list[dict[str, Any]]:
    event_by_id: dict[int, dict[str, Any]] = {}

    if security_keys:
        rows = db.execute(
            text(
                """
                SELECT
                  b.bo_event_id,
                  b.report_date,
                  b.event_type,
                  b.percent_beneficial_owned,
                  b.shares_beneficial_owned,
                  b.manager_id,
                  m.manager_name,
                  COALESCE(
                    (
                      SELECT si.id_value
                      FROM security_identifiers si
                      WHERE si.security_id = b.security_id
                        AND si.id_type = 'TICKER'
                        AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                      ORDER BY si.valid_from DESC
                      LIMIT 1
                    ),
                    UPPER(COALESCE(b.ticker_raw, ''))
                  ) AS ticker,
                  COALESCE(s.security_name, b.issuer_name_raw, '') AS security_name,
                  f.form_type,
                  f.accession_no,
                  f.sec_url
                FROM beneficial_ownership_events b
                JOIN filings f ON f.filing_id = b.filing_id
                LEFT JOIN managers m ON m.manager_id = b.manager_id
                LEFT JOIN securities s ON s.security_id = b.security_id
                WHERE b.report_date >= :since_date
                  AND UPPER(
                    COALESCE(
                      (
                        SELECT si.id_value
                        FROM security_identifiers si
                        WHERE si.security_id = b.security_id
                          AND si.id_type = 'TICKER'
                          AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                        ORDER BY si.valid_from DESC
                        LIMIT 1
                      ),
                      b.ticker_raw,
                      ''
                    )
                  ) IN :security_keys
                  AND (
                    b.security_id IS NULL
                    OR UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
                  )
                ORDER BY b.report_date DESC, b.bo_event_id DESC
                LIMIT :limit_n
                """
            ).bindparams(bindparam("security_keys", expanding=True)),
            {
                "since_date": since_date,
                "security_keys": sorted(security_keys),
                "limit_n": max(1, limit_n),
            },
        ).mappings().all()
        for row in rows:
            event_by_id[int(row["bo_event_id"])] = dict(row)

    if manager_ids:
        rows = db.execute(
            text(
                """
                SELECT
                  b.bo_event_id,
                  b.report_date,
                  b.event_type,
                  b.percent_beneficial_owned,
                  b.shares_beneficial_owned,
                  b.manager_id,
                  m.manager_name,
                  COALESCE(
                    (
                      SELECT si.id_value
                      FROM security_identifiers si
                      WHERE si.security_id = b.security_id
                        AND si.id_type = 'TICKER'
                        AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                      ORDER BY si.valid_from DESC
                      LIMIT 1
                    ),
                    UPPER(COALESCE(b.ticker_raw, ''))
                  ) AS ticker,
                  COALESCE(s.security_name, b.issuer_name_raw, '') AS security_name,
                  f.form_type,
                  f.accession_no,
                  f.sec_url
                FROM beneficial_ownership_events b
                JOIN filings f ON f.filing_id = b.filing_id
                LEFT JOIN managers m ON m.manager_id = b.manager_id
                LEFT JOIN securities s ON s.security_id = b.security_id
                WHERE b.report_date >= :since_date
                  AND b.manager_id IN :manager_ids
                  AND (
                    b.security_id IS NULL
                    OR UPPER(COALESCE(s.instrument_type, '')) NOT IN ('OPTION', 'WARRANT', 'RIGHT')
                  )
                ORDER BY b.report_date DESC, b.bo_event_id DESC
                LIMIT :limit_n
                """
            ).bindparams(bindparam("manager_ids", expanding=True)),
            {
                "since_date": since_date,
                "manager_ids": sorted(manager_ids),
                "limit_n": max(1, limit_n),
            },
        ).mappings().all()
        for row in rows:
            event_by_id[int(row["bo_event_id"])] = dict(row)

    out: list[dict[str, Any]] = []
    for bo_event_id, row in sorted(
        event_by_id.items(),
        key=lambda kv: (str(kv[1].get("report_date") or ""), int(kv[0])),
        reverse=True,
    ):
        ticker = str(row.get("ticker") or "").strip().upper()
        manager_id_raw = row.get("manager_id")
        manager_id = int(manager_id_raw) if manager_id_raw is not None else None
        matched_items: list[dict[str, str]] = []
        if ticker and f"SECURITY:{ticker}" in item_lookup:
            candidate = item_lookup[f"SECURITY:{ticker}"]
            if _item_alert_enabled(candidate, source="13DG"):
                matched_items.append(candidate)
        if manager_id is not None and f"INSTITUTION:{manager_id}" in item_lookup:
            candidate = item_lookup[f"INSTITUTION:{manager_id}"]
            if _item_alert_enabled(candidate, source="13DG"):
                matched_items.append(candidate)
        if not matched_items:
            continue
        security_name = str(row.get("security_name") or "").strip()
        display_name = ticker or security_name or "Unknown Security"
        event_type = str(row.get("event_type") or "").upper() or "OTHER"
        form_type = str(row.get("form_type") or "").strip()
        manager_name = str(row.get("manager_name") or "").strip()
        title = f"{display_name}: {_bo_event_label(event_type)}"
        summary = f"{manager_name or 'Filer'} filed {form_type or '13D/G'} ({event_type})"
        out.append(
            {
                "watchlist_id": watchlist_id,
                "watchlist_name": watchlist_name,
                "event_source": "13DG",
                "event_id": bo_event_id,
                "event_key": f"13dg:{bo_event_id}",
                "event_ts": str(row.get("report_date") or ""),
                "title": title,
                "summary": summary,
                "event_type": event_type,
                "ticker": ticker or None,
                "security_name": security_name or None,
                "manager_id": manager_id,
                "manager_name": manager_name or None,
                "form_type": form_type or None,
                "accession_no": str(row.get("accession_no") or "") or None,
                "sec_url": str(row.get("sec_url") or "") or None,
                "source_path": (
                    f"/explore?type=security&key={ticker}"
                    if ticker
                    else (
                        f"/explore?type=institution&key={manager_id}"
                        if manager_id is not None
                        else "/explore"
                    )
                ),
                "matched_items": matched_items,
            }
        )
    return out


def _collect_insider_for_watchlist(
    db: Session,
    *,
    watchlist_id: str,
    watchlist_name: str,
    since_date: str,
    security_keys: set[str],
    item_lookup: dict[str, dict[str, Any]],
    limit_n: int,
) -> list[dict[str, Any]]:
    if not security_keys:
        return []
    if not _table_exists(db=db, table_name="insider_transactions"):
        return []

    rows = db.execute(
        text(
            """
            SELECT
              t.insider_tx_id,
              t.transaction_date,
              t.signal_type,
              t.transaction_code,
              t.transaction_value_usd,
              t.reporting_owner_name,
              t.reporting_owner_title,
              t.role_group,
              COALESCE(
                (
                  SELECT si.id_value
                  FROM security_identifiers si
                  WHERE si.security_id = t.security_id
                    AND si.id_type = 'TICKER'
                    AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                  ORDER BY si.valid_from DESC
                  LIMIT 1
                ),
                UPPER(COALESCE(t.issuer_trading_symbol, ''))
              ) AS ticker,
              COALESCE(t.issuer_name, '') AS issuer_name,
              f.form_type,
              f.accession_no,
              f.sec_url
            FROM insider_transactions t
            JOIN filings f ON f.filing_id = t.filing_id
            WHERE t.transaction_date >= :since_date
              AND UPPER(
                COALESCE(
                  (
                    SELECT si.id_value
                    FROM security_identifiers si
                    WHERE si.security_id = t.security_id
                      AND si.id_type = 'TICKER'
                      AND (si.valid_to IS NULL OR date('now') < date(si.valid_to))
                    ORDER BY si.valid_from DESC
                    LIMIT 1
                  ),
                  t.issuer_trading_symbol,
                  ''
                )
              ) IN :security_keys
            ORDER BY t.transaction_date DESC, t.insider_tx_id DESC
            LIMIT :limit_n
            """
        ).bindparams(bindparam("security_keys", expanding=True)),
        {
            "since_date": since_date,
            "security_keys": sorted(security_keys),
            "limit_n": max(1, limit_n),
        },
    ).mappings().all()

    out: list[dict[str, Any]] = []
    for row in rows:
        insider_tx_id = int(row["insider_tx_id"])
        ticker = str(row.get("ticker") or "").strip().upper()
        match = item_lookup.get(f"SECURITY:{ticker}")
        if not match or not _item_alert_enabled(match, source="INSIDER"):
            continue
        signal_type = str(row.get("signal_type") or "OTHER").upper()
        tx_code = str(row.get("transaction_code") or "").strip().upper()
        value = row.get("transaction_value_usd")
        issuer_name = str(row.get("issuer_name") or "").strip()
        display_name = ticker or issuer_name or "Unknown Security"
        title = f"{display_name}: Insider {signal_type.replace('_', ' ').title()}"
        summary = (
            f"{str(row.get('reporting_owner_name') or 'Insider').strip()} "
            f"({tx_code or '-'}) {signal_type.replace('_', ' ').lower()} "
            f"for {_fmt_usd_compact(value)}"
        )
        out.append(
            {
                "watchlist_id": watchlist_id,
                "watchlist_name": watchlist_name,
                "event_source": "INSIDER",
                "event_id": insider_tx_id,
                "event_key": f"insider:{insider_tx_id}",
                "event_ts": str(row.get("transaction_date") or ""),
                "title": title,
                "summary": summary,
                "signal_type": signal_type,
                "transaction_code": tx_code or None,
                "transaction_value_usd": value,
                "ticker": ticker or None,
                "issuer_name": issuer_name or None,
                "form_type": str(row.get("form_type") or "") or None,
                "accession_no": str(row.get("accession_no") or "") or None,
                "sec_url": str(row.get("sec_url") or "") or None,
                "source_path": f"/explore?type=security&key={ticker}" if ticker else "/explore",
                "matched_items": [match],
            }
        )
    return out


def collect_watchlist_events(
    db: Session,
    *,
    owner_user_id: str,
    since_date: date | str,
    include_13dg: bool = True,
    include_insider: bool = True,
    only_watchlist_id: str | None = None,
    limit_per_watchlist: int = 150,
) -> list[dict[str, Any]]:
    if isinstance(since_date, date):
        since_date_iso = since_date.isoformat()
    else:
        since_date_iso = str(since_date).strip() or datetime.now(UTC).date().isoformat()

    watchlists = _normalize_watchlists(
        db=db,
        owner_user_id=owner_user_id,
        only_watchlist_id=only_watchlist_id,
    )
    if not watchlists:
        return []

    all_events: list[dict[str, Any]] = []
    for watchlist in watchlists:
        items = list(watchlist.get("items") or [])
        security_keys = {
            str(item.get("item_key") or "").strip().upper()
            for item in items
            if str(item.get("item_type") or "").strip().upper() == "SECURITY"
            and str(item.get("item_key") or "").strip()
        }
        manager_ids: set[int] = set()
        for item in items:
            if str(item.get("item_type") or "").strip().upper() != "INSTITUTION":
                continue
            try:
                manager_ids.add(int(str(item.get("item_key") or "").strip()))
            except ValueError:
                continue
        item_lookup: dict[str, dict[str, Any]] = {}
        for item in items:
            item_type = str(item.get("item_type") or "").strip().upper()
            item_key = str(item.get("item_key") or "").strip().upper() if item_type == "SECURITY" else str(item.get("item_key") or "").strip()
            if not item_type or not item_key:
                continue
            item_lookup[f"{item_type}:{item_key}"] = {
                "item_type": item_type,
                "item_key": item_key,
                "item_label": str(item.get("item_label") or item_key),
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else None,
            }

        if include_13dg and (security_keys or manager_ids):
            all_events.extend(
                _collect_13dg_for_watchlist(
                    db=db,
                    watchlist_id=str(watchlist["watchlist_id"]),
                    watchlist_name=str(watchlist["watchlist_name"]),
                    since_date=since_date_iso,
                    security_keys=security_keys,
                    manager_ids=manager_ids,
                    item_lookup=item_lookup,
                    limit_n=limit_per_watchlist,
                )
            )
        if include_insider and security_keys:
            all_events.extend(
                _collect_insider_for_watchlist(
                    db=db,
                    watchlist_id=str(watchlist["watchlist_id"]),
                    watchlist_name=str(watchlist["watchlist_name"]),
                    since_date=since_date_iso,
                    security_keys=security_keys,
                    item_lookup=item_lookup,
                    limit_n=limit_per_watchlist,
                )
            )

    all_events.sort(
        key=lambda row: (str(row.get("event_ts") or ""), str(row.get("event_source") or ""), str(row.get("event_key") or "")),
        reverse=True,
    )
    return all_events
