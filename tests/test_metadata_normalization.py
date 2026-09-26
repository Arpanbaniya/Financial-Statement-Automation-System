"""Amounts and reporting periods retain their source and expose uncertainty."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from normalization import SourceLocation, normalize_amount, normalize_period


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("1,234.50", Decimal("1234.50")),
        ("(1,234.50)", Decimal("-1234.50")),
        ("-250", Decimal("-250")),
        (".75", Decimal("0.75")),
    ],
)
def test_accounting_numbers_are_exact_and_source_is_kept(
    source: str, expected: Decimal
) -> None:
    location = SourceLocation(sheet="Income", cell="B4", row=4)
    result = normalize_amount(source, source_location=location)
    assert result.original_value == source
    assert result.normalized_value == expected
    assert result.status == "normalized"
    assert result.source_location == location


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("in thousands", Decimal("125000")),
        ("Millions", Decimal("125000000")),
        ("billions", Decimal("125000000000")),
    ],
)
def test_unit_scaling_keeps_original_unit(unit: str, expected: Decimal) -> None:
    result = normalize_amount("125", unit=unit, currency="USD")
    assert result.original_unit == unit
    assert result.original_currency == "USD"
    assert result.normalized_value == expected
    assert result.currency == "USD"
    assert result.status == "normalized"


@pytest.mark.parametrize("source", [None, "", "  ", "-", "–", "—"])
def test_empty_and_dash_are_missing_not_zero(source: str | None) -> None:
    result = normalize_amount(source)
    assert result.normalized_value is None
    assert result.status == "missing"
    assert result.warnings[0].code == "missing_value"


def test_currency_symbol_never_converts_amount() -> None:
    euros = normalize_amount("(€1,234.50)", unit="thousands")
    assert euros.currency == "EUR"
    assert euros.currency_symbol == "€"
    assert euros.normalized_value == Decimal("-1234500.00")

    dollars = normalize_amount("$125", unit="millions")
    assert dollars.normalized_value == Decimal("125000000")
    assert dollars.currency is None
    assert dollars.status == "needs_review"
    assert "ambiguous_currency" in {warning.code for warning in dollars.warnings}
    assert normalize_amount("$125", currency="CAD").currency == "CAD"


@pytest.mark.parametrize(
    "source", ["1,23", "12.3.4", "10%", "(-250)", True, float("nan")]
)
def test_invalid_amounts_require_review(source: object) -> None:
    result = normalize_amount(source)  # type: ignore[arg-type]
    assert result.normalized_value is None
    assert result.status == "needs_review"


def test_unknown_unit_and_conflicting_currency_are_visible() -> None:
    unknown = normalize_amount("125", unit="crores")
    assert unknown.normalized_value is None
    assert "unknown_unit" in {warning.code for warning in unknown.warnings}
    conflict = normalize_amount("EUR 125", currency="USD")
    assert conflict.normalized_value == Decimal("125")
    assert conflict.currency is None
    assert conflict.status == "needs_review"


def test_fiscal_year_and_quarter_need_a_calendar_to_resolve_dates() -> None:
    unresolved = normalize_period("income_statement", label="FY2025")
    assert unresolved.fiscal_year == 2025
    assert unresolved.period_start is None
    assert unresolved.period_end is None
    assert unresolved.status == "needs_review"

    annual = normalize_period(
        "income_statement", label="FY2025", fiscal_year_end=(6, 30)
    )
    assert (annual.period_start, annual.period_end) == (
        date(2024, 7, 1),
        date(2025, 6, 30),
    )
    assert annual.period_type == "annual"
    assert annual.status == "normalized"

    quarter = normalize_period(
        "cash_flow_statement", label="Q1 FY2025", fiscal_year_end=(6, 30)
    )
    assert (quarter.period_start, quarter.period_end) == (
        date(2024, 7, 1),
        date(2024, 9, 30),
    )
    assert quarter.fiscal_year == 2025
    assert quarter.fiscal_quarter == 1
    assert quarter.period_type == "quarterly"


def test_explicit_date_ranges_classify_duration_and_instant() -> None:
    annual = normalize_period("income_statement", label="Jan 1, 2025 – Dec 31, 2025")
    assert annual.period_start == date(2025, 1, 1)
    assert annual.period_end == date(2025, 12, 31)
    assert annual.period_type == "annual"
    assert annual.period_basis == "duration"
    assert annual.status == "normalized"

    instant = normalize_period("balance_sheet", label="as of Dec 31, 2025")
    assert instant.period_start is None
    assert instant.period_end == date(2025, 12, 31)
    assert instant.period_type == "instant"
    assert instant.status == "normalized"

    as_at = normalize_period("balance_sheet", label="As at December 31, 2025")
    assert as_at.period_end == date(2025, 12, 31)


@pytest.mark.parametrize(
    ("label", "start", "kind"),
    [
        ("Year ended December 31, 2025", date(2025, 1, 1), "annual"),
        ("Three months ended Sep 30, 2025", date(2025, 7, 1), "quarterly"),
        ("Six months ended Jun 30, 2025", date(2025, 1, 1), "six_months"),
        ("Nine months ended Sep 30, 2025", date(2025, 1, 1), "nine_months"),
    ],
)
def test_common_ended_headings_resolve_range(
    label: str, start: date, kind: str
) -> None:
    result = normalize_period("income_statement", label=label)
    assert result.period_start == start
    assert result.period_type == kind
    assert result.status == "normalized"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2025-01-01", "2025-06-30", "six_months"),
        ("2025-01-01", "2025-09-30", "nine_months"),
        ("2025-01-15", "2025-04-30", "other_duration"),
    ],
)
def test_explicit_ranges_preserve_duration_type(
    start: str, end: str, expected: str
) -> None:
    result = normalize_period("cash_flow_statement", start=start, end=end)
    assert (result.original_start, result.original_end) == (start, end)
    assert result.period_type == expected
    assert result.status == "normalized"


def test_instant_and_duration_conflicts_require_review() -> None:
    balance = normalize_period("balance_sheet", start="2025-01-01", end="2025-12-31")
    assert balance.status == "needs_review"
    assert "basis_conflict" in {warning.code for warning in balance.warnings}

    income = normalize_period("income_statement", label="as of Dec 31, 2025")
    assert income.status == "needs_review"
    assert income.period_start is None


def test_period_label_and_explicit_dates_cannot_disagree_silently() -> None:
    result = normalize_period(
        "income_statement",
        label="2025-01-01 to 2025-12-31",
        start="2025-02-01",
        end="2025-12-31",
    )
    assert result.status == "needs_review"
    assert "period_conflict" in {warning.code for warning in result.warnings}


def test_balance_sheet_fiscal_quarter_uses_quarter_end_only() -> None:
    result = normalize_period(
        "balance_sheet", label="Q1 FY2025", fiscal_year_end=(6, 30)
    )
    assert result.period_start is None
    assert result.period_end == date(2024, 9, 30)
    assert result.period_type == "instant"
    assert result.status == "normalized"


def test_malformed_dates_are_reviewed_without_crashing() -> None:
    result = normalize_period("income_statement", start="2025-02-30", end="2025-12-31")
    assert result.status == "needs_review"
    assert result.period_start is None
    assert "invalid_period_start" in {warning.code for warning in result.warnings}


def test_excel_datetime_and_fiscal_label_mismatch() -> None:
    result = normalize_period(
        "income_statement",
        label="FY2025",
        start=datetime(2025, 1, 1),
        end=datetime(2025, 3, 31),
    )
    assert result.period_type == "quarterly"
    assert result.status == "needs_review"
    assert "fiscal_label_conflict" in {warning.code for warning in result.warnings}
