from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

import requests

from app.clients.rate_limit import ProviderRateLimiter
from app.config import get_settings

_DATASETS_PAGE = "/data-research/sec-markets-data/form-13f-data-sets"
_RANGE_DATASET_RE = re.compile(
    r"/(\d{2}[a-z]{3}\d{4})-(\d{2}[a-z]{3}\d{4})_form13f\.zip$",
    re.IGNORECASE,
)
_QUARTER_DATASET_RE = re.compile(r"/(\d{4})q([1-4])_form13f\.zip$", re.IGNORECASE)


@dataclass(frozen=True)
class TopAumManager:
    cik: str
    manager_name: str
    accession_number: str
    filing_date: str
    period_of_report: str
    table_value_total: float


def _extract_zip_links(html: str) -> list[str]:
    return sorted(set(re.findall(r"""href=["']([^"']+_form13f\.zip)["']""", html, re.IGNORECASE)))


def _parse_dataset_sort_date(dataset_url: str) -> date:
    range_match = _RANGE_DATASET_RE.search(dataset_url)
    if range_match:
        end_text = range_match.group(2).upper()
        return datetime.strptime(end_text, "%d%b%Y").date()

    quarter_match = _QUARTER_DATASET_RE.search(dataset_url)
    if quarter_match:
        year = int(quarter_match.group(1))
        quarter = int(quarter_match.group(2))
        if quarter == 1:
            return date(year, 3, 31)
        if quarter == 2:
            return date(year, 6, 30)
        if quarter == 3:
            return date(year, 9, 30)
        return date(year, 12, 31)

    return date.min


def resolve_latest_13f_dataset_url(
    session: requests.Session,
    limiter: ProviderRateLimiter,
) -> str:
    settings = get_settings()
    page_url = urljoin(settings.sec_www_base_url.rstrip("/") + "/", _DATASETS_PAGE.lstrip("/"))

    limiter.acquire("SEC")
    response = session.get(page_url, timeout=settings.request_timeout_seconds)
    response.raise_for_status()

    links = _extract_zip_links(response.text)
    if not links:
        raise ValueError(f"No form13f ZIP links found on {page_url}")

    absolute = [urljoin(settings.sec_www_base_url.rstrip("/") + "/", link.lstrip("/")) for link in links]
    absolute.sort(key=_parse_dataset_sort_date, reverse=True)
    return absolute[0]


def _parse_numeric(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip().replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _normalize_sec_date(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def fetch_top_managers_by_13f_value(
    session: requests.Session,
    limiter: ProviderRateLimiter,
    top_n: int,
    dataset_url: str = "",
) -> tuple[str, list[TopAumManager]]:
    if top_n <= 0:
        return (dataset_url, [])

    settings = get_settings()
    selected_dataset_url = dataset_url.strip() or resolve_latest_13f_dataset_url(session=session, limiter=limiter)

    limiter.acquire("SEC")
    response = session.get(selected_dataset_url, timeout=max(60.0, settings.request_timeout_seconds))
    response.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    files = {name.upper(): name for name in zf.namelist()}
    required = ["SUBMISSION.TSV", "SUMMARYPAGE.TSV", "COVERPAGE.TSV"]
    missing = [name for name in required if name not in files]
    if missing:
        raise ValueError(f"SEC dataset is missing required TSV files: {', '.join(missing)}")

    summary_value_by_accession: dict[str, float] = {}
    with zf.open(files["SUMMARYPAGE.TSV"]) as fh:
        reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", newline=""), delimiter="\t")
        for row in reader:
            accession = (row.get("ACCESSION_NUMBER") or "").strip()
            table_value_total = _parse_numeric(row.get("TABLEVALUETOTAL"))
            if not accession or table_value_total is None:
                continue
            summary_value_by_accession[accession] = table_value_total

    manager_name_by_accession: dict[str, str] = {}
    with zf.open(files["COVERPAGE.TSV"]) as fh:
        reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", newline=""), delimiter="\t")
        for row in reader:
            accession = (row.get("ACCESSION_NUMBER") or "").strip()
            manager_name = (row.get("FILINGMANAGER_NAME") or "").strip()
            if accession and manager_name:
                manager_name_by_accession[accession] = manager_name

    best_by_cik: dict[str, TopAumManager] = {}
    with zf.open(files["SUBMISSION.TSV"]) as fh:
        reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", newline=""), delimiter="\t")
        for row in reader:
            submission_type = (row.get("SUBMISSIONTYPE") or "").strip().upper()
            if submission_type not in {"13F-HR", "13F-HR/A"}:
                continue
            accession = (row.get("ACCESSION_NUMBER") or "").strip()
            if not accession:
                continue
            table_value_total = summary_value_by_accession.get(accession)
            if table_value_total is None:
                continue
            raw_cik = "".join(ch for ch in (row.get("CIK") or "") if ch.isdigit())
            if not raw_cik:
                continue
            cik = raw_cik.zfill(10)
            filing_date = _normalize_sec_date(row.get("FILING_DATE"))
            period_of_report = _normalize_sec_date(row.get("PERIODOFREPORT"))
            manager_name = manager_name_by_accession.get(accession, "")

            candidate = TopAumManager(
                cik=cik,
                manager_name=manager_name,
                accession_number=accession,
                filing_date=filing_date,
                period_of_report=period_of_report,
                table_value_total=table_value_total,
            )
            current = best_by_cik.get(cik)
            if current is None:
                best_by_cik[cik] = candidate
                continue
            if (
                candidate.period_of_report,
                candidate.filing_date,
                candidate.table_value_total,
                candidate.accession_number,
            ) > (
                current.period_of_report,
                current.filing_date,
                current.table_value_total,
                current.accession_number,
            ):
                best_by_cik[cik] = candidate

    ranked = sorted(
        best_by_cik.values(),
        key=lambda r: (r.table_value_total, r.period_of_report, r.filing_date, r.accession_number),
        reverse=True,
    )
    return (selected_dataset_url, ranked[:top_n])
