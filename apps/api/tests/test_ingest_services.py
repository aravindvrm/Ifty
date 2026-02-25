from __future__ import annotations

from sqlalchemy import text

from app.ingest.sec_13dg import Sec13DGIngestionService
from app.ingest.sec_13f import Sec13FIngestionService


class FakeSecClient13F:
    def get_submissions(self, cik):
        return {
            "name": "Mock Manager",
            "filings": {
                "recent": {
                    "form": ["13F-HR"],
                    "accessionNumber": ["0001000000-26-000001"],
                    "filingDate": ["2026-02-14"],
                    "reportDate": ["2025-12-31"],
                    "primaryDocument": ["primary.htm"],
                }
            },
        }

    def get_filing_index(self, cik, accession_no_dashless):
        return {"directory": {"item": [{"name": "form13fInfoTable.xml"}]}}

    def download_text(self, url):
        return """<?xml version="1.0" encoding="UTF-8"?>
<informationTable>
  <infoTable>
    <nameOfIssuer>Issuer A</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>11111111</cusip>
    <value>123</value>
    <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <votingAuthority><Sole>100</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>Issuer B</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>22222222</cusip>
    <value>456</value>
    <shrsOrPrnAmt><sshPrnamt>200</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <votingAuthority><Sole>200</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
</informationTable>
"""


class FakeSecClient13DG:
    def get_submissions(self, cik):
        return {
            "name": "Mock Activist",
            "filings": {
                "recent": {
                    "form": ["SC 13D"],
                    "accessionNumber": ["0002000000-26-000001"],
                    "filingDate": ["2026-02-20"],
                    "reportDate": ["2026-02-19"],
                    "primaryDocument": ["sc13d.htm"],
                }
            },
        }

    def download_text(self, url):
        return "CUSIP 037833100 Item 11. Percent of class represented by amount in row (11) 6.3%"


def test_ingest_13f_mocked_client(db_session):
    service = Sec13FIngestionService(db=db_session, sec_client=FakeSecClient13F())
    result = service.ingest_for_cik("0001000000", limit=5)

    assert result.filings_upserted == 1
    assert result.holdings_inserted == 2

    counts = db_session.execute(
        text("SELECT (SELECT COUNT(*) FROM filings) AS filings, (SELECT COUNT(*) FROM holdings_13f) AS holdings")
    ).mappings().first()
    assert counts is not None
    assert counts["filings"] == 1
    assert counts["holdings"] == 2


def test_ingest_13dg_mocked_client(db_session):
    service = Sec13DGIngestionService(db=db_session, sec_client=FakeSecClient13DG())
    result = service.ingest_for_cik("0002000000", limit=5)

    assert result.filings_upserted == 1
    assert result.events_inserted == 1

    row = db_session.execute(
        text(
            """
            SELECT event_type, percent_beneficial_owned, cusip_raw
            FROM beneficial_ownership_events
            LIMIT 1
            """
        )
    ).mappings().first()
    assert row is not None
    assert row["event_type"] == "NEW_5PCT"
    assert row["percent_beneficial_owned"] == 6.3
    assert row["cusip_raw"] == "037833100"

