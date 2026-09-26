"""Cash flow arithmetic, signed CapEx, and period comparisons."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance import calculate_cash_flow, calculate_horizontal, compare_cash_flow
from normalization import SourceLocation, normalize_period
from validation import SourceRef, StatementSnapshot, ValidationValue

NOW = datetime(2026, 9, 26, tzinfo=UTC)


def value(
    statement_id: str, field: str, amount: str, status: str = "accepted"
) -> ValidationValue:
    return ValidationValue(
        field=field,
        normalized_value=Decimal(amount),
        source_ref=SourceRef(statement_id, field, SourceLocation(page=2)),
        currency="USD",
        unit_scale="ones",
        status=status,  # type: ignore[arg-type]
    )


def snapshot(
    kind: str,
    statement_id: str,
    start: str,
    end: str,
    amounts: dict[str, str],
) -> StatementSnapshot:
    return StatementSnapshot(
        id=statement_id,
        company_id="company",
        document_id=f"doc-{statement_id}",
        statement_type=kind,  # type: ignore[arg-type]
        period=normalize_period(kind, start=start, end=end),  # type: ignore[arg-type]
        values=tuple(
            value(statement_id, field, amount) for field, amount in amounts.items()
        ),
        currency="USD",
        unit_scale="ones",
    )


def metrics(capex: str = "-30", net_income: str = "80") -> dict:
    cash = snapshot(
        "cash_flow_statement",
        "cash",
        "2025-01-01",
        "2025-12-31",
        {
            "operating_cash_flow": "120",
            "investing_cash_flow": "-50",
            "financing_cash_flow": "20",
            "capital_expenditure": capex,
        },
    )
    income = snapshot(
        "income_statement",
        "income",
        "2025-01-01",
        "2025-12-31",
        {"net_income": net_income},
    )
    return {
        item.metric_name: item
        for item in calculate_cash_flow(
            cash_flow_statement=cash,
            income_statement=income,
            calculated_at=NOW,
        )
    }


def test_cash_flow_values_and_source_trail() -> None:
    result = metrics()
    assert result["operating_cash_flow"].value == Decimal("120")
    assert result["investing_cash_flow"].value == Decimal("-50")
    assert result["financing_cash_flow"].value == Decimal("20")
    assert result["capital_expenditure_outflow"].value == Decimal("30")
    assert result["free_cash_flow"].value == Decimal("90")
    assert result["cash_conversion_gap"].value == Decimal("40")
    assert result["cash_conversion_ratio"].value == Decimal("1.5")
    assert {
        ref.statement_id for ref in result["cash_conversion_ratio"].source_refs
    } == {"cash", "income"}


def test_capex_sign_prevents_double_negation() -> None:
    positive = metrics("30")
    assert positive["free_cash_flow"].status == "unavailable"
    assert positive["capital_expenditure_outflow"].status == "unavailable"
    assert any(w.code == "positive_capex" for w in positive["free_cash_flow"].warnings)
    zero = metrics("0")
    assert zero["capital_expenditure_outflow"].value == Decimal("0")
    assert zero["free_cash_flow"].value == Decimal("120")

    previous = snapshot(
        "cash_flow_statement",
        "prior",
        "2024-01-01",
        "2024-12-31",
        {"operating_cash_flow": "100", "capital_expenditure": "-20"},
    )
    current = snapshot(
        "cash_flow_statement",
        "current",
        "2025-01-01",
        "2025-12-31",
        {"operating_cash_flow": "120", "capital_expenditure": "30"},
    )
    growth = next(
        item
        for item in calculate_horizontal((previous, current), calculated_at=NOW)
        if item.metric_name == "free_cash_flow_growth"
        and item.current_period.period_end.year == 2025
    )
    assert growth.status == "unavailable"
    assert growth.current_value is None


def test_conversion_ratio_needs_positive_profit_but_gap_can_be_negative() -> None:
    result = metrics("-30", "-20")
    assert result["cash_conversion_gap"].value == Decimal("140")
    assert result["cash_conversion_ratio"].status == "unavailable"
    assert any(
        w.code == "nonpositive_net_income"
        for w in result["cash_conversion_ratio"].warnings
    )


def test_missing_and_suggested_inputs_stay_unavailable() -> None:
    cash = snapshot(
        "cash_flow_statement",
        "cash",
        "2025-01-01",
        "2025-12-31",
        {"operating_cash_flow": "100"},
    )
    result = {
        item.metric_name: item
        for item in calculate_cash_flow(
            cash_flow_statement=cash,
            calculated_at=NOW,
        )
    }
    assert result["free_cash_flow"].status == "unavailable"
    assert result["cash_conversion_ratio"].status == "unavailable"
    assert result["operating_cash_flow"].value == Decimal("100")


def test_trend_and_mismatched_periods() -> None:
    current = tuple(metrics().values())
    previous_cash = snapshot(
        "cash_flow_statement",
        "prior",
        "2024-01-01",
        "2024-12-31",
        {
            "operating_cash_flow": "100",
            "investing_cash_flow": "-60",
            "financing_cash_flow": "10",
            "capital_expenditure": "-20",
            "net_income": "70",
        },
    )
    previous = calculate_cash_flow(cash_flow_statement=previous_cash, calculated_at=NOW)
    trends = {item.metric_name: item for item in compare_cash_flow(current, previous)}
    assert trends["operating_cash_flow"].absolute_change == Decimal("20")
    assert trends["operating_cash_flow"].percentage_change == Decimal("20")
    assert trends["free_cash_flow"].absolute_change == Decimal("10")
    wrong = snapshot(
        "income_statement",
        "wrong",
        "2025-04-01",
        "2025-12-31",
        {"net_income": "80"},
    )
    with pytest.raises(ValueError, match="periods must match"):
        calculate_cash_flow(
            cash_flow_statement=snapshot(
                "cash_flow_statement",
                "cash",
                "2025-01-01",
                "2025-12-31",
                {"operating_cash_flow": "120"},
            ),
            income_statement=wrong,
            calculated_at=NOW,
        )
