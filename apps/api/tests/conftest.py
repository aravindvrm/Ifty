from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def test_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("API_DB_URL", db_url)
    monkeypatch.setenv("SEC_USER_AGENT", "Codex Test codex@example.com")

    from app.config import get_settings
    from app.db import ensure_schema_and_seed

    get_settings.cache_clear()
    engine = create_engine(db_url, future=True)
    ensure_schema_and_seed(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        get_settings.cache_clear()


@pytest.fixture()
def db_session(test_engine):
    with Session(bind=test_engine) as session:
        yield session


@pytest.fixture()
def seed_route_data(test_engine):
    with test_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO managers (manager_id,cik,manager_name,normalized_name)
                VALUES
                  (1,'0000000001','Alpha Capital','ALPHA CAPITAL'),
                  (2,'0000000002','Beta Partners','BETA PARTNERS')
                """
            )
        )
        conn.execute(
            text("INSERT INTO issuers (issuer_id, issuer_name) VALUES (1,'Apple Inc.'), (2,'Microsoft Corp.')")
        )
        conn.execute(
            text(
                """
                INSERT INTO securities (security_id,issuer_id,instrument_type,security_name,is_active)
                VALUES
                  (1,1,'EQUITY','Apple Common',1),
                  (2,2,'EQUITY','Microsoft Common',1)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO security_identifiers (
                  security_id,id_type,id_value,mic,valid_from,valid_to,source_system,confidence
                ) VALUES
                  (1,'TICKER','AAPL','XNAS','2000-01-01',NULL,'TEST',1.0),
                  (2,'TICKER','MSFT','XNAS','2000-01-01',NULL,'TEST',1.0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO filings (filing_id,accession_no,form_type,cik,manager_id,filed_at,period_end_date,sec_url,is_amendment)
                VALUES
                  (1,'0001-0001-0001','13F-HR','0000000001',1,'2025-08-14','2025-06-30','https://example.com/1',0),
                  (2,'0001-0001-0002','13F-HR','0000000001',1,'2025-11-14','2025-09-30','https://example.com/2',0),
                  (3,'0002-0002-0001','13F-HR','0000000002',2,'2025-08-14','2025-06-30','https://example.com/3',0),
                  (4,'0002-0002-0002','13F-HR','0000000002',2,'2025-11-14','2025-09-30','https://example.com/4',0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO filings (filing_id,accession_no,form_type,cik,manager_id,filed_at,period_end_date,sec_url,is_amendment)
                VALUES
                  (5,'0001-13d-0001','SC 13D','0000000001',1,'2025-10-10','2025-10-09','https://example.com/5',0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO holdings_13f (
                  holding_13f_id, filing_id, manager_id, security_id, report_date, issuer_name_raw, class_title_raw,
                  cusip_raw, value_usd_thousands, shares, share_type, row_hash, mapping_status, mapping_confidence
                ) VALUES
                  (1,1,1,1,'2025-06-30','Apple Inc.','COM','037833100',1000,100,'SH','h1','MAPPED',1.0),
                  (2,1,1,2,'2025-06-30','Microsoft Corp.','COM','594918104',500,50,'SH','h2','MAPPED',1.0),
                  (3,2,1,1,'2025-09-30','Apple Inc.','COM','037833100',2000,200,'SH','h3','MAPPED',1.0),
                  (4,3,2,1,'2025-06-30','Apple Inc.','COM','037833100',800,80,'SH','h4','MAPPED',1.0),
                  (5,4,2,1,'2025-09-30','Apple Inc.','COM','037833100',600,60,'SH','h5','MAPPED',1.0)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO beneficial_ownership_events (
                  bo_event_id, filing_id, manager_id, security_id, report_date, event_type,
                  percent_beneficial_owned, shares_beneficial_owned, cusip_raw, issuer_name_raw, ticker_raw,
                  mapping_status, mapping_confidence
                ) VALUES (
                  1,5,1,1,'2025-10-09','NEW_5PCT',
                  5.5,NULL,'037833100','Apple Inc.','AAPL',
                  'MAPPED',1.0
                )
                """
            )
        )


@pytest.fixture()
def api_client(test_engine, seed_route_data):
    from fastapi.testclient import TestClient

    from app.dependencies import get_db
    from app.main import app

    def _override_get_db():
        with Session(bind=test_engine) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
