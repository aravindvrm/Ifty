from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from app.ingest.sec_13dg import Sec13DGIngestionService
from app.ingest.sec_13f import Sec13FIngestionService
from app.pipeline.bo_discovery import Sec13DGIndexDiscoveryService
from app.pipeline.bo_feed import cleanup_13dg_history


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


class FakeSecClient13FDeepRecent:
    def get_submissions(self, cik):
        n = 80
        forms = ["8-K"] * n
        forms[60] = "13F-HR"
        forms[75] = "13F-HR/A"
        accession = [f"0003000000-26-{i:06d}" for i in range(n)]
        filing_date = ["2026-02-14"] * n
        report_date = ["2025-12-31"] * n
        report_date[75] = "2025-09-30"
        primary_doc = ["primary.htm"] * n
        return {
            "name": "Deep Recent Manager",
            "filings": {
                "recent": {
                    "form": forms,
                    "accessionNumber": accession,
                    "filingDate": filing_date,
                    "reportDate": report_date,
                    "primaryDocument": primary_doc,
                }
            },
        }

    def get_filing_index(self, cik, accession_no_dashless):
        return {"directory": {"item": [{"name": "form13fInfoTable.xml"}]}}

    def download_text(self, url):
        return FakeSecClient13F().download_text(url)


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


class FakeSecClient13DGSchedule:
    def get_submissions(self, cik):
        return {
            "name": "Mock Schedule Activist",
            "filings": {
                "recent": {
                    "form": ["SCHEDULE 13G/A"],
                    "accessionNumber": ["0002100000-26-000001"],
                    "filingDate": ["2026-02-20"],
                    "reportDate": ["2026-02-19"],
                    "primaryDocument": ["sched13ga.htm"],
                }
            },
        }

    def download_text(self, url):
        return (
            "Name of Issuer: Example Therapeutics, Inc. "
            "CUSIP 037833100 Item 11. Percent of class represented by amount in row (11) 7.1%"
        )


class FakeSecClient13DGDeepRecent:
    def get_submissions(self, cik):
        n = 70
        forms = ["8-K"] * n
        forms[52] = "SC 13D"
        accession = [f"0004000000-26-{i:06d}" for i in range(n)]
        filing_date = ["2026-02-20"] * n
        report_date = ["2026-02-19"] * n
        primary_doc = ["sc13d.htm"] * n
        return {
            "name": "Deep Recent Activist",
            "filings": {
                "recent": {
                    "form": forms,
                    "accessionNumber": accession,
                    "filingDate": filing_date,
                    "reportDate": report_date,
                    "primaryDocument": primary_doc,
                }
            },
        }

    def download_text(self, url):
        return "CUSIP 037833100 Item 11. Percent of class represented by amount in row (11) 6.3%"


class FakeSecClient13DGBadCusipWord:
    def get_submissions(self, cik):
        return {
            "name": "Bad Cusip Manager",
            "filings": {
                "recent": {
                    "form": ["SC 13D/A"],
                    "accessionNumber": ["0005000000-26-000001"],
                    "filingDate": ["2026-02-20"],
                    "reportDate": ["2026-02-19"],
                    "primaryDocument": ["sc13d.htm"],
                }
            },
        }

    def download_text(self, url):
        return "CUSIP Number: DOCUMENT Item 11. Percent of class represented by amount in row (11) 5.1%"


class FakeSecClient13DGBadCusipChecksum:
    def get_submissions(self, cik):
        return {
            "name": "Bad Cusip Checksum Manager",
            "filings": {
                "recent": {
                    "form": ["SC 13G/A"],
                    "accessionNumber": ["0005000001-26-000001"],
                    "filingDate": ["2026-02-20"],
                    "reportDate": ["2026-02-19"],
                    "primaryDocument": ["sc13g.htm"],
                }
            },
        }

    def download_text(self, url):
        return "Name of Issuer: Example Corp CUSIP Number: ITEM1TO9 Item 11 9.9%"


class FakeSecClient13DGIndexDiscovery:
    def __init__(self, by_url: dict[str, str]) -> None:
        self.by_url = by_url

    def download_text(self, url: str):
        if url not in self.by_url:
            raise RuntimeError("missing test fixture url")
        return self.by_url[url]


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


def test_ingest_13f_limit_applies_to_matching_forms_not_first_recent_rows(db_session):
    service = Sec13FIngestionService(db=db_session, sec_client=FakeSecClient13FDeepRecent())
    result = service.ingest_for_cik("0003000000", limit=2)

    assert result.filings_upserted == 2
    assert result.holdings_inserted == 4


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


