"""Turn SEC submission metadata and selected XBRL tags into reviewable records."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from normalization.taxonomy import StatementType, get_field
from sec_data.client import SecError, normalize_cik
from validation.types import SourceRef, StatementSnapshot, TolerancePolicy

# These are direct tag-to-field relationships, not broad synonym matching.
# In particular, cash-flow payments are inverted to the project's signed
# outflow convention. Unlisted or company-specific tags stay unmapped.
_TAGS: dict[str, tuple[StatementType, str, Literal[1, -1]]] = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": (
        "income_statement",
        "revenue",
        1,
    ),
    "Revenues": ("income_statement", "revenue", 1),
    "SalesRevenueNet": ("income_statement", "revenue", 1),
    "CostOfRevenue": ("income_statement", "cost_of_revenue", 1),
    "CostOfGoodsAndServicesSold": ("income_statement", "cost_of_revenue", 1),
    "GrossProfit": ("income_statement", "gross_profit", 1),
    "OperatingIncomeLoss": ("income_statement", "operating_income", 1),
    "NetIncomeLoss": ("income_statement", "net_income", 1),
    "Assets": ("balance_sheet", "total_assets", 1),
    "AssetsCurrent": ("balance_sheet", "total_current_assets", 1),
    "Liabilities": ("balance_sheet", "total_liabilities", 1),
    "LiabilitiesCurrent": ("balance_sheet", "total_current_liabilities", 1),
    "StockholdersEquity": ("balance_sheet", "shareholders_equity", 1),
    "CashAndCashEquivalentsAtCarryingValue": (
        "balance_sheet",
        "cash_and_cash_equivalents",
        1,
    ),
    "NetCashProvidedByUsedInOperatingActivities": (
        "cash_flow_statement",
        "operating_cash_flow",
        1,
    ),
    "NetCashProvidedByUsedInInvestingActivities": (
        "cash_flow_statement",
        "investing_cash_flow",
        1,
    ),
    "NetCashProvidedByUsedInFinancingActivities": (
        "cash_flow_statement",
        "financing_cash_flow",
        1,
    ),
    "PaymentsToAcquirePropertyPlantAndEquipment": (
        "cash_flow_statement",
        "capital_expenditure",
        -1,
    ),
}

for _statement, _field, _sign in _TAGS.values():
    get_field(_statement, _field)

_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")
_SAFE_DOCUMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True, slots=True)
class SecFiling:
    cik: str
    company_name: str
    accession: str
    form: str
    filed: date
    report_date: date | None
    primary_document: str
    filing_url: str
    source_url: str


@dataclass(frozen=True, slots=True)
class SecFact:
    cik: str
    accession: str
    form: str
    filed: date
    taxonomy: str
    tag: str
    statement_type: StatementType
    canonical_field: str
    raw_value: Decimal
    normalized_value: Decimal | None
    unit: str
    start: date | None
    end: date
    fiscal_year: int | None
    fiscal_period: str | None
    frame: str | None
    source_url: str
    filing_url: str
    status: Literal["candidate", "needs_review"]
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SecComparison:
    fact: SecFact
    local_source_refs: tuple[SourceRef, ...]
    local_value: Decimal | None
    difference: Decimal | None
    status: Literal["match", "difference", "unavailable"]
    reason: str | None = None


def _date(value: Any, *, optional: bool = False) -> date | None:
    if value in (None, "") and optional:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise SecError("SEC returned an invalid date") from exc


def _identity(data: dict[str, Any]) -> tuple[str, str]:
    try:
        cik = normalize_cik(data["cik"])
    except (KeyError, ValueError) as exc:
        raise SecError("SEC response has no valid CIK") from exc
    name = data.get("name") or data.get("entityName") or ""
    return cik, str(name)


def filing_url(cik: str, accession: str, primary_document: str = "") -> str:
    if not _ACCESSION.fullmatch(accession):
        raise ValueError("Invalid accession number")
    root = (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik)}/{accession.replace('-', '')}/"
    )
    return (
        root + primary_document if _SAFE_DOCUMENT.fullmatch(primary_document) else root
    )


def parse_recent_filings(
    submissions: dict[str, Any],
    *,
    forms: tuple[str, ...] = ("10-K", "10-Q"),
    limit: int = 100,
) -> tuple[SecFiling, ...]:
    """Read the SEC's recent filing columns without guessing missing metadata."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    cik, name = _identity(submissions)
    source = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        recent = submissions["filings"]["recent"]
        columns = [
            recent[key]
            for key in (
                "accessionNumber",
                "form",
                "filingDate",
                "reportDate",
                "primaryDocument",
            )
        ]
    except (KeyError, TypeError) as exc:
        raise SecError("SEC submissions are missing recent filing columns") from exc
    if (
        any(not isinstance(column, list) for column in columns)
        or len({len(column) for column in columns}) != 1
    ):
        raise SecError("SEC recent filing columns have different lengths")
    result = []
    for accession, form, filed, report_date, primary in zip(*columns, strict=True):
        if form not in forms:
            continue
        if not isinstance(accession, str) or not _ACCESSION.fullmatch(accession):
            raise SecError("SEC filing has an invalid accession number")
        result.append(
            SecFiling(
                cik=cik,
                company_name=name,
                accession=accession,
                form=form,
                filed=_date(filed),
                report_date=_date(report_date, optional=True),
                primary_document=str(primary),
                filing_url=filing_url(cik, accession, str(primary)),
                source_url=source,
            )
        )
        if len(result) == limit:
            break
    return tuple(result)


