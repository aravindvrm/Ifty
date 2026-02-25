from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def test_health(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_security_page_aapl(api_client):
    response = api_client.get("/security/AAPL")
    assert response.status_code == 200
    body = response.json()

    assert body["security_id"] == 1
    assert body["ticker"] == "AAPL"
    assert body["latest_quarter"] == "2025-09-30"
    assert len(body["top_holders"]) == 2
    assert body["top_holders"][0]["manager_name"] == "Alpha Capital"
    assert body["top_holders"][0]["shares"] == 200.0


def test_manager_page_1(api_client):
    response = api_client.get("/manager/1")
    assert response.status_code == 200
    body = response.json()

    assert body["manager"]["manager_name"] == "Alpha Capital"
    assert body["latest_quarter"] == "2025-09-30"
    assert len(body["top_positions"]) == 1
    assert body["top_positions"][0]["security_id"] == 1
    assert body["top_positions"][0]["shares"] == 200.0
    assert body["new_positions"] == []
    assert len(body["exited_positions"]) == 1
    assert body["exited_positions"][0]["security_id"] == 2


def test_accumulation_screener(api_client):
    response = api_client.get(
        "/screeners/accumulation",
        params={"curr_q": "2025-09-30", "prev_q": "2025-06-30", "limit_n": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["curr_q"] == "2025-09-30"
    assert body["prev_q"] == "2025-06-30"
    assert len(body["rows"]) == 2

    top_row = body["rows"][0]
    assert top_row["security_id"] == 1
    assert top_row["security_name"] == "Apple Common"
    assert top_row["net_holder_count"] == 0
    assert top_row["net_shares"] == 80.0

    security_ids = {row["security_id"] for row in body["rows"]}
    assert security_ids == {1, 2}


def test_job_endpoints(api_client):
    res = api_client.post("/jobs/resolve-mappings")
    assert res.status_code == 200
    assert "holdings_mapped" in res.json()
    assert "bo_events_mapped" in res.json()

    res = api_client.post("/jobs/refresh-aggregates")
    assert res.status_code == 200
    assert "security_rows" in res.json()
    assert "manager_rows" in res.json()


def test_security_events_feed(api_client):
    response = api_client.get("/security/AAPL/events")
    assert response.status_code == 200
    body = response.json()
    assert body["security_id"] == 1
    assert len(body["rows"]) == 1
    assert body["rows"][0]["event_type"] == "NEW_5PCT"


def test_accumulation_history(api_client):
    response = api_client.get("/screeners/accumulation-history?limit_n=10")
    assert response.status_code == 200
    body = response.json()
    assert len(body["quarters"]) >= 2
    assert len(body["rows"]) >= 1
    assert body["rows"][0]["series"]


def test_security_search(api_client):
    response = api_client.get("/security/search?q=Apple")
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Apple"
    assert len(body["rows"]) >= 1


def test_sync_tickers_job_endpoint(test_engine):
    class _FakeSecClient:
        def get_company_tickers_exchange(self):
            return {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
            }

    from app.dependencies import get_db, get_sec_client
    from app.main import app
    from fastapi.testclient import TestClient

    with test_engine.begin() as conn:
        conn.execute(text("INSERT INTO managers (manager_id, cik, manager_name) VALUES (1, '0000000001', 'Alpha')"))
        conn.execute(text("INSERT INTO issuers (issuer_id, issuer_name) VALUES (1, 'Apple Inc.')"))
        conn.execute(
            text(
                """
                INSERT INTO securities (security_id, issuer_id, instrument_type, security_name, is_active, active_from)
                VALUES (1, 1, 'EQUITY', 'Apple Inc.', 1, '2020-01-01')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO filings (filing_id, accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment)
                VALUES (1, 'acc-sync-1', '13F-HR', '0000000001', 1, '2025-11-14', '2025-09-30', 'https://x', 0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO holdings_13f (
                  holding_13f_id, filing_id, manager_id, security_id, report_date,
                  issuer_name_raw, class_title_raw, cusip_raw, value_usd_thousands, shares,
                  share_type, row_hash, mapping_status, mapping_confidence
                ) VALUES (
                  1, 1, 1, 1, '2025-09-30',
                  'Apple Inc.', 'COM', '037833100', 600000, 1000,
                  'SH', 'synch1', 'MAPPED', 1.0
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO manager_universe (manager_id, rank, total_value_usd, as_of_report_date, source, is_active)
                VALUES (1, 1, 600000000, '2025-09-30', 'TEST', 1)
                """
            )
        )

    def _override_get_db():
        with Session(bind=test_engine) as session:
            yield session

    def _override_get_sec_client():
        return _FakeSecClient()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_sec_client] = _override_get_sec_client
    try:
        with TestClient(app) as client:
            res = client.post(
                "/jobs/sync-tickers?recent_quarters=4&min_holders=1&min_total_value_usd=1&universe_only=1"
            )
            assert res.status_code == 200
            body = res.json()
            assert body["scanned"] == 1
            assert body["matched"] == 1
            assert body["inserted"] == 1
    finally:
        app.dependency_overrides.clear()


def test_security_page_aggregates_duplicate_rows(test_engine):
    from app.dependencies import get_db
    from app.main import app
    from fastapi.testclient import TestClient

    with test_engine.begin() as conn:
        conn.execute(text("INSERT INTO managers (manager_id, cik, manager_name) VALUES (1, '0000000001', 'Alpha')"))
        conn.execute(text("INSERT INTO issuers (issuer_id, issuer_name) VALUES (1, 'Apple Inc.')"))
        conn.execute(
            text(
                """
                INSERT INTO securities (security_id, issuer_id, instrument_type, security_name, is_active)
                VALUES (1, 1, 'EQUITY', 'Apple Common', 1)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO security_identifiers (security_id, id_type, id_value, mic, valid_from, valid_to, source_system, confidence)
                VALUES (1, 'TICKER', 'AAPL', 'XNAS', '2000-01-01', NULL, 'TEST', 1.0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO filings (filing_id, accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment)
                VALUES
                  (1, 'acc-dupe-1', '13F-HR', '0000000001', 1, '2025-08-14', '2025-06-30', 'https://x', 0),
                  (2, 'acc-dupe-2', '13F-HR', '0000000001', 1, '2025-11-14', '2025-09-30', 'https://y', 0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO holdings_13f (
                  holding_13f_id, filing_id, manager_id, security_id, report_date,
                  issuer_name_raw, class_title_raw, cusip_raw, value_usd_thousands, shares, share_type, row_hash, mapping_status, mapping_confidence
                ) VALUES
                  (1,1,1,1,'2025-06-30','Apple Inc.','COM','037833100',100,100,'SH','d1','MAPPED',1.0),
                  (2,1,1,1,'2025-06-30','Apple Inc.','COM','037833100',50,50,'SH','d2','MAPPED',1.0),
                  (3,2,1,1,'2025-09-30','Apple Inc.','COM','037833100',120,120,'SH','d3','MAPPED',1.0),
                  (4,2,1,1,'2025-09-30','Apple Inc.','COM','037833100',80,80,'SH','d4','MAPPED',1.0)
                """
            )
        )

    def _override_get_db():
        with Session(bind=test_engine) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            res = client.get("/security/AAPL")
            assert res.status_code == 200
            body = res.json()
            assert len(body["top_holders"]) == 1
            assert body["top_holders"][0]["shares"] == 200.0
            latest_deltas = [x for x in body["net_change_last_4q"] if x["report_date"] == "2025-09-30"]
            assert len(latest_deltas) == 1
            assert latest_deltas[0]["net_change_shares"] == 50.0
    finally:
        app.dependency_overrides.clear()
