"""Express accepted statement lines as a percentage of one source base."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Literal

from finance.ratio_registry import RatioInput
from finance.ratios import MetricInput, MetricWarning, _select
from normalization.periods import NormalizedPeriod
from validation.types import SourceRef, StatementSnapshot

CommonSizeStatus = Literal["calculated", "unavailable"]


@dataclass(frozen=True, slots=True)
class CommonSizeResult:
    field: str
    status: CommonSizeStatus
    formula_id: str
    amount: Decimal | None
    base_field: str
    base_amount: Decimal | None
    percentage: Decimal | None
    period: NormalizedPeriod
    unit: Literal["percent"]
    calculated_at: datetime
    inputs: tuple[MetricInput, ...]
    source_refs: tuple[SourceRef, ...]
    warnings: tuple[MetricWarning, ...]


def calculate_common_size(
    statement: StatementSnapshot, *, calculated_at: datetime
) -> tuple[CommonSizeResult, ...]:
    """Use revenue for income lines or total assets for balance-sheet lines."""
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise ValueError("Calculation timestamp must include a timezone")
    if statement.statement_type == "income_statement":
        role, base_field, formula_id = "income", "revenue", "income_common_size_v1"
    elif statement.statement_type == "balance_sheet":
        role, base_field, formula_id = (
            "ending_balance",
            "total_assets",
            "balance_common_size_v1",
        )
    else:
        raise ValueError("Common-size analysis needs an income or balance sheet")
    fields = tuple(dict.fromkeys(value.field for value in statement.values))
    if not fields:
        fields = (base_field,)
    base, base_warning = _select(statement, RatioInput(role, base_field))
    numbers = [
        value.normalized_value
        for value in statement.values
        if value.normalized_value is not None
    ]
    integer_digits = max(
        (max(len(n.as_tuple().digits) + n.as_tuple().exponent, 0) for n in numbers),
        default=1,
    )
    fractional_digits = max(
        (max(-n.as_tuple().exponent, 0) for n in numbers), default=0
    )
    results: list[CommonSizeResult] = []
    with localcontext() as context:
        context.prec = max(50, integer_digits + fractional_digits + 20)
        for field in fields:
            item, item_warning = _select(statement, RatioInput(role, field))
            inputs = tuple(dict.fromkeys(value for value in (item, base) if value))
            warnings = tuple(
                dict.fromkeys(
                    warning for warning in (item_warning, base_warning) if warning
                )
            )
            amount = item.value if item else None
            base_amount = base.value if base else None
            percentage = None
            if item and base:
                if item.currency != base.currency:
                    warnings += (
                        MetricWarning(
                            "currency_mismatch", "Line and base currencies differ."
                        ),
                    )
                elif base.value <= 0:
                    warnings += (
                        MetricWarning(
                            "nonpositive_base",
                            "Revenue or total assets must be positive.",
                        ),
                    )
                else:
                    percentage = item.value / base.value * Decimal(100)
            results.append(
                CommonSizeResult(
                    field=field,
                    status="calculated" if percentage is not None else "unavailable",
                    formula_id=formula_id,
                    amount=amount,
                    base_field=base_field,
                    base_amount=base_amount,
                    percentage=percentage,
                    period=statement.period,
                    unit="percent",
                    calculated_at=calculated_at.astimezone(UTC),
                    inputs=inputs,
                    source_refs=tuple(
                        dict.fromkeys(
                            ref for value in inputs for ref in value.source_refs
                        )
                    ),
                    warnings=warnings,
                )
            )
    return tuple(results)
