from __future__ import annotations

from sqlalchemy import text

from app.analytics.aggregates import AggregateRefreshService
from app.resolution.security_resolver import SecurityResolverService


def test_security_resolver_maps_13f_and_13dg(db_session):
    db_session.execute(text("INSERT INTO managers (manager_id, cik, manager_name) VALUES (1, '0000000001', 'Mgr')"))
    db_session.execute(text("INSERT INTO issuers (issuer_id, issuer_name) VALUES (1, 'Issuer A')"))
    db_session.execute(
        text(
            """
            INSERT INTO securities (security_id, issuer_id, instrument_type, security_name, is_active)
            VALUES (1, 1, 'EQUITY', 'Issuer A Common', 1)
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO security_identifiers (security_id, id_type, id_value, mic, valid_from, valid_to, source_system, confidence)
            VALUES
              (1, 'CUSIP', '11111111', NULL, '2020-01-01', NULL, 'TEST', 1.0),
              (1, 'TICKER', 'ISSA', 'XNAS', '2020-01-01', NULL, 'TEST', 1.0)
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO filings (filing_id, accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment)
            VALUES
              (1, 'acc-13f-1', '13F-HR', '0000000001', 1, '2025-11-14', '2025-09-30', 'https://x', 0),
              (2, 'acc-13d-1', 'SC 13D', '0000000001', 1, '2025-11-20', '2025-11-19', 'https://y', 0)
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO holdings_13f (
              holding_13f_id, filing_id, manager_id, security_id, report_date,
              issuer_name_raw, class_title_raw, cusip_raw, ticker_raw, value_usd_thousands, shares, share_type, row_hash, mapping_status
            ) VALUES (
              1, 1, 1, NULL, '2025-09-30',
              'Issuer A', 'COM', '11111111', NULL, 100, 10, 'SH', 'h1', 'UNMAPPED'
            )
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO beneficial_ownership_events (
              bo_event_id, filing_id, manager_id, security_id, report_date,
              event_type, percent_beneficial_owned, cusip_raw, ticker_raw, mapping_status
            ) VALUES (
              1, 2, 1, NULL, '2025-11-19',
              'NEW_5PCT', 6.0, '11111111', NULL, 'UNMAPPED'
            )
            """
        )
    )
    db_session.commit()

    service = SecurityResolverService(db_session)
    summary = service.resolve_all()
    assert summary.holdings_mapped == 1
    assert summary.bo_events_mapped == 1

    holding = db_session.execute(
        text("SELECT security_id, mapping_status, mapping_confidence FROM holdings_13f WHERE holding_13f_id = 1")
    ).mappings().first()
    event = db_session.execute(
        text(
            "SELECT security_id, mapping_status, mapping_confidence FROM beneficial_ownership_events WHERE bo_event_id = 1"
        )
    ).mappings().first()
    assert holding is not None and event is not None
    assert holding["security_id"] == 1
    assert holding["mapping_status"] == "MAPPED"
    assert event["security_id"] == 1
    assert event["mapping_status"] == "MAPPED"


def test_security_resolver_bootstraps_from_unmapped_holdings(db_session):
    db_session.execute(text("INSERT INTO managers (manager_id, cik, manager_name) VALUES (1, '0000000001', 'Mgr')"))
    db_session.execute(
        text(
            """
            INSERT INTO filings (filing_id, accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment)
            VALUES (1, 'acc-bootstrap-1', '13F-HR', '0000000001', 1, '2025-11-14', '2025-09-30', 'https://x', 0)
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO holdings_13f (
              holding_13f_id, filing_id, manager_id, security_id, report_date,
              issuer_name_raw, class_title_raw, cusip_raw, ticker_raw, value_usd_thousands, shares, share_type, row_hash, mapping_status
            ) VALUES (
              1, 1, 1, NULL, '2025-09-30',
              'Issuer Bootstrap', 'COM', '99999999', NULL, 100, 10, 'SH', 'boot1', 'UNMAPPED'
            )
            """
        )
    )
    db_session.commit()

    service = SecurityResolverService(db_session)
    summary = service.resolve_all()
    assert summary.holdings_mapped == 1

    created = db_session.execute(
        text(
            """
            SELECT h.security_id, h.mapping_status, si.id_type, si.id_value
            FROM holdings_13f h
            JOIN security_identifiers si ON si.security_id = h.security_id
            WHERE h.holding_13f_id = 1
            """
        )
    ).mappings().first()
    assert created is not None
    assert created["mapping_status"] == "MAPPED"
    assert created["id_type"] == "CUSIP"
    assert created["id_value"] == "99999999"


