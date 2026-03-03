from __future__ import annotations

import re

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
    body = res.json()
    assert "holdings_mapped" in body
    assert "bo_events_mapped" in body
    assert "holdings_batches" in body
    assert "bo_batches" in body
    assert isinstance(body["holdings_batches"], list)
    assert isinstance(body["bo_batches"], list)

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


def test_13dg_feed(api_client):
    response = api_client.get("/feeds/13dg?days=800&limit_n=50")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["rows"] >= 1
    assert body["rows"][0]["event_type"] == "NEW_5PCT"
    assert body["rows"][0]["ticker"] == "AAPL"


def test_13dg_feed_filters(api_client):
    response = api_client.get("/feeds/13dg?days=800&limit_n=50&ticker=AAPL&manager_key=1&event_type=NEW_5PCT")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["rows"] >= 1
    assert all((x.get("ticker") or "") == "AAPL" for x in body["rows"])
    assert all(int(x.get("manager_id") or 0) == 1 for x in body["rows"])


def test_13dg_feed_text_search(api_client):
    response = api_client.get("/feeds/13dg?days=800&limit_n=50&q=alpha")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["rows"] >= 1
    assert all("alpha" in (x.get("manager_name") or "").lower() for x in body["rows"])


def test_13dg_feed_form_type_filter(api_client):
    response = api_client.get("/feeds/13dg?days=800&limit_n=50&form_type=SC%2013D")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["rows"] >= 1
    assert all((x.get("form_type") or "").upper() == "SC 13D" for x in body["rows"])


def test_accumulation_history(api_client):
    response = api_client.get("/screeners/accumulation-history?limit_n=10")
    assert response.status_code == 200
    body = response.json()
    assert len(body["quarters"]) >= 2
    assert len(body["rows"]) >= 1
    assert body["rows"][0]["series"]


def test_home_overview_filters_non_equity_like_movers(test_engine):
    from app.dependencies import get_db
    from app.main import app
    from fastapi.testclient import TestClient

    with test_engine.begin() as conn:
        conn.execute(text("INSERT INTO issuers (issuer_id, issuer_name) VALUES (1, 'Apple Inc.'), (2, 'Option Issuer')"))
        conn.execute(
            text(
                """
                INSERT INTO securities (security_id, issuer_id, instrument_type, security_name, is_active)
                VALUES
                  (1, 1, 'EQUITY', 'Apple Inc.', 1),
                  (2, 2, 'EQUITY', 'UBER 0 12/15/25', 1)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO security_identifiers (security_id, id_type, id_value, mic, valid_from, valid_to, source_system, confidence)
                VALUES
                  (1, 'TICKER', 'AAPL', 'XNAS', '2000-01-01', NULL, 'TEST', 1.0),
                  (2, 'TICKER', 'UBER 0 12/15/25', 'XNAS', '2000-01-01', NULL, 'TEST', 1.0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO agg_security_quarter
                  (security_id, report_date, holders_count, total_shares, total_value_usd, top10_shares, top10_pct)
                VALUES
                  (1, '2025-09-30', 30, 1000, 1000000, 600, 0.60),
                  (1, '2025-12-31', 31, 900, 950000, 580, 0.61),
                  (2, '2025-09-30', 20, 900000, 3000000, 700000, 0.78),
                  (2, '2025-12-31', 18, 100000, 2000000, 70000, 0.80)
                """
            )
        )

    def _override_get_db():
        with Session(bind=test_engine) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            res = client.get("/home/overview?quarters_n=8&top_n=20&scatter_n=0")
            assert res.status_code == 200
            body = res.json()
            distributed = body["top_movers"]["distributed"]
            assert distributed
            assert all(re.fullmatch(r"^[A-Z]{1,6}(?:\\.[A-Z]{1,2})?$", (r.get("ticker") or "")) for r in distributed)
            assert all("12/15/25" not in (r.get("security_name") or "") for r in distributed)
    finally:
        app.dependency_overrides.clear()


def test_security_search(api_client):
    response = api_client.get("/security/search?q=Apple")
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Apple"
    assert len(body["rows"]) >= 1


