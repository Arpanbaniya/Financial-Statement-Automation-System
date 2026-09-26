"""Reconciliation checks use accepted source values without rewriting them."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from normalization import SourceLocation, normalize_period
from validation import (
    SourceRef,
    StatementSnapshot,
    TolerancePolicy,
    ValidationResult,
    ValidationValue,
    validate_statements,
)


def value(
    statement_id: str,
    field: str,
    amount: str | None,
    *,
    row: int = 1,
    currency: str | None = None,
    unit: str | None = None,
    status: str = "accepted",
) -> ValidationValue:
    return ValidationValue(
        field=field,
        normalized_value=Decimal(amount) if amount is not None else None,
        source_ref=SourceRef(
            statement_id,
            line_item_id=f"{statement_id}-{field}-{row}",
            location=SourceLocation(page=1, row=row),
        ),
        currency=currency,
        unit_scale=unit,
        original_value=amount,
        status=status,  # type: ignore[arg-type]
    )


def statement(
    statement_id: str,
    kind: str,
    values: tuple[ValidationValue, ...],
    *,
    company: str = "company-1",
    start: str = "2025-01-01",
    end: str = "2025-12-31",
    currency: str | None = "USD",
    unit: str | None = "ones",
    current_assets_complete: bool = False,
    current_liabilities_complete: bool = False,
    operating_structure: bool = False,
    cash_components: bool = False,
) -> StatementSnapshot:
    return StatementSnapshot(
        id=statement_id,
        company_id=company,
        document_id=f"doc-{statement_id}",
        statement_type=kind,  # type: ignore[arg-type]
        period=normalize_period(
            kind,  # type: ignore[arg-type]
            start=None if kind == "balance_sheet" else start,
            end=end,
        ),
        values=values,
        currency=currency,
        unit_scale=unit,
        current_assets_components_complete=current_assets_complete,
        current_liabilities_components_complete=current_liabilities_complete,
        operating_expenses_exclude_cost=operating_structure,
        cash_flow_components_complete=cash_components,
    )


def check(results: tuple[ValidationResult, ...], name: str) -> ValidationResult:
    return next(result for result in results if result.check_name == name)


def test_accounting_equation_passes_with_small_rounding_difference() -> None:
    values = (
        value("bs", "total_assets", "1000.5", row=10),
        value("bs", "total_liabilities", "600", row=11),
        value("bs", "shareholders_equity", "400", row=12),
    )
    snapshot = statement("bs", "balance_sheet", values)
    result = check(validate_statements([snapshot]), "accounting_equation")
    assert result.status == "pass"
    assert result.expected_value == Decimal("1000")
    assert result.actual_value == Decimal("1000.5")
    assert result.difference == Decimal("0.5")
    assert result.tolerance == Decimal("1")
    assert result.severity == "info"
    assert {ref.line_item_id for ref in result.source_refs} == {
        "bs-total_assets-10",
        "bs-total_liabilities-11",
        "bs-shareholders_equity-12",
    }
    assert snapshot.values == values


def test_accounting_equation_fails_beyond_tolerance() -> None:
    snapshot = statement(
        "bs",
        "balance_sheet",
        (
            value("bs", "total_assets", "1050"),
            value("bs", "total_liabilities", "600"),
            value("bs", "shareholders_equity", "400"),
        ),
    )
    result = check(validate_statements([snapshot]), "accounting_equation")
    assert result.status == "fail"
    assert result.difference == Decimal("50")
    assert result.severity == "error"


def test_subtotals_only_run_when_all_components_are_present() -> None:
    full = statement(
        "bs",
        "balance_sheet",
        (
            value("bs", "cash_and_cash_equivalents", "10"),
            value("bs", "short_term_investments", "20"),
            value("bs", "accounts_receivable", "30"),
            value("bs", "inventory", "40"),
            value("bs", "other_current_assets", "5"),
            value("bs", "total_current_assets", "105"),
            value("bs", "accounts_payable", "20"),
            value("bs", "short_term_debt", "10"),
            value("bs", "other_current_liabilities", "5"),
            value("bs", "total_current_liabilities", "40"),
        ),
        current_assets_complete=True,
        current_liabilities_complete=True,
    )
    results = validate_statements([full])
    assert check(results, "current_assets_subtotal").status == "pass"
    assert check(results, "current_liabilities_subtotal").status == "fail"
    unconfirmed = statement("bs", "balance_sheet", full.values)
    assert (
        check(validate_statements([unconfirmed]), "current_assets_subtotal").status
        == "unavailable"
    )
    incomplete = statement("bs2", "balance_sheet", ())
    assert (
        check(validate_statements([incomplete]), "current_assets_subtotal").status
        == "unavailable"
    )


def test_gross_profit_and_operating_income_respect_structure() -> None:
    values = (
        value("is", "revenue", "1000"),
        value("is", "cost_of_revenue", "600"),
        value("is", "gross_profit", "400"),
        value("is", "operating_expenses", "250"),
        value("is", "operating_income", "150"),
    )
    guarded = statement("is", "income_statement", values)
    guarded_results = validate_statements([guarded])
    assert check(guarded_results, "gross_profit").status == "pass"
    assert check(guarded_results, "operating_income").status == "unavailable"

    confirmed = statement("is", "income_statement", values, operating_structure=True)
    assert check(validate_statements([confirmed]), "operating_income").status == "pass"


def test_cash_bridge_and_category_subtotal_are_separate() -> None:
    snapshot = statement(
        "cf",
        "cash_flow_statement",
        (
            value("cf", "beginning_cash", "100"),
            value("cf", "net_change_in_cash", "25"),
            value("cf", "ending_cash", "125"),
            value("cf", "operating_cash_flow", "30"),
            value("cf", "investing_cash_flow", "-10"),
            value("cf", "financing_cash_flow", "5"),
        ),
    )
    results = validate_statements([snapshot])
    assert check(results, "cash_bridge").status == "pass"
    assert check(results, "cash_flow_subtotal").status == "unavailable"
    complete = statement(
        "cf", "cash_flow_statement", snapshot.values, cash_components=True
    )
    assert check(validate_statements([complete]), "cash_flow_subtotal").status == "pass"


def test_missing_required_and_suggested_values_are_not_trusted() -> None:
    snapshot = statement(
        "is",
        "income_statement",
        (
            value("is", "revenue", "100", status="suggested"),
            value("is", "net_income", "20"),
        ),
    )
    results = validate_statements([snapshot])
    missing = check(results, "missing_required_fields")
    assert missing.status == "warning"
    assert "revenue" in missing.explanation
    assert check(results, "gross_profit").status == "unavailable"


def test_mixed_currencies_stop_arithmetic_and_are_reported() -> None:
    snapshot = statement(
        "bs",
        "balance_sheet",
        (
            value("bs", "total_assets", "100", currency="USD"),
            value("bs", "total_liabilities", "60", currency="EUR"),
            value("bs", "shareholders_equity", "40", currency="USD"),
        ),
    )
    results = validate_statements([snapshot])
    assert check(results, "inconsistent_currencies").status == "warning"
    assert check(results, "accounting_equation").status == "unavailable"


def test_mixed_reported_units_warn_but_scaled_values_can_reconcile() -> None:
    snapshot = statement(
        "bs",
        "balance_sheet",
        (
            value("bs", "total_assets", "1000000", unit="millions"),
            value("bs", "total_liabilities", "600000", unit="thousands"),
            value("bs", "shareholders_equity", "400000", unit="ones"),
        ),
        unit=None,
    )
    results = validate_statements([snapshot])
    assert check(results, "inconsistent_units").status == "warning"
    assert check(results, "accounting_equation").status == "pass"


def test_duplicate_periods_and_cross_statement_conflict() -> None:
    first = statement("bs1", "balance_sheet", (value("bs1", "total_assets", "100"),))
    second = statement("bs2", "balance_sheet", (value("bs2", "total_assets", "120"),))
    results = validate_statements([first, second])
    assert (
        len(
            [
                r
                for r in results
                if r.check_name == "duplicate_period" and r.status == "warning"
            ]
        )
        == 2
    )
    conflict = check(results, "cross_statement_conflict:total_assets")
    assert conflict.status == "fail"
    assert conflict.difference == Decimal("20")
    assert {ref.statement_id for ref in conflict.source_refs} == {"bs1", "bs2"}


def test_duplicate_period_different_currency_or_unknown_unit_is_not_compared() -> None:
    first = statement("bs1", "balance_sheet", (value("bs1", "total_assets", "100"),))
    euros = statement(
        "bs2",
        "balance_sheet",
        (value("bs2", "total_assets", "120"),),
        currency="EUR",
    )
    currency_results = validate_statements([first, euros])
    assert (
        check(currency_results, "cross_statement_currency:total_assets").status
        == "warning"
    )
    assert not any(
        result.check_name == "cross_statement_conflict:total_assets"
        for result in currency_results
    )

    contradictory = statement(
        "bs5",
        "balance_sheet",
        (value("bs5", "total_assets", "120", currency="EUR"),),
    )
    contradictory_results = validate_statements([first, contradictory])
    assert (
        check(contradictory_results, "cross_statement_currency:total_assets").status
        == "warning"
    )

    unknown_unit = statement(
        "bs3",
        "balance_sheet",
        (value("bs3", "total_assets", "120"),),
        unit=None,
    )
    unit_results = validate_statements([first, unknown_unit])
    assert check(unit_results, "cross_statement_units:total_assets").status == "warning"
    assert not any(
        result.check_name == "cross_statement_conflict:total_assets"
        for result in unit_results
    )

    mixed_scale = statement(
        "bs4",
        "balance_sheet",
        (value("bs4", "total_assets", "120", unit="thousands"),),
    )
    scale_results = validate_statements([first, mixed_scale])
    assert (
        check(scale_results, "cross_statement_units:total_assets").status == "warning"
    )
    assert (
        check(scale_results, "cross_statement_conflict:total_assets").status == "fail"
    )


def test_periods_are_scoped_by_company_and_type() -> None:
    first = statement("a", "balance_sheet", ())
    other_company = statement("b", "balance_sheet", (), company="company-2")
    assert all(
        result.status == "pass"
        for result in validate_statements([first, other_company])
        if result.check_name == "duplicate_period"
    )


def test_unresolved_period_does_not_create_a_false_duplicate() -> None:
    snapshot = StatementSnapshot(
        id="is",
        company_id="company-1",
        document_id="doc-is",
        statement_type="income_statement",
        period=normalize_period("income_statement", label="FY2025"),
        values=(value("is", "revenue", "100"),),
        currency="USD",
        unit_scale="ones",
    )
    result = check(validate_statements([snapshot]), "duplicate_period")
    assert result.status == "unavailable"


def test_conflicting_values_within_statement_block_equation() -> None:
    snapshot = statement(
        "bs",
        "balance_sheet",
        (
            value("bs", "total_assets", "100", row=1),
            value("bs", "total_assets", "120", row=2),
            value("bs", "total_liabilities", "60"),
            value("bs", "shareholders_equity", "40"),
        ),
    )
    results = validate_statements([snapshot])
    assert check(results, "conflicting_values:total_assets").status == "fail"
    assert check(results, "accounting_equation").status == "unavailable"


def test_equal_repeated_values_do_not_block_reconciliation() -> None:
    snapshot = statement(
        "bs",
        "balance_sheet",
        (
            value("bs", "total_assets", "100", row=1),
            value("bs", "total_assets", "100", row=2),
            value("bs", "total_liabilities", "60"),
            value("bs", "shareholders_equity", "40"),
        ),
    )
    results = validate_statements([snapshot])
    assert check(results, "conflicting_values").status == "pass"
    assert check(results, "accounting_equation").status == "pass"


def test_cash_bridge_mismatch_is_reported_without_adjustment() -> None:
    snapshot = statement(
        "cf",
        "cash_flow_statement",
        (
            value("cf", "beginning_cash", "100"),
            value("cf", "net_change_in_cash", "25"),
            value("cf", "ending_cash", "130"),
        ),
    )
    result = check(validate_statements([snapshot]), "cash_bridge")
    assert result.status == "fail"
    assert result.expected_value == Decimal("125")
    assert result.actual_value == Decimal("130")


def test_missing_currency_or_unit_prevents_unsafe_comparison() -> None:
    snapshot = statement(
        "bs",
        "balance_sheet",
        (
            value("bs", "total_assets", "100"),
            value("bs", "total_liabilities", "60"),
            value("bs", "shareholders_equity", "40"),
        ),
        currency=None,
        unit=None,
    )
    results = validate_statements([snapshot])
    assert check(results, "accounting_equation").status == "unavailable"
    assert check(results, "inconsistent_currencies").status == "warning"
    assert check(results, "inconsistent_units").status == "warning"


def test_custom_tolerance_changes_only_pass_fail_decision() -> None:
    snapshot = statement(
        "bs",
        "balance_sheet",
        (
            value("bs", "total_assets", "1002"),
            value("bs", "total_liabilities", "600"),
            value("bs", "shareholders_equity", "400"),
        ),
    )
    assert (
        check(validate_statements([snapshot]), "accounting_equation").status == "fail"
    )
    relaxed = validate_statements(
        [snapshot], tolerance=TolerancePolicy(absolute=Decimal("2"))
    )
    assert check(relaxed, "accounting_equation").status == "pass"
    assert check(relaxed, "accounting_equation").difference == Decimal("2")


def test_relative_tolerance_is_used_for_large_amounts() -> None:
    snapshot = statement(
        "bs",
        "balance_sheet",
        (
            value("bs", "total_assets", "1000000500"),
            value("bs", "total_liabilities", "600000000"),
            value("bs", "shareholders_equity", "400000000"),
        ),
    )
    result = check(validate_statements([snapshot]), "accounting_equation")
    assert result.status == "pass"
    assert result.tolerance > Decimal("500")


def test_large_decimal_values_are_compared_without_context_rounding() -> None:
    base = "10000000000000000000000000000000000000000"
    assets = str(int(base) + 1)
    snapshot = statement(
        "bs",
        "balance_sheet",
        (
            value("bs", "total_assets", assets),
            value("bs", "total_liabilities", base),
            value("bs", "shareholders_equity", "0"),
        ),
    )
    exact = validate_statements(
        [snapshot],
        tolerance=TolerancePolicy(absolute=Decimal(0), relative=Decimal(0)),
    )
    result = check(exact, "accounting_equation")
    assert result.status == "fail"
    assert result.difference == Decimal(1)


def test_invalid_input_and_immutable_results() -> None:
    with pytest.raises(ValueError, match="finite Decimal"):
        value("bs", "total_assets", "NaN")
    with pytest.raises(ValueError, match="Unknown field"):
        statement("bs", "balance_sheet", (value("bs", "revenue", "100"),))
    with pytest.raises(ValueError, match="unique"):
        same = statement("bs", "balance_sheet", ())
        validate_statements([same, same])
    result = check(
        validate_statements([statement("bs", "balance_sheet", ())]),
        "accounting_equation",
    )
    with pytest.raises(FrozenInstanceError):
        result.status = "pass"  # type: ignore[misc]