def test_ingest_13dg_accepts_schedule_form_variants(db_session):
    service = Sec13DGIngestionService(db=db_session, sec_client=FakeSecClient13DGSchedule())
    result = service.ingest_for_cik("0002100000", limit=5)

    assert result.filings_upserted == 1
    assert result.events_inserted == 1
    row = db_session.execute(
        text(
            """
            SELECT form_type, event_type, percent_beneficial_owned
            FROM filings f
            JOIN beneficial_ownership_events b ON b.filing_id = f.filing_id
            LIMIT 1
            """
        )
    ).mappings().first()
    assert row is not None
    assert row["form_type"] == "SC 13G/A"
    assert row["event_type"] == "NEW_5PCT"
    assert row["percent_beneficial_owned"] == 7.1


def test_ingest_13dg_retries_missing_event_for_existing_filing(db_session):
    db_session.execute(
        text(
            """
            INSERT INTO managers (manager_id, cik, manager_name, normalized_name)
            VALUES (901, '0002100000', 'Mock Schedule Activist', 'MOCK SCHEDULE ACTIVIST')
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO filings (
              filing_id, accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment
            ) VALUES (
              910,
              '0002100000-26-000001',
              'SC 13G/A',
              '0002100000',
              901,
              '2026-02-20',
              '2026-02-19',
              'https://www.sec.gov/Archives/edgar/data/210000/000210000026000001/sched13ga.htm',
              1
            )
            """
        )
    )
    db_session.commit()

    service = Sec13DGIngestionService(db=db_session, sec_client=FakeSecClient13DGSchedule())
    result = service.ingest_for_cik("0002100000", limit=5)

    assert result.filings_upserted == 0
    assert result.events_inserted == 1
    events = db_session.execute(
        text("SELECT COUNT(*) FROM beneficial_ownership_events WHERE filing_id = 910")
    ).scalar_one()
    assert events == 1


def test_ingest_13dg_limit_applies_to_matching_forms_not_first_recent_rows(db_session):
    service = Sec13DGIngestionService(db=db_session, sec_client=FakeSecClient13DGDeepRecent())
    result = service.ingest_for_cik("0004000000", limit=1)

    assert result.filings_upserted == 1
    assert result.events_inserted == 1


def test_ingest_13dg_rejects_header_words_as_cusip(db_session):
    service = Sec13DGIngestionService(db=db_session, sec_client=FakeSecClient13DGBadCusipWord())
    result = service.ingest_for_cik("0005000000", limit=5)

    assert result.filings_upserted == 1
    assert result.events_inserted == 1
    row = db_session.execute(
        text("SELECT cusip_raw, percent_beneficial_owned FROM beneficial_ownership_events LIMIT 1")
    ).mappings().first()
    assert row is not None
    assert row["cusip_raw"] is None
    assert row["percent_beneficial_owned"] == 5.1


def test_ingest_13dg_rejects_invalid_checksum_cusip_tokens(db_session):
    service = Sec13DGIngestionService(db=db_session, sec_client=FakeSecClient13DGBadCusipChecksum())
    result = service.ingest_for_cik("0005000001", limit=5)

    assert result.filings_upserted == 1
    assert result.events_inserted == 1
    row = db_session.execute(
        text("SELECT cusip_raw, issuer_name_raw FROM beneficial_ownership_events LIMIT 1")
    ).mappings().first()
    assert row is not None
    assert row["cusip_raw"] is None


def test_13dg_discovery_from_daily_and_quarterly_indexes(db_session):
    daily_url = "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR1/master.20260301.idx"
    quarter_url = "https://www.sec.gov/Archives/edgar/full-index/2026/QTR1/master.idx"
    idx_body = "\n".join(
        [
            "Description: Master Index of EDGAR Dissemination Feed",
            "CIK|Company Name|Form Type|Date Filed|Filename",
            "0001374170|NORGES BANK|SC 13G|2026-02-28|edgar/data/1374170/...",
            "0001067983|BERKSHIRE HATHAWAY INC|SC 13D/A|2026-02-27|edgar/data/1067983/...",
            "0000320193|APPLE INC|8-K|2026-02-27|edgar/data/320193/...",
        ]
    )
    fake_client = FakeSecClient13DGIndexDiscovery({daily_url: idx_body, quarter_url: idx_body})

    service = Sec13DGIndexDiscoveryService(sec_client=fake_client)
    summary = service.discover(
        mode="both",
        days=1,
        quarters=1,
        max_ciks=10,
        today=date(2026, 3, 1),
    )

    assert summary.mode == "both"
    assert summary.files_attempted == 2
    assert summary.files_scanned == 2
    assert summary.filings_matched == 4
    assert "0001374170" in summary.ciks
    assert "0001067983" in summary.ciks
    assert "0000320193" not in summary.ciks
    assert summary.latest_filed_date_by_cik["0001374170"] == "2026-02-28"