def test_security_search_excludes_derivatives_by_default(test_engine):
    from app.dependencies import get_db
    from app.main import app
    from fastapi.testclient import TestClient

    with test_engine.begin() as conn:
        conn.execute(text("INSERT INTO issuers (issuer_id, issuer_name) VALUES (1, 'APPLE INC'), (2, 'OPTION ISSUER')"))
        conn.execute(
            text(
                """
                INSERT INTO securities (security_id, issuer_id, instrument_type, security_name, is_active)
                VALUES
                  (1, 1, 'EQUITY', 'APPLE INC', 1),
                  (2, 2, 'OPTION', 'PUT 100 APPLE INC COM EXP 01-19-24@170.000 OPTION ROOT= AAPL', 1),
                  (3, 1, 'EQUITY', 'GOOGLE INC', 1)
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

    def _override_get_db():
        with Session(bind=test_engine) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            res = client.get("/security/search?q=AAPL&limit_n=50")
            assert res.status_code == 200
            rows = res.json()["rows"]
            assert any(r["ticker"] == "AAPL" for r in rows)
            assert all("OPTION ROOT" not in (r["security_name"] or "") for r in rows)
            assert all((r["ticker"] or "").strip() != "" for r in rows)
    finally:
        app.dependency_overrides.clear()


def test_security_page_excludes_option_holdings_rows(test_engine):
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
                VALUES
                  (1, 'TICKER', 'AAPL', 'XNAS', '2000-01-01', NULL, 'TEST', 1.0),
                  (1, 'CUSIP', '037833100', NULL, '2000-01-01', NULL, 'TEST', 1.0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO filings (filing_id, accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment)
                VALUES (1, 'acc-opt-1', '13F-HR', '0000000001', 1, '2025-11-14', '2025-09-30', 'https://x', 0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO holdings_13f (
                  holding_13f_id, filing_id, manager_id, security_id, report_date,
                  issuer_name_raw, class_title_raw, cusip_raw, value_usd_thousands, shares,
                  share_type, option_type, row_hash, mapping_status, mapping_confidence
                ) VALUES
                  (1, 1, 1, 1, '2025-09-30', 'Apple Inc.', 'COM', '037833100', 1000, 100, 'SH', NULL, 'opt-h1', 'MAPPED', 1.0),
                  (2, 1, 1, 1, '2025-09-30', 'Apple Inc.', 'COM', '037833100', 5000, 500, 'SH', 'PUT', 'opt-h2', 'MAPPED', 1.0)
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
            assert body["ownership_summary"]["holders_count"] == 1
            assert body["ownership_summary"]["total_shares"] == 100.0
            assert body["active_positions"][0]["shares"] == 100.0
    finally:
        app.dependency_overrides.clear()


def test_ops_endpoints(api_client):
    response = api_client.get("/ops/manager-universe?limit_n=10")
    assert response.status_code == 200
    assert "rows" in response.json()

    response = api_client.get("/ops/api-usage?days=7&limit_n=10")
    assert response.status_code == 200
    body = response.json()
    assert "summary" in body
    assert "recent" in body


def test_ops_pipeline_runs_latest_parses_metrics(test_engine):
    from app.dependencies import get_db
    from app.main import app
    from fastapi.testclient import TestClient

    with test_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO pipeline_run_events (run_id, event_ts, stage, status, message, metrics_json)
                VALUES
                  (:run_id, :event_ts, :stage, :status, :message, :metrics_json)
                """
            ),
            [
                {
                    "run_id": "run-test-1",
                    "event_ts": "2026-01-01 00:00:00",
                    "stage": "start",
                    "status": "INFO",
                    "message": "start",
                    "metrics_json": '{"x":1}',
                },
                {
                    "run_id": "run-test-1",
                    "event_ts": "2026-01-01 00:00:01",
                    "stage": "done",
                    "status": "INFO",
                    "message": "done",
                    "metrics_json": '{"y":2}',
                },
            ],
        )

    def _override_get_db():
        with Session(bind=test_engine) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            res = client.get("/ops/pipeline-runs/latest")
            assert res.status_code == 200
            body = res.json()
            assert body["run_id"] == "run-test-1"
            assert body["current"]["stage"] == "done"
            assert body["current"]["metrics"]["y"] == 2
            assert len(body["events"]) == 2
            assert body["events"][0]["metrics"]["x"] == 1
    finally:
        app.dependency_overrides.clear()


