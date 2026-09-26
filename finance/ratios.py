"""Pure ratio calculations from accepted, source-linked statement snapshots."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal

from finance.ratio_registry import FORMULAS, RatioFormula, RatioInput, RatioUnit
from normalization.periods import NormalizedPeriod
from validation.types import SourceRef, StatementSnapshot

MetricStatus = Literal["calculated", "unavailable"]


@dataclass(frozen=True, slots=True)
class MetricWarning:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class MetricInput:
    name: str
    value: Decimal
    currency: str
    statement_id: str
    source_refs: tuple[SourceRef, ...]


@dataclass(frozen=True, slots=True)
class MetricResult:
    metric_name: str
    status: MetricStatus
    value: Decimal | None
    formula_id: str
    numerator: Decimal | None
    denominator: Decimal | None
    period: NormalizedPeriod | None
    unit: RatioUnit
    calculated_at: datetime
    inputs: tuple[MetricInput, ...]
    source_refs: tuple[SourceRef, ...]
    warnings: tuple[MetricWarning, ...]


def _warning(code: str, message: str) -> MetricWarning:
    return MetricWarning(code, message)


def _select(
    snapshot: StatementSnapshot | None, requirement: RatioInput
) -> tuple[MetricInput | None, MetricWarning | None]:
    name = f"{requirement.role}.{requirement.field}"
    if snapshot is None:
        return None, _warning("missing_statement", f"No statement supplies {name}.")
    if snapshot.period.status != "normalized" or snapshot.period.period_end is None:
        return None, _warning(
            "unresolved_period", f"The period for {name} needs review."
        )
    values = tuple(
        value
        for value in snapshot.values
        if value.field == requirement.field
        and value.status == "accepted"
        and value.normalized_value is not None
    )
    if not values:
        return None, _warning("missing_input", f"No accepted value supplies {name}.")
    first = values[0]
    if any(value.normalized_value != first.normalized_value for value in values[1:]):
        return None, _warning(
            "conflicting_input", f"Accepted values for {name} disagree."
        )
    currencies = {value.currency or snapshot.currency for value in values}
    if None in currencies or len(currencies) != 1:
        return None, _warning("unresolved_currency", f"Currency for {name} is unclear.")
    if snapshot.currency and any(
        value.currency and value.currency != snapshot.currency for value in values
    ):
        return None, _warning(
            "currency_mismatch", f"Currency for {name} conflicts with its statement."
        )
    if any(
        value.unit_scale is None and snapshot.unit_scale is None for value in values
    ):
        return None, _warning("unresolved_unit", f"Unit scale for {name} is unclear.")
    return (
        MetricInput(
            name=name,
            value=first.normalized_value,
            currency=next(iter(currencies)),
            statement_id=snapshot.id,
            source_refs=tuple(dict.fromkeys(value.source_ref for value in values)),
        ),
        None,
    )


def _period(
    formula: RatioFormula,
    income: StatementSnapshot | None,
    ending_balance: StatementSnapshot | None,
) -> NormalizedPeriod | None:
    if (
        any(item.role == "income" for item in formula.numerator)
        or formula.denominator.role == "income"
    ):
        return income.period if income else None
    return ending_balance.period if ending_balance else None


def _result(
    formula: RatioFormula,
    *,
    status: MetricStatus,
    value: Decimal | None,
    numerator: Decimal | None,
    denominator: Decimal | None,
    period: NormalizedPeriod | None,
    calculated_at: datetime,
    inputs: tuple[MetricInput, ...],
    warnings: tuple[MetricWarning, ...],
) -> MetricResult:
    refs = tuple(dict.fromkeys(ref for item in inputs for ref in item.source_refs))
    return MetricResult(
        metric_name=formula.name,
        status=status,
        value=value,
        formula_id=formula.formula_id,
        numerator=numerator,
        denominator=denominator,
        period=period,
        unit=formula.output_unit,
        calculated_at=calculated_at,
        inputs=inputs,
        source_refs=refs,
        warnings=warnings,
    )


def _calculate_one(
    formula: RatioFormula,
    income: StatementSnapshot | None,
    ending_balance: StatementSnapshot | None,
    opening_balance: StatementSnapshot | None,
    calculated_at: datetime,
) -> MetricResult:
    snapshots = {
        "income": income,
        "ending_balance": ending_balance,
        "opening_balance": opening_balance,
    }
    selected: dict[str, MetricInput] = {}
    warnings: list[MetricWarning] = []
    for requirement in (*formula.numerator, formula.denominator):
        key = f"{requirement.role}.{requirement.field}"
        if key in selected:
            continue
        item, warning = _select(snapshots[requirement.role], requirement)
        if warning:
            warnings.append(warning)
        if item:
            selected[key] = item
    period = _period(formula, income, ending_balance)
    inputs = tuple(selected.values())
    numerator = (
        sum(
            (
                selected[f"{term.role}.{term.field}"].value * term.sign
                for term in formula.numerator
            ),
            Decimal(0),
        )
        if all(f"{term.role}.{term.field}" in selected for term in formula.numerator)
        else None
    )
    denominator_key = f"{formula.denominator.role}.{formula.denominator.field}"
    denominator = (
        selected[denominator_key].value if denominator_key in selected else None
    )
    blocked = False
    if formula.prefers_average and denominator is not None:
        if opening_balance is None:
            warnings.append(
                _warning(
                    "ending_balance_only",
                    "Opening balance is unavailable; ending balance was used.",
                )
            )
        else:
            opening_requirement = RatioInput(
                "opening_balance", formula.denominator.field
            )
            opening, warning = _select(opening_balance, opening_requirement)
            if opening is None:
                if warning and warning.code == "missing_input":
                    warnings.append(
                        _warning(
                            "ending_balance_only",
                            "Opening line item is missing; ending balance was used.",
                        )
                    )
                else:
                    if warning:
                        warnings.append(warning)
                    blocked = True
            else:
                current = selected[denominator_key]
                if opening.currency != current.currency:
                    warnings.append(
                        _warning(
                            "currency_mismatch",
                            "Opening and ending balances have different currencies.",
                        )
                    )
                    blocked = True
                else:
                    denominator = (opening.value + current.value) / Decimal(2)
                    inputs = (*inputs, opening)

    currencies = {item.currency for item in inputs}
    if len(currencies) > 1:
        warnings.append(
            _warning("currency_mismatch", "Ratio inputs use different currencies.")
        )
        blocked = True
    if numerator is None or denominator is None or blocked:
        return _result(
            formula,
            status="unavailable",
            value=None,
            numerator=numerator,
            denominator=denominator,
            period=period,
            calculated_at=calculated_at,
            inputs=inputs,
            warnings=tuple(warnings),
        )
    if denominator == 0:
        warnings.append(
            _warning(
                "zero_denominator", "The denominator is zero; no ratio was calculated."
            )
        )
        return _result(
            formula,
            status="unavailable",
            value=None,
            numerator=numerator,
            denominator=denominator,
            period=period,
            calculated_at=calculated_at,
            inputs=inputs,
            warnings=tuple(warnings),
        )
    if denominator < 0:
        warnings.append(
            _warning(
                "negative_denominator", "A negative denominator needs interpretation."
            )
        )
    value = numerator / denominator
    if formula.output_unit == "percent":
        value *= Decimal(100)
    return _result(
        formula,
        status="calculated",
        value=value,
        numerator=numerator,
        denominator=denominator,
        period=period,
        calculated_at=calculated_at,
        inputs=inputs,
        warnings=tuple(warnings),
    )


def _check_snapshots(
    income: StatementSnapshot | None,
    ending_balance: StatementSnapshot | None,
    opening_balance: StatementSnapshot | None,
) -> None:
    if income and income.statement_type != "income_statement":
        raise ValueError("Income snapshot must be an income statement")
    for snapshot in (ending_balance, opening_balance):
        if snapshot and snapshot.statement_type != "balance_sheet":
            raise ValueError("Balance snapshots must be balance sheets")
    snapshots = tuple(
        snapshot for snapshot in (income, ending_balance, opening_balance) if snapshot
    )
    if len({snapshot.company_id for snapshot in snapshots}) > 1:
        raise ValueError("Ratio inputs must belong to one company")
    if opening_balance and (income is None or ending_balance is None):
        raise ValueError("An opening balance requires income and ending balances")
    if income and ending_balance:
        if (
            income.period.period_end
            and ending_balance.period.period_end
            and income.period.period_end != ending_balance.period.period_end
        ):
            raise ValueError("Ending balance date must match income period end")
    if income and opening_balance:
        if (
            income.period.period_start
            and opening_balance.period.period_end
            and opening_balance.period.period_end
            != income.period.period_start - timedelta(days=1)
        ):
            raise ValueError("Opening balance date must precede income period start")


def calculate_ratios(
    *,
    income_statement: StatementSnapshot | None = None,
    ending_balance_sheet: StatementSnapshot | None = None,
    opening_balance_sheet: StatementSnapshot | None = None,
    calculated_at: datetime,
) -> tuple[MetricResult, ...]:
    """Calculate all registered ratios without modifying statement snapshots.

    The caller supplies a timezone-aware clock value, making repeated calculations
    with identical inputs reproducible. Values remain unrounded Decimals.
    """
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise ValueError("Calculation timestamp must include a timezone")
    _check_snapshots(income_statement, ending_balance_sheet, opening_balance_sheet)
    timestamp = calculated_at.astimezone(UTC)
    numbers = [
        item.normalized_value
        for snapshot in (income_statement, ending_balance_sheet, opening_balance_sheet)
        if snapshot
        for item in snapshot.values
        if item.normalized_value is not None
    ]
    integer_digits = max(
        (
            max(len(value.as_tuple().digits) + value.as_tuple().exponent, 0)
            for value in numbers
        ),
        default=1,
    )
    fractional_digits = max(
        (max(-value.as_tuple().exponent, 0) for value in numbers), default=0
    )
    with localcontext() as context:
        context.prec = max(50, integer_digits + fractional_digits + 20)
        return tuple(
            _calculate_one(
                formula,
                income_statement,
                ending_balance_sheet,
                opening_balance_sheet,
                timestamp,
            )
            for formula in FORMULAS.values()
        )