def map_company_facts(data: dict[str, Any], accession: str) -> tuple[SecFact, ...]:
    """Map explicitly known USD facts from one filing to reviewable candidates.

    All matching contexts are kept. A caller must resolve duplicate concepts,
    quarterly versus year-to-date durations, and amendments before acceptance.
    """
    if not _ACCESSION.fullmatch(accession):
        raise ValueError("Invalid accession number")
    cik, _ = _identity(data)
    source = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    facts = data.get("facts")
    if not isinstance(facts, dict):
        raise SecError("SEC company facts are missing")
    concepts = facts.get("us-gaap", {})
    if not isinstance(concepts, dict):
        raise SecError("SEC company facts have an invalid us-gaap structure")
    result = []
    for tag, (statement, field, sign) in _TAGS.items():
        concept = concepts.get(tag)
        if concept is None:
            continue
        if not isinstance(concept, dict) or not isinstance(concept.get("units"), dict):
            raise SecError(f"SEC company facts have invalid units for {tag}")
        entries = concept.get("units", {}).get("USD", [])
        if not isinstance(entries, list):
            raise SecError(f"SEC company facts have invalid USD entries for {tag}")
        for entry in entries:
            if not isinstance(entry, dict):
                raise SecError(f"SEC company facts have an invalid entry for {tag}")
            if entry.get("accn") != accession:
                continue
            raw = entry.get("val")
            if isinstance(raw, bool):
                raise SecError(f"SEC returned an invalid numeric fact for {tag}")
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, TypeError) as exc:
                raise SecError(
                    f"SEC returned an invalid numeric fact for {tag}"
                ) from exc
            if not value.is_finite():
                raise SecError(f"SEC returned an invalid numeric fact for {tag}")
            start = _date(entry.get("start"), optional=True)
            end = _date(entry.get("end"))
            basis = get_field(statement, field).period_basis
            needs_review = (basis == "duration" and start is None) or (
                basis == "instant" and start is not None
            )
            note = (
                "Period context does not match the canonical field"
                if needs_review
                else None
            )
            if sign == -1 and value < 0:
                needs_review = True
                note = "Payment tag has an unexpected negative source value"
            result.append(
                SecFact(
                    cik=cik,
                    accession=accession,
                    form=str(entry.get("form", "")),
                    filed=_date(entry.get("filed")),
                    taxonomy="us-gaap",
                    tag=tag,
                    statement_type=statement,
                    canonical_field=field,
                    raw_value=value,
                    normalized_value=None if needs_review else value * sign,
                    unit="USD",
                    start=start,
                    end=end,
                    fiscal_year=entry.get("fy"),
                    fiscal_period=entry.get("fp"),
                    frame=entry.get("frame"),
                    source_url=source,
                    filing_url=filing_url(cik, accession),
                    status="needs_review" if needs_review else "candidate",
                    note=note,
                )
            )
    return tuple(result)


def compare_to_statement(
    fact: SecFact,
    statement: StatementSnapshot,
    *,
    tolerance: TolerancePolicy | None = None,
) -> SecComparison:
    """Compare exact field, date range, and currency; never accept a value."""

    def unavailable(reason: str) -> SecComparison:
        return SecComparison(fact, (), None, None, "unavailable", reason)

    tolerance = tolerance or TolerancePolicy()
    if fact.status != "candidate" or fact.normalized_value is None:
        return unavailable("SEC fact needs review")
    if statement.statement_type != fact.statement_type:
        return unavailable("Statement type differs")
    if statement.period.status != "normalized" or (
        statement.period.period_start != fact.start
        or statement.period.period_end != fact.end
    ):
        return unavailable("Reporting dates differ")
    if statement.currency != fact.unit or statement.unit_scale != "ones":
        return unavailable("Currency or unit scale differs")
    values = [
        item
        for item in statement.values
        if item.field == fact.canonical_field
        and item.status == "accepted"
        and item.normalized_value is not None
        and (item.currency is None or item.currency == fact.unit)
        and (item.unit_scale is None or item.unit_scale == "ones")
    ]
    if not values or len({item.normalized_value for item in values}) != 1:
        return unavailable("No single accepted local value")
    local = values[0].normalized_value
    difference = local - fact.normalized_value
    return SecComparison(
        fact=fact,
        local_source_refs=tuple(item.source_ref for item in values),
        local_value=local,
        difference=difference,
        status=(
            "match"
            if abs(difference) <= tolerance.for_values(local, fact.normalized_value)
            else "difference"
        ),
    )
