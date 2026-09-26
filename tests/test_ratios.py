"""Hand-calculated ratios, provenance, and unavailable cases."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance import FORMULAS, calculate_ratios
from normalization import SourceLocation, normalize_period
from validation import SourceRef, StatementSnapshot, ValidationValue

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def item(
    statement_id: str,
    field: str,
    amount: str,
    *,
    row: int = 1,
    currency: str | None = None,
    unit: str | None = None,
    status: str = "accepted",
) -> ValidationValue:
    return ValidationValue(
        field=field,
        normalized_value=Decimal(amount),
        source_ref=SourceRef(
            statement_id,
            f"{statement_id}-{field}-{row}",
            SourceLocation(sheet="Statement", cell=f"B{row}", row=row),
        ),
        currency=currency,
        unit_scale=unit,
        original_value=amount,
        status=status,  # type: ignore[arg-type]
    )


def income(
    *,
    statement_id: str = "income",
    start: str = "2025-01-01",
    end: str = "2025-12-31",
    currency: str = "USD",
    company: str = "company-1",
    values: tuple[ValidationValue, ...] | None = None,
) -> StatementSnapshot:
    return StatementSnapshot(
        id=statement_id,
        company_id=company,
        document_id=f"doc-{statement_id}",
        statement_type="income_statement",
        period=normalize_period("income_statement", start=start, end=end),
        values=values
        if values is not None
        else (
            item(statement_id, "revenue", "1000", row=1),
            item(statement_id, "cost_of_revenue", "600", row=2),
            item(statement_id, "gross_profit", "400", row=3),
            item(statement_id, "operating_income", "200", row=4),
            item(statement_id, "net_income", "120", row=5),
            item(statement_id, "interest_expense", "40", row=6),
        ),
        currency=currency,
        unit_scale="ones",
    )


def balance(
    statement_id: str,
    end: str,
    *,
    currency: str = "USD",
    company: str = "company-1",
    opening: bool = False,
    values: tuple[ValidationValue, ...] | None = None,
) -> StatementSnapshot:
    return StatementSnapshot(
        id=statement_id,
        company_id=company,
        document_id=f"doc-{statement_id}",
        statement_type="balance_sheet",
        period=normalize_period("balance_sheet", end=end),
        values=values
        if values is not None
        else (
            (
                item(statement_id, "total_assets", "1800", row=1),
                item(statement_id, "shareholders_equity", "700", row=2),
                item(statement_id, "accounts_receivable", "150", row=3),
                item(statement_id, "inventory", "80", row=4),
            )
            if opening
            else (
                item(statement_id, "total_assets", "2000", row=1),
                item(statement_id, "shareholders_equity", "800", row=2),
                item(statement_id, "total_current_assets", "600", row=3),
                item(statement_id, "inventory", "100", row=4),
                item(statement_id, "total_current_liabilities", "300", row=5),
                item(statement_id, "short_term_debt", "100", row=6),
                item(statement_id, "long_term_debt", "300", row=7),
                item(statement_id, "accounts_receivable", "200", row=8),
            )
        ),
        currency=currency,
        unit_scale="ones",
    )


def results(
    income_statement: StatementSnapshot | None = None,
    ending: StatementSnapshot | None = None,
    opening: StatementSnapshot | None = None,
) -> dict:
    return {
        metric.metric_name: metric
        for metric in calculate_ratios(
            income_statement=income_statement,
            ending_balance_sheet=ending,
            opening_balance_sheet=opening,
            calculated_at=NOW,
        )
    }


def test_all_twelve_ratios_match_hand_calculations() -> None:
    metrics = results(
        income(),
        balance("end", "2025-12-31"),
        balance("open", "2024-12-31", opening=True),
    )
    assert len(metrics) == 12
    expected = {
        "gross_margin": (Decimal("40"), Decimal("400"), Decimal("1000")),
        "operating_margin": (Decimal("20"), Decimal("200"), Decimal("1000")),
        "net_margin": (Decimal("12"), Decimal("120"), Decimal("1000")),
        "return_on_assets": (
            Decimal("120") / Decimal("1900") * 100,
            Decimal("120"),
            Decimal("1900"),
        ),
        "return_on_equity": (Decimal("16"), Decimal("120"), Decimal("750")),
        "current_ratio": (Decimal("2"), Decimal("600"), Decimal("300")),
        "quick_ratio": (
            Decimal("500") / Decimal("300"),
            Decimal("500"),
            Decimal("300"),
        ),
        "debt_to_equity": (Decimal("0.5"), Decimal("400"), Decimal("800")),
        "interest_coverage": (Decimal("5"), Decimal("200"), Decimal("40")),
        "asset_turnover": (
            Decimal("1000") / Decimal("1900"),
            Decimal("1000"),
            Decimal("1900"),
        ),
        "receivables_turnover": (
            Decimal("1000") / Decimal("175"),
            Decimal("1000"),
            Decimal("175"),
        ),
        "inventory_turnover": (
            Decimal("600") / Decimal("90"),
            Decimal("600"),
            Decimal("90"),
        ),
    }
    for name, (value, numerator, denominator) in expected.items():
        result = metrics[name]
        assert result.status == "calculated", name
        assert result.numerator == numerator, name
        assert result.denominator == denominator, name
        assert abs(result.value - value) < Decimal("0.0000000001"), name
        assert result.formula_id == FORMULAS[name].formula_id
        assert result.calculated_at == NOW
        assert result.source_refs
    assert metrics["gross_margin"].unit == "percent"
    assert metrics["current_ratio"].unit == "times"
    assert metrics["return_on_assets"].period.period_type == "annual"
    assert {ref.statement_id for ref in metrics["return_on_assets"].source_refs} == {
        "income",
        "end",
        "open",
    }
    assert {item.name for item in metrics["return_on_assets"].inputs} == {
        "income.net_income",
        "ending_balance.total_assets",
        "opening_balance.total_assets",
    }


def test_average_balance_falls_back_only_when_opening_is_missing() -> None:
    metrics = results(income(), balance("end", "2025-12-31"))
    roa = metrics["return_on_assets"]
    assert roa.denominator == Decimal("2000")
    assert roa.value == Decimal("6")
    assert "ending_balance_only" in {warning.code for warning in roa.warnings}
    assert metrics["current_ratio"].warnings == ()

    no_receivables = balance(
        "open",
        "2024-12-31",
        opening=True,
        values=(item("open", "total_assets", "1800"),),
    )
    partial = results(income(), balance("end", "2025-12-31"), no_receivables)
    assert partial["asset_turnover"].denominator == Decimal("1900")
    assert partial["receivables_turnover"].denominator == Decimal("200")
    assert "ending_balance_only" in {
        warning.code for warning in partial["receivables_turnover"].warnings
    }


def test_missing_and_suggested_inputs_stay_unavailable() -> None:
    report = income(values=(item("income", "revenue", "1000", status="suggested"),))
    metrics = results(report)
    gross = metrics["gross_margin"]
    assert gross.status == "unavailable"
    assert gross.value is None
    assert "missing_input" in {warning.code for warning in gross.warnings}
    assert metrics["current_ratio"].status == "unavailable"
    assert "missing_statement" in {
        warning.code for warning in metrics["current_ratio"].warnings
    }


def test_zero_denominator_never_returns_infinity() -> None:
    report = income(
        values=(
            item("income", "revenue", "0"),
            item("income", "gross_profit", "20"),
            item("income", "operating_income", "50"),
            item("income", "interest_expense", "0"),
        )
    )
    metrics = results(report)
    for name in ("gross_margin", "interest_coverage"):
        result = metrics[name]
        assert result.status == "unavailable"
        assert result.value is None
        assert result.denominator == 0
        assert "zero_denominator" in {warning.code for warning in result.warnings}

    ending = balance(
        "end",
        "2025-12-31",
        values=(
            item("end", "total_current_assets", "100"),
            item("end", "total_current_liabilities", "0"),
        ),
    )
    assert results(ending=ending)["current_ratio"].status == "unavailable"


def test_currency_mismatch_blocks_cross_statement_ratios_only() -> None:
    metrics = results(income(), balance("end", "2025-12-31", currency="EUR"))
    assert metrics["gross_margin"].status == "calculated"
    roa = metrics["return_on_assets"]
    assert roa.status == "unavailable"
    assert "currency_mismatch" in {warning.code for warning in roa.warnings}
    assert metrics["current_ratio"].status == "calculated"

    opening = balance("open", "2024-12-31", currency="EUR", opening=True)
    with_opening = results(income(), balance("end", "2025-12-31"), opening)
    assert with_opening["return_on_assets"].status == "unavailable"
    assert "currency_mismatch" in {
        warning.code for warning in with_opening["return_on_assets"].warnings
    }


def test_missing_inventory_does_not_become_zero() -> None:
    ending = balance(
        "end",
        "2025-12-31",
        values=(
            item("end", "total_current_assets", "600"),
            item("end", "total_current_liabilities", "300"),
        ),
    )
    metrics = results(ending=ending)
    assert metrics["current_ratio"].value == Decimal("2")
    assert metrics["quick_ratio"].status == "unavailable"
    assert "missing_input" in {
        warning.code for warning in metrics["quick_ratio"].warnings
    }


def test_conflicting_duplicate_values_are_not_selected() -> None:
    report = income(
        values=(
            item("income", "revenue", "1000", row=1),
            item("income", "revenue", "1100", row=2),
            item("income", "gross_profit", "400", row=3),
        )
    )
    margin = results(report)["gross_margin"]
    assert margin.status == "unavailable"
    assert "conflicting_input" in {warning.code for warning in margin.warnings}


def test_negative_denominator_is_visible() -> None:
    ending = balance(
        "end",
        "2025-12-31",
        values=(
            item("end", "short_term_debt", "100"),
            item("end", "long_term_debt", "300"),
            item("end", "shareholders_equity", "-200"),
        ),
    )
    metric = results(ending=ending)["debt_to_equity"]
    assert metric.value == Decimal("-2")
    assert "negative_denominator" in {warning.code for warning in metric.warnings}


def test_period_and_company_mismatches_are_rejected() -> None:
    with pytest.raises(ValueError, match="Ending balance date"):
        results(income(), balance("end", "2025-09-30"))
    with pytest.raises(ValueError, match="Opening balance date"):
        results(
            income(),
            balance("end", "2025-12-31"),
            balance("open", "2025-01-01", opening=True),
        )
    with pytest.raises(ValueError, match="one company"):
        results(income(), balance("end", "2025-12-31", company="other"))


def test_quarterly_turnover_is_not_annualized() -> None:
    flow = income(start="2025-04-01", end="2025-06-30")
    ending = balance("end", "2025-06-30")
    opening = balance("open", "2025-03-31", opening=True)
    metric = results(flow, ending, opening)["asset_turnover"]
    assert metric.period.period_type == "quarterly"
    assert abs(metric.value - Decimal("1000") / Decimal("1900")) < Decimal(
        "0.0000000001"
    )


def test_registry_is_complete_and_formula_details_are_explicit() -> None:
    assert len(FORMULAS) == 12
    assert all(
        formula.formula_id and formula.expression for formula in FORMULAS.values()
    )
    assert all(formula.required_inputs for formula in FORMULAS.values())
    assert all(formula.zero_denominator_behavior for formula in FORMULAS.values())
    assert all(formula.missing_behavior for formula in FORMULAS.values())
    assert all(
        formula.ending_only_behavior
        for formula in FORMULAS.values()
        if formula.prefers_average
    )
    with pytest.raises(TypeError):
        FORMULAS["gross_margin"] = FORMULAS["net_margin"]  # type: ignore[index]


def test_timestamp_is_explicit_and_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone"):
        calculate_ratios(income_statement=income(), calculated_at=datetime(2026, 1, 1))