def test_update_13dg_feed_job(test_engine):
    from app.dependencies import get_db, get_sec_client
    from app.main import app
    from fastapi.testclient import TestClient

    class _FakeSecClient13DGRoute:
        def get_submissions(self, cik: str):
            return {
                "name": "Alpha Capital",
                "filings": {
                    "recent": {
                        "form": ["SC 13D"],
                        "accessionNumber": ["0000000000-26-000001"],
                        "filingDate": ["2026-02-28"],
                        "reportDate": ["2026-02-27"],
                        "primaryDocument": ["bo13d.txt"],
                    }
                },
            }

        def download_text(self, url: str):
            return "ITEM 11. Percent of class represented by amount in Row (11): 5.6% CUSIP 037833100"

    with test_engine.begin() as conn:
        conn.execute(text("INSERT INTO managers (manager_id, cik, manager_name) VALUES (1, '0000000001', 'Alpha Capital')"))
        conn.execute(text("INSERT INTO manager_universe (manager_id, rank, total_value_usd, as_of_report_date, source, is_active) VALUES (1, 1, 1, '2025-12-31', 'TEST', 1)"))
        conn.execute(text("INSERT INTO issuers (issuer_id, issuer_name) VALUES (1, 'Apple Inc.')"))
        conn.execute(
            text(
                """
                INSERT INTO securities (security_id, issuer_id, instrument_type, security_name, is_active)
                VALUES (1, 1, 'EQUITY', 'Apple Inc.', 1)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO security_identifiers (security_id, id_type, id_value, mic, valid_from, valid_to, source_system, confidence)
                VALUES
                  (1, 'CUSIP', '037833100', NULL, '2000-01-01', NULL, 'TEST', 1.0),
                  (1, 'TICKER', 'AAPL', 'XNAS', '2000-01-01', NULL, 'TEST', 1.0)
                """
            )
        )

    def _override_get_db():
        with Session(bind=test_engine) as session:
            yield session

    def _override_get_sec_client():
        return _FakeSecClient13DGRoute()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_sec_client] = _override_get_sec_client
    try:
            with TestClient(app) as client:
                res = client.post(
                    "/jobs/update-13dg-feed?top_n=10&per_manager_limit=5&resolve_limit=6&refresh_universe_if_empty=0&include_universe=1"
                )
            assert res.status_code == 200
            body = res.json()
            assert body["managers_scanned"] == 1
            assert body["events_inserted"] == 1
            assert body["bo_events_mapped"] >= 1
    finally:
        app.dependency_overrides.clear()


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


def test_security_page_stitches_quarters_across_cusip_linked_security_ids(test_engine):
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
                VALUES
                  (1, 1, 'EQUITY', 'Apple Common A', 1),
                  (2, 1, 'EQUITY', 'Apple Common B', 1)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO security_identifiers (security_id, id_type, id_value, mic, valid_from, valid_to, source_system, confidence)
                VALUES
                  (1, 'TICKER', 'AAPL', 'XNAS', '2000-01-01', NULL, 'TEST', 1.0),
                  (1, 'CUSIP', '037833100', NULL, '2000-01-01', NULL, 'TEST', 1.0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO filings (filing_id, accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment)
                VALUES
                  (1, 'acc-stitch-1', '13F-HR', '0000000001', 1, '2025-08-14', '2025-06-30', 'https://x', 0),
                  (2, 'acc-stitch-2', '13F-HR', '0000000001', 1, '2025-11-14', '2025-09-30', 'https://y', 0)
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
                  (1,1,1,2,'2025-06-30','Apple Inc.','COM','037833100',100,100,'SH','st1','MAPPED',1.0),
                  (2,2,1,1,'2025-09-30','Apple Inc.','COM','037833100',130,130,'SH','st2','MAPPED',1.0)
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
            dates = {row["report_date"] for row in body["net_change_last_4q"]}
            assert "2025-06-30" in dates
            assert "2025-09-30" in dates
    finally:
        app.dependency_overrides.clear()
