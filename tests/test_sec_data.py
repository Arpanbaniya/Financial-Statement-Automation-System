"""SEC adapter tests use saved JSON and mocked HTTP; they make no live calls."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from normalization.periods import normalize_period
from sec_data.adapter import (
    compare_to_statement,
    map_company_facts,
    parse_recent_filings,
)
from sec_data.client import SecClient, SecError, _RateLimiter, normalize_cik
from validation.types import SourceRef, StatementSnapshot, ValidationValue

FIXTURES = Path(__file__).parent / "fixtures"
AGENT = "Financial Statement Research research@valid-company.org"
ACCESSION = "0000123456-25-000001"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_filing_metadata_and_source_urls() -> None:
    filings = parse_recent_filings(fixture("sec_submissions.json"))
    assert [item.form for item in filings] == ["10-K", "10-Q"]
    assert filings[0].cik == "0000123456"
    assert filings[0].report_date == date(2024, 12, 31)
    assert filings[0].filing_url == (
        "https://www.sec.gov/Archives/edgar/data/123456/000012345625000001/annual.htm"
    )
    assert filings[0].source_url.endswith("/CIK0000123456.json")


def test_facts_keep_context_and_capex_sign() -> None:
    facts = map_company_facts(fixture("sec_companyfacts.json"), ACCESSION)
    assert len(facts) == 3
    revenue = next(item for item in facts if item.canonical_field == "revenue")
    capex = next(
        item for item in facts if item.canonical_field == "capital_expenditure"
    )
    assert revenue.raw_value == Decimal(1000)
    assert revenue.start == date(2024, 1, 1)
    assert revenue.end == date(2024, 12, 31)
    assert revenue.accession == ACCESSION
    assert revenue.status == "candidate"
    assert revenue.source_url.endswith("/CIK0000123456.json")
    assert capex.raw_value == Decimal(80)
    assert capex.normalized_value == Decimal(-80)
    assert capex.filing_url.endswith("/000012345625000001/")


def test_unexpected_sign_and_period_need_review() -> None:
    data = fixture("sec_companyfacts.json")
    payment = data["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]
    payment["units"]["USD"][0]["val"] = -80
    assets = data["facts"]["us-gaap"]["Assets"]
    assets["units"]["USD"][0]["start"] = "2024-01-01"
    facts = map_company_facts(data, ACCESSION)
    assert all(
        item.normalized_value is None and item.status == "needs_review"
        for item in facts
        if item.tag in {"PaymentsToAcquirePropertyPlantAndEquipment", "Assets"}
    )


def test_compare_only_exact_context_and_accepted_values() -> None:
    fact = next(
        item
        for item in map_company_facts(fixture("sec_companyfacts.json"), ACCESSION)
        if item.canonical_field == "revenue"
    )
    period = normalize_period("income_statement", start="2024-01-01", end="2024-12-31")
    statement = StatementSnapshot(
        id="statement-1",
        company_id="company-1",
        document_id="document-1",
        statement_type="income_statement",
        period=period,
        values=(
            ValidationValue(
                field="revenue",
                normalized_value=Decimal(1000),
                source_ref=SourceRef(statement_id="statement-1"),
                status="accepted",
                currency="USD",
                unit_scale="ones",
            ),
        ),
        currency="USD",
        unit_scale="ones",
    )
    comparison = compare_to_statement(fact, statement)
    assert comparison.status == "match"
    assert comparison.difference == Decimal(0)
    wrong_period = StatementSnapshot(
        id="statement-1",
        company_id="company-1",
        document_id="document-1",
        statement_type="income_statement",
        period=normalize_period(
            "income_statement", start="2023-01-01", end="2023-12-31"
        ),
        values=statement.values,
        currency="USD",
        unit_scale="ones",
    )
    assert compare_to_statement(fact, wrong_period).status == "unavailable"


def test_client_throttles_retries_and_caches() -> None:
    clock = [0.0]
    delays = []
    calls = []

    def sleep(seconds: float) -> None:
        delays.append(seconds)
        clock[0] += seconds

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=fixture("sec_submissions.json"))

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    sec = SecClient(
        AGENT,
        client=http_client,
        limiter=_RateLimiter(clock=lambda: clock[0], sleep=sleep),
        clock=lambda: clock[0],
        sleep=sleep,
    )
    first = sec.submissions(123456)
    first["name"] = "changed by caller"
    second = sec.submissions("0000123456")
    assert second["name"] == "Sample Public Company"
    assert len(calls) == 2
    assert calls[0].url.host == "data.sec.gov"
    assert calls[0].headers["User-Agent"] == AGENT
    assert calls[1].url.path == "/submissions/CIK0000123456.json"
    assert delays == [2.0]


def test_client_rejects_bad_configuration_and_http_errors() -> None:
    with pytest.raises(ValueError, match="contact email"):
        SecClient("anonymous")
    with pytest.raises(ValueError, match="CIK"):
        normalize_cik("123/../456")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(404))
    )
    sec = SecClient(AGENT, client=client, limiter=_RateLimiter(interval=0))
    with pytest.raises(SecError, match="404"):
        sec.company_facts("123456")


def test_invalid_filing_columns_and_accession_fail_closed() -> None:
    data = fixture("sec_submissions.json")
    data["filings"]["recent"]["form"].pop()
    with pytest.raises(SecError, match="different lengths"):
        parse_recent_filings(data)
    with pytest.raises(ValueError, match="accession"):
        map_company_facts(fixture("sec_companyfacts.json"), "../../other")
    with pytest.raises(SecError, match="facts are missing"):
        map_company_facts({"cik": 123456}, ACCESSION)