def test_13dg_discovery_accepts_schedule_form_variants(db_session):
    quarter_url = "https://www.sec.gov/Archives/edgar/full-index/2026/QTR1/master.idx"
    idx_body = "\n".join(
        [
            "Description: Master Index of EDGAR Dissemination Feed",
            "CIK|Company Name|Form Type|Date Filed|Filename",
            "0001067983|BERKSHIRE HATHAWAY INC|SCHEDULE 13G/A|2026-02-27|edgar/data/1067983/...",
            "0000320193|APPLE INC|8-K|2026-02-27|edgar/data/320193/...",
        ]
    )
    fake_client = FakeSecClient13DGIndexDiscovery({quarter_url: idx_body})

    service = Sec13DGIndexDiscoveryService(sec_client=fake_client)
    summary = service.discover(
        mode="quarterly",
        days=1,
        quarters=1,
        max_ciks=10,
        today=date(2026, 3, 1),
    )

    assert summary.files_scanned == 1
    assert summary.filings_matched == 1
    assert summary.ciks == ["0001067983"]
    assert summary.latest_filed_date_by_cik["0001067983"] == "2026-02-27"


def test_cleanup_13dg_history_prunes_old_rows(db_session):
    old_date = (date.today() - timedelta(days=420)).isoformat()
    recent_date = (date.today() - timedelta(days=10)).isoformat()
    with db_session.begin():
        db_session.execute(
            text(
                """
                INSERT INTO managers (manager_id, cik, manager_name, normalized_name, status)
                VALUES (9901, '0009900001', 'Cleanup Old', 'CLEANUP OLD', 'ACTIVE')
                """
            )
        )
        db_session.execute(
            text(
                """
                INSERT INTO managers (manager_id, cik, manager_name, normalized_name, status)
                VALUES (9902, '0009900002', 'Cleanup New', 'CLEANUP NEW', 'ACTIVE')
                """
            )
        )
        db_session.execute(
            text(
                """
                INSERT INTO filings (
                  filing_id, accession_no, form_type, cik, manager_id, filed_at, period_end_date, sec_url, is_amendment
                ) VALUES
                  (99010, '0009900001-26-000001', 'SC 13D', '0009900001', 9901, :old_date, :old_date, 'https://example.com/old13d', 0),
                  (99011, '0009900002-26-000001', 'SC 13G', '0009900002', 9902, :recent_date, :recent_date, 'https://example.com/new13g', 0),
                  (99012, '0009900001-26-000013', '13F-HR', '0009900001', 9901, :old_date, :old_date, 'https://example.com/old13f', 0)
                """
            ),
            {"old_date": old_date, "recent_date": recent_date},
        )
        db_session.execute(
            text(
                """
                INSERT INTO beneficial_ownership_events (
                  bo_event_id, filing_id, manager_id, security_id, report_date, event_type, mapping_status
                ) VALUES
                  (990100, 99010, 9901, NULL, :old_date, 'NEW_5PCT', 'UNMAPPED'),
                  (990101, 99011, 9902, NULL, :recent_date, 'NEW_5PCT', 'UNMAPPED')
                """
            ),
            {"old_date": old_date, "recent_date": recent_date},
        )

    summary = cleanup_13dg_history(db=db_session, keep_days=120, analyze=False)

    assert summary.events_deleted == 1
    assert summary.filings_deleted == 1

    remaining_events = db_session.execute(
        text("SELECT COUNT(*) FROM beneficial_ownership_events WHERE filing_id IN (99010, 99011)")
    ).scalar_one()
    assert remaining_events == 1

    old_13dg_exists = db_session.execute(text("SELECT COUNT(*) FROM filings WHERE filing_id = 99010")).scalar_one()
    recent_13dg_exists = db_session.execute(text("SELECT COUNT(*) FROM filings WHERE filing_id = 99011")).scalar_one()
    old_13f_exists = db_session.execute(text("SELECT COUNT(*) FROM filings WHERE filing_id = 99012")).scalar_one()
    assert old_13dg_exists == 0
    assert recent_13dg_exists == 1
    assert old_13f_exists == 1
