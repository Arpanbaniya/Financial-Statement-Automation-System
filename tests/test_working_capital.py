"""Hand-checked working capital examples and unavailable cases."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from finance import calculate_working_capital
from normalization import SourceLocation, normalize_period
from validation import SourceRef, StatementSnapshot, ValidationValue

NOW = datetime(2026, 9, 26, tzinfo=UTC)


def item(
    statement_id: str, field: str, amount: str, *, status: str = "accepted"
) -> ValidationValue:
    return ValidationValue(
        field=field,
        normalized_value=Decimal(amount),
        source_ref=SourceRef(
            statement_id, field, SourceLocation(sheet="Sheet1", cell="B2")
        ),
        currency="USD",
        unit_scale="ones",
        status=status,  # type: ignore[arg-type]
    )


def income(
    *,
    start: str = "2025-01-01",
    end: str = "2025-12-31",
    revenue: str = "1000",
    cost: str = "600",
) -> StatementSnapshot:
    return StatementSnapshot(
        id="income",
        company_id="company",
        document_id="doc-income",
        statement_type="income_statement",
        period=normalize_period("income_statement", start=start, end=end),
        values=(
            item("income", "revenue", revenue),
            item("income", "cost_of_revenue", cost),
        ),
        currency="USD",
        unit_scale="ones",
    )


def balance(
    statement_id: str,
    end: str,
    *,
    ar: str = "150",
    inventory: str = "100",
    ap: str = "90",
    assets: str = "600",
    liabilities: str = "300",
    include_ap: bool = True,
) -> StatementSnapshot:
    amounts = [
        ("accounts_receivable", ar),
        ("inventory", inventory),
        ("total_current_assets", assets),
        ("total_current_liabilities", liabilities),
    ]
    if include_ap:
        amounts.append(("accounts_payable", ap))
    return StatementSnapshot(
        id=statement_id,
        company_id="company",
        document_id=f"doc-{statement_id}",
        statement_type="balance_sheet",
        period=normalize_period("balance_sheet", end=end),
        values=tuple(item(statement_id, field, amount) for field, amount in amounts),
        currency="USD",
        unit_scale="ones",
    )


def results(
    flow: StatementSnapshot | None,
    ending: StatementSnapshot | None,
    opening: StatementSnapshot | None = None,
) -> dict:
    return {
        metric.metric_name: metric
        for metric in calculate_working_capital(
            income_statement=flow,
            ending_balance_sheet=ending,
            opening_balance_sheet=opening,
            calculated_at=NOW,
        )
    }


def test_hand_calculated_metrics_and_provenance() -> None:
    metrics = results(
        income(),
        balance("ending", "2025-12-31"),
        balance("opening", "2024-12-31", ar="100", inventory="80", ap="60"),
    )
    assert len(metrics) == 5
    assert metrics["net_working_capital"].value == Decimal("300")
    assert metrics["net_working_capital"].unit == "currency"
    assert metrics["dso"].value == Decimal("45.625")
    assert metrics["dio"].value == Decimal("54.75")
    assert metrics["dpo"].value == Decimal("45.625")
    assert metrics["cash_conversion_cycle"].value == Decimal("54.75")
    assert metrics["dso"].days_in_period == 365
    assert metrics["dso"].numerator == Decimal("125")
    assert metrics["dso"].denominator == Decimal("1000")
    assert metrics["dpo"].denominator == Decimal("600")
    assert {
        ref.statement_id for ref in metrics["cash_conversion_cycle"].source_refs
    } == {"income", "ending", "opening"}
    assert metrics["cash_conversion_cycle"].formula_id == "cash_conversion_cycle_v1"
    assert all(metric.calculated_at == NOW for metric in metrics.values())


def test_actual_period_days_and_ending_only_warning() -> None:
    metrics = results(
        income(start="2024-01-01", end="2024-12-31"),
        balance("ending", "2024-12-31"),
    )
    assert metrics["dso"].days_in_period == 366
    assert metrics["dso"].value == Decimal("54.9")
    assert any(w.code == "ending_balance_only" for w in metrics["dso"].warnings)
    quarter = results(
        income(start="2025-01-01", end="2025-03-31"),
        balance("ending", "2025-03-31"),
    )
    assert quarter["dso"].days_in_period == 90
    assert quarter["dso"].value == Decimal("13.5")


def test_missing_component_and_nonpositive_flow_do_not_invent_ccc() -> None:
    metrics = results(
        income(cost="0"), balance("ending", "2025-12-31", include_ap=False)
    )
    assert metrics["dso"].status == "calculated"
    assert metrics["dio"].status == "unavailable"
    assert any(w.code == "nonpositive_denominator" for w in metrics["dio"].warnings)
    assert metrics["dpo"].status == "unavailable"
    assert metrics["cash_conversion_cycle"].status == "unavailable"
    assert metrics["cash_conversion_cycle"].value is None
    assert any(
        w.code == "missing_component" for w in metrics["cash_conversion_cycle"].warnings
    )


def test_missing_opening_line_uses_ending_but_conflicting_currency_blocks() -> None:
    opening = balance("opening", "2024-12-31", include_ap=False)
    metrics = results(income(), balance("ending", "2025-12-31"), opening)
    assert metrics["dpo"].value == Decimal("54.75")
    assert any(w.code == "ending_balance_only" for w in metrics["dpo"].warnings)

    wrong_currency = StatementSnapshot(
        id="opening",
        company_id="company",
        document_id="doc-opening",
        statement_type="balance_sheet",
        period=normalize_period("balance_sheet", end="2024-12-31"),
        values=(
            ValidationValue(
                field="accounts_receivable",
                normalized_value=Decimal("100"),
                source_ref=SourceRef("opening", "ar"),
                currency="EUR",
                unit_scale="ones",
                status="accepted",
            ),
        ),
        currency="EUR",
        unit_scale="ones",
    )
    mismatched = results(income(), balance("ending", "2025-12-31"), wrong_currency)
    assert mismatched["dso"].status == "unavailable"
    assert mismatched["cash_conversion_cycle"].status == "unavailable"


def test_negative_nwc_and_negative_average_balance() -> None:
    metrics = results(
        income(),
        balance("ending", "2025-12-31", ar="-150", assets="200", liabilities="300"),
    )
    assert metrics["net_working_capital"].value == Decimal("-100")
    assert metrics["dso"].status == "unavailable"
    assert any(w.code == "negative_balance" for w in metrics["dso"].warnings)


def test_missing_income_and_unaccepted_values() -> None:
    ending = balance("ending", "2025-12-31")
    no_income = results(None, ending)
    assert no_income["net_working_capital"].value == Decimal("300")
    assert all(
        no_income[name].status == "unavailable"
        for name in ("dso", "dio", "dpo", "cash_conversion_cycle")
    )

    pending = StatementSnapshot(
        id="ending",
        company_id="company",
        document_id="doc-ending",
        statement_type="balance_sheet",
        period=normalize_period("balance_sheet", end="2025-12-31"),
        values=(
            item("ending", "accounts_receivable", "150", status="suggested"),
            item("ending", "inventory", "0"),
            item("ending", "accounts_payable", "0"),
        ),
        currency="USD",
        unit_scale="ones",
    )
    metrics = results(income(), pending)
    assert metrics["dso"].status == "unavailable"
    assert any(w.code == "missing_input" for w in metrics["dso"].warnings)
    assert metrics["dio"].value == Decimal("0")
    assert metrics["dpo"].value == Decimal("0")


def test_period_pairing_and_timestamp_validation() -> None:
    with pytest.raises(ValueError, match="Ending balance date"):
        results(income(), balance("ending", "2024-12-31"))
    with pytest.raises(ValueError, match="Opening balance date"):
        results(
            income(), balance("ending", "2025-12-31"), balance("opening", "2025-01-01")
        )
    with pytest.raises(ValueError, match="timezone"):
        calculate_working_capital(calculated_at=datetime(2026, 9, 26))