def test_aggregate_refresh_populates_tables(db_session):
    db_session.execute(
        text(
            """
            INSERT INTO managers (manager_id, cik, manager_name) VALUES
              (1, '0000000001', 'Alpha'),
              (2, '0000000002', 'Beta')
            """
        )
    )
    db_session.execute(text("INSERT INTO issuers (issuer_id, issuer_name) VALUES (1, 'Issuer A')"))
    db_session.execute(
        text(
            """
            INSERT INTO securities (security_id, issuer_id, instrument_type, security_name, is_active)
            VALUES (1, 1, 'EQUITY', 'Issuer A Common', 1)
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO filings (filing_id, accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment)
            VALUES
              (1, 'acc-agg-1', '13F-HR', '0000000001', 1, '2025-08-14', '2025-06-30', 'https://a', 0),
              (2, 'acc-agg-2', '13F-HR', '0000000001', 1, '2025-11-14', '2025-09-30', 'https://b', 0)
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO holdings_13f (
              holding_13f_id, filing_id, manager_id, security_id, report_date,
              issuer_name_raw, class_title_raw, cusip_raw, value_usd_thousands, shares,
              share_type, row_hash, mapping_status, mapping_confidence
            ) VALUES
              (1, 1, 1, 1, '2025-06-30', 'Issuer A', 'COM', '11111111', 100, 10, 'SH', 'x1', 'MAPPED', 1.0),
              (2, 1, 2, 1, '2025-06-30', 'Issuer A', 'COM', '11111111', 200, 20, 'SH', 'x2', 'MAPPED', 1.0),
              (3, 2, 1, 1, '2025-09-30', 'Issuer A', 'COM', '11111111', 140, 14, 'SH', 'x3', 'MAPPED', 1.0),
              (4, 2, 2, 1, '2025-09-30', 'Issuer A', 'COM', '11111111', 160, 16, 'SH', 'x4', 'MAPPED', 1.0)
            """
        )
    )
    db_session.commit()

    service = AggregateRefreshService(db_session)
    summary = service.refresh_all()
    assert summary.security_rows == 2
    assert summary.manager_rows == 4

    sec_row = db_session.execute(
        text(
            """
            SELECT holders_count, total_shares, top10_shares, top10_pct
            FROM agg_security_quarter
            WHERE security_id = 1 AND report_date = '2025-09-30'
            """
        )
    ).mappings().first()
    assert sec_row is not None
    assert sec_row["holders_count"] == 2
    assert sec_row["total_shares"] == 30.0
    assert sec_row["top10_shares"] == 30.0
    assert sec_row["top10_pct"] == 1.0

    mgr_row = db_session.execute(
        text(
            """
            SELECT positions_count, new_positions_count, exited_positions_count, turnover_ratio
            FROM agg_manager_quarter
            WHERE manager_id = 1 AND report_date = '2025-09-30'
            """
        )
    ).mappings().first()
    assert mgr_row is not None
    assert mgr_row["positions_count"] == 1
    assert mgr_row["new_positions_count"] == 0
    assert mgr_row["exited_positions_count"] == 0
    assert float(mgr_row["turnover_ratio"]) > 0.0
