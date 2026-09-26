"""Hand-calculated trend and common-size examples with unsafe cases."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance import calculate_common_size, calculate_horizontal
from normalization import SourceLocation, normalize_period
from validation import SourceRef, StatementSnapshot, ValidationValue

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


def value(
    statement_id: str,
    field: str,
    amount: str,
    *,
    row: int = 1,
    currency: str | None = None,
    status: str = "accepted",
) -> ValidationValue:
    return ValidationValue(
        field=field,
        normalized_value=Decimal(amount),
        source_ref=SourceRef(
            statement_id,
            f"{statement_id}-{field}-{row}",
            SourceLocation(sheet="Source", cell=f"B{row}", row=row),
        ),
        currency=currency,
        unit_scale="ones",
        original_value=amount,
        status=status,  # type: ignore[arg-type]
    )


def snapshot(
    statement_id: str,
    kind: str,
    start: str | None,
    end: str,
    values: tuple[ValidationValue, ...],
    *,
    currency: str = "USD",
    company: str = "company-1",
) -> StatementSnapshot:
    return StatementSnapshot(
        id=statement_id,
        company_id=company,
        document_id=f"doc-{statement_id}",
        statement_type=kind,  # type: ignore[arg-type]
        period=normalize_period(kind, start=start, end=end),  # type: ignore[arg-type]
        values=values,
        currency=currency,
        unit_scale="ones",
    )


def by_name(results: tuple, name: str, year: int):
    return next(
        result
        for result in results
        if result.metric_name == name and result.current_period.period_end.year == year
    )


def test_year_over_year_growth_uses_matching_statements_and_signed_fcf() -> None:
    previous_income = snapshot(
        "is24",
        "income_statement",
        "2024-01-01",
        "2024-12-31",
        (
            value("is24", "revenue", "100"),
            value("is24", "gross_profit", "40"),
            value("is24", "operating_income", "10"),
            value("is24", "net_income", "-10"),
        ),
    )
    current_income = snapshot(
        "is25",
        "income_statement",
        "2025-01-01",
        "2025-12-31",
        (
            value("is25", "revenue", "120"),
            value("is25", "gross_profit", "0"),
            value("is25", "operating_income", "-5"),
            value("is25", "net_income", "20"),
        ),
    )
    previous_balance = snapshot(
        "bs24",
        "balance_sheet",
        None,
        "2024-12-31",
        (
            value("bs24", "total_assets", "100"),
            value("bs24", "short_term_debt", "5"),
            value("bs24", "long_term_debt", "35"),
            value("bs24", "shareholders_equity", "60"),
        ),
    )
    current_balance = snapshot(
        "bs25",
        "balance_sheet",
        None,
        "2025-12-31",
        (
            value("bs25", "total_assets", "150"),
            value("bs25", "short_term_debt", "10"),
            value("bs25", "long_term_debt", "40"),
            value("bs25", "shareholders_equity", "80"),
        ),
    )
    previous_cash = snapshot(
        "cf24",
        "cash_flow_statement",
        "2024-01-01",
        "2024-12-31",
        (
            value("cf24", "operating_cash_flow", "20"),
            value("cf24", "capital_expenditure", "-5"),
        ),
    )
    current_cash = snapshot(
        "cf25",
        "cash_flow_statement",
        "2025-01-01",
        "2025-12-31",
        (
            value("cf25", "operating_cash_flow", "30"),
            value("cf25", "capital_expenditure", "-10"),
        ),
    )
    source = (
        current_cash,
        previous_income,
        current_balance,
        previous_cash,
        current_income,
        previous_balance,
    )
    results = calculate_horizontal(source, calculated_at=NOW)
    assert len(results) == 18
    expected = {
        "revenue_growth": (Decimal("20"), Decimal("20")),
        "gross_profit_growth": (Decimal("-40"), Decimal("-100")),
        "operating_income_growth": (Decimal("-15"), Decimal("-150")),
        "assets_growth": (Decimal("50"), Decimal("50")),
        "debt_growth": (Decimal("10"), Decimal("25")),
        "equity_growth": (Decimal("20"), Decimal("100") / Decimal("3")),
        "operating_cash_flow_growth": (Decimal("10"), Decimal("50")),
        "free_cash_flow_growth": (Decimal("5"), Decimal("100") / Decimal("3")),
    }
    for name, (change, percentage) in expected.items():
        result = by_name(results, name, 2025)
        assert result.status == "calculated", name
        assert result.absolute_change == change, name
        assert abs(result.percentage_change - percentage) < Decimal("0.0000000001"), (
            name
        )
        assert result.formula_id and result.source_refs
        assert result.calculated_at == NOW
    net = by_name(results, "net_income_growth", 2025)
    assert net.absolute_change == Decimal("30")
    assert net.previous_value == Decimal("-10")
    assert net.percentage_change is None
    assert "negative_baseline" in {w.code for w in net.warnings}
    operating = by_name(results, "operating_income_growth", 2025)
    assert "sign_change" in {w.code for w in operating.warnings}
    fcf = by_name(results, "free_cash_flow_growth", 2025)
    assert (fcf.current_value, fcf.previous_value) == (Decimal("20"), Decimal("15"))
    assert {ref.statement_id for ref in fcf.source_refs} == {"cf24", "cf25"}
    assert previous_cash.values[1].normalized_value == Decimal("-5")


def test_missing_period_and_zero_baseline_do_not_produce_growth() -> None:
    early = snapshot(
        "is23",
        "income_statement",
        "2023-01-01",
        "2023-12-31",
        (value("is23", "revenue", "100"),),
    )
    prior = snapshot(
        "is24",
        "income_statement",
        "2024-01-01",
        "2024-12-31",
        (value("is24", "revenue", "0"),),
    )
    current = snapshot(
        "is25",
        "income_statement",
        "2025-01-01",
        "2025-12-31",
        (value("is25", "revenue", "50"),),
    )
    results = calculate_horizontal([current, early, prior], calculated_at=NOW)
    oldest = by_name(results, "revenue_growth", 2023)
    assert oldest.status == "unavailable"
    assert "missing_comparable_period" in {w.code for w in oldest.warnings}
    latest = by_name(results, "revenue_growth", 2025)
    assert latest.previous_value == 0
    assert latest.absolute_change == Decimal("50")
    assert latest.percentage_change is None
    assert "zero_baseline" in {w.code for w in latest.warnings}


def test_quarters_require_matching_year_or_explicit_sequential_mode() -> None:
    q1_2024 = snapshot(
        "q124",
        "income_statement",
        "2024-01-01",
        "2024-03-31",
        (value("q124", "revenue", "80"),),
    )
    q1_2025 = snapshot(
        "q125",
        "income_statement",
        "2025-01-01",
        "2025-03-31",
        (value("q125", "revenue", "100"),),
    )
    q2_2025 = snapshot(
        "q225",
        "income_statement",
        "2025-04-01",
        "2025-06-30",
        (value("q225", "revenue", "120"),),
    )
    yoy = calculate_horizontal([q1_2024, q1_2025, q2_2025], calculated_at=NOW)
    q1_result = next(
        r
        for r in yoy
        if r.metric_name == "revenue_growth"
        and r.current_period.period_end.isoformat() == "2025-03-31"
    )
    q2_result = next(
        r
        for r in yoy
        if r.metric_name == "revenue_growth"
        and r.current_period.period_end.isoformat() == "2025-06-30"
    )
    assert q1_result.percentage_change == Decimal("25")
    assert q2_result.status == "unavailable"
    sequential = calculate_horizontal(
        [q1_2024, q1_2025, q2_2025], calculated_at=NOW, comparison="sequential"
    )
    q2_seq = next(
        r
        for r in sequential
        if r.metric_name == "revenue_growth"
        and r.current_period.period_end.isoformat() == "2025-06-30"
    )
    assert q2_seq.percentage_change == Decimal("20")


def test_duplicate_period_and_currency_mismatch_do_not_choose_a_source() -> None:
    prior_a = snapshot(
        "a", "balance_sheet", None, "2024-12-31", (value("a", "total_assets", "100"),)
    )
    prior_b = snapshot(
        "b", "balance_sheet", None, "2024-12-31", (value("b", "total_assets", "110"),)
    )
    current = snapshot(
        "c", "balance_sheet", None, "2025-12-31", (value("c", "total_assets", "150"),)
    )
    result = by_name(
        calculate_horizontal([prior_a, prior_b, current], calculated_at=NOW),
        "assets_growth",
        2025,
    )
    assert result.status == "unavailable"
    assert "duplicate_period" in {w.code for w in result.warnings}

    euros = snapshot(
        "e",
        "balance_sheet",
        None,
        "2024-12-31",
        (value("e", "total_assets", "100"),),
        currency="EUR",
    )
    mixed = by_name(
        calculate_horizontal([euros, current], calculated_at=NOW), "assets_growth", 2025
    )
    assert mixed.status == "unavailable"
    assert mixed.current_value == Decimal("150")
    assert mixed.previous_value == Decimal("100")
    assert mixed.absolute_change is None
    assert "currency_mismatch" in {w.code for w in mixed.warnings}

    current_copy = snapshot(
        "c2",
        "balance_sheet",
        None,
        "2025-12-31",
        (value("c2", "total_assets", "151"),),
    )
    duplicated_current = by_name(
        calculate_horizontal([prior_a, current, current_copy], calculated_at=NOW),
        "assets_growth",
        2025,
    )
    assert duplicated_current.status == "unavailable"
    assert "duplicate_period" in {w.code for w in duplicated_current.warnings}


def test_fiscal_year_end_leap_day_matches_prior_month_end() -> None:
    earlier = snapshot(
        "old",
        "income_statement",
        "2023-03-01",
        "2024-02-29",
        (value("old", "revenue", "100"),),
    )
    current = snapshot(
        "new",
        "income_statement",
        "2024-03-01",
        "2025-02-28",
        (value("new", "revenue", "110"),),
    )
    result = by_name(
        calculate_horizontal([earlier, current], calculated_at=NOW),
        "revenue_growth",
        2025,
    )
    assert result.percentage_change == Decimal("10")


def test_sequential_balance_sheet_warns_about_long_gap() -> None:
    old = snapshot(
        "old",
        "balance_sheet",
        None,
        "2020-12-31",
        (value("old", "total_assets", "100"),),
    )
    current = snapshot(
        "new",
        "balance_sheet",
        None,
        "2025-12-31",
        (value("new", "total_assets", "150"),),
    )
    result = by_name(
        calculate_horizontal(
            [old, current], calculated_at=NOW, comparison="sequential"
        ),
        "assets_growth",
        2025,
    )
    assert result.percentage_change == Decimal("50")
    assert "long_balance_gap" in {warning.code for warning in result.warnings}


def test_missing_debt_component_and_capex_cannot_be_assumed_zero() -> None:
    old_bs = snapshot(
        "old",
        "balance_sheet",
        None,
        "2024-12-31",
        (value("old", "short_term_debt", "10"),),
    )
    new_bs = snapshot(
        "new",
        "balance_sheet",
        None,
        "2025-12-31",
        (value("new", "short_term_debt", "15"), value("new", "long_term_debt", "25")),
    )
    debt = by_name(
        calculate_horizontal([old_bs, new_bs], calculated_at=NOW), "debt_growth", 2025
    )
    assert debt.status == "unavailable"
    assert "missing_input" in {w.code for w in debt.warnings}

    old_cf = snapshot(
        "oldcf",
        "cash_flow_statement",
        "2024-01-01",
        "2024-12-31",
        (value("oldcf", "operating_cash_flow", "20"),),
    )
    new_cf = snapshot(
        "newcf",
        "cash_flow_statement",
        "2025-01-01",
        "2025-12-31",
        (
            value("newcf", "operating_cash_flow", "30"),
            value("newcf", "capital_expenditure", "-10"),
        ),
    )
    fcf = by_name(
        calculate_horizontal([old_cf, new_cf], calculated_at=NOW),
        "free_cash_flow_growth",
        2025,
    )
    assert fcf.status == "unavailable"
    assert "missing_input" in {w.code for w in fcf.warnings}


def test_common_size_income_uses_revenue_and_preserves_losses() -> None:
    report = snapshot(
        "is",
        "income_statement",
        "2025-01-01",
        "2025-12-31",
        (
            value("is", "revenue", "1000", row=1),
            value("is", "cost_of_revenue", "600", row=2),
            value("is", "gross_profit", "400", row=3),
            value("is", "net_income", "-100", row=4),
        ),
    )
    results = {
        item.field: item for item in calculate_common_size(report, calculated_at=NOW)
    }
    assert {name: item.percentage for name, item in results.items()} == {
        "revenue": Decimal("100"),
        "cost_of_revenue": Decimal("60"),
        "gross_profit": Decimal("40"),
        "net_income": Decimal("-10"),
    }
    assert results["net_income"].amount == Decimal("-100")
    assert {ref.line_item_id for ref in results["net_income"].source_refs} == {
        "is-net_income-4",
        "is-revenue-1",
    }
    assert report.values[3].normalized_value == Decimal("-100")


def test_common_size_balance_uses_total_assets() -> None:
    report = snapshot(
        "bs",
        "balance_sheet",
        None,
        "2025-12-31",
        (
            value("bs", "total_assets", "2000"),
            value("bs", "total_current_assets", "600"),
            value("bs", "shareholders_equity", "800"),
            value("bs", "treasury_stock", "-100"),
        ),
    )
    results = {
        item.field: item for item in calculate_common_size(report, calculated_at=NOW)
    }
    assert results["total_assets"].percentage == Decimal("100")
    assert results["total_current_assets"].percentage == Decimal("30")
    assert results["shareholders_equity"].percentage == Decimal("40")
    assert results["treasury_stock"].percentage == Decimal("-5")
    assert results["total_assets"].period.period_type == "instant"


@pytest.mark.parametrize("base", ["0", "-100"])
def test_common_size_nonpositive_base_is_unavailable(base: str) -> None:
    report = snapshot(
        "is",
        "income_statement",
        "2025-01-01",
        "2025-12-31",
        (value("is", "revenue", base), value("is", "net_income", "10")),
    )
    result = next(
        r
        for r in calculate_common_size(report, calculated_at=NOW)
        if r.field == "net_income"
    )
    assert result.status == "unavailable"
    assert result.percentage is None
    assert "nonpositive_base" in {w.code for w in result.warnings}


def test_common_size_missing_base_and_unaccepted_line_are_visible() -> None:
    missing = snapshot(
        "is",
        "income_statement",
        "2025-01-01",
        "2025-12-31",
        (value("is", "net_income", "10"),),
    )
    result = calculate_common_size(missing, calculated_at=NOW)[0]
    assert result.status == "unavailable"
    assert "missing_input" in {w.code for w in result.warnings}

    suggested = snapshot(
        "is2",
        "income_statement",
        "2025-01-01",
        "2025-12-31",
        (
            value("is2", "revenue", "100"),
            value("is2", "net_income", "10", status="suggested"),
        ),
    )
    net = next(
        r
        for r in calculate_common_size(suggested, calculated_at=NOW)
        if r.field == "net_income"
    )
    assert net.status == "unavailable"
    assert "missing_input" in {w.code for w in net.warnings}


def test_unresolved_period_and_wrong_statement_type_are_rejected_or_unavailable() -> (
    None
):
    cash = snapshot(
        "cf",
        "cash_flow_statement",
        "2025-01-01",
        "2025-12-31",
        (value("cf", "operating_cash_flow", "20"),),
    )
    with pytest.raises(ValueError, match="income or balance"):
        calculate_common_size(cash, calculated_at=NOW)
    with pytest.raises(ValueError, match="timezone"):
        calculate_horizontal([cash], calculated_at=datetime(2026, 1, 1))


def test_common_size_rejects_conflicting_values_and_currency() -> None:
    conflicting = snapshot(
        "is",
        "income_statement",
        "2025-01-01",
        "2025-12-31",
        (
            value("is", "revenue", "100", row=1),
            value("is", "net_income", "10", row=2),
            value("is", "net_income", "20", row=3),
        ),
    )
    net = next(
        result
        for result in calculate_common_size(conflicting, calculated_at=NOW)
        if result.field == "net_income"
    )
    assert net.status == "unavailable"
    assert "conflicting_input" in {warning.code for warning in net.warnings}

    mixed = snapshot(
        "is2",
        "income_statement",
        "2025-01-01",
        "2025-12-31",
        (
            value("is2", "revenue", "100"),
            value("is2", "net_income", "10", currency="EUR"),
        ),
    )
    result = next(
        item
        for item in calculate_common_size(mixed, calculated_at=NOW)
        if item.field == "net_income"
    )
    assert result.status == "unavailable"
    assert "currency_mismatch" in {warning.code for warning in result.warnings}
