"""Source-linked working capital and cash conversion cycle calculations."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Literal

from finance.ratio_registry import RatioInput
from finance.ratios import MetricInput, MetricWarning, _check_snapshots, _select
from normalization.periods import NormalizedPeriod
from validation.types import SourceRef, StatementSnapshot

WorkingCapitalUnit = Literal["currency", "days"]
WorkingCapitalStatus = Literal["calculated", "unavailable"]


@dataclass(frozen=True, slots=True)
class WorkingCapitalResult:
    metric_name: str
    status: WorkingCapitalStatus
    value: Decimal | None
    formula_id: str
    unit: WorkingCapitalUnit
    period: NormalizedPeriod | None
    days_in_period: int | None
    numerator: Decimal | None
    denominator: Decimal | None
    calculated_at: datetime
    inputs: tuple[MetricInput, ...]
    source_refs: tuple[SourceRef, ...]
    warnings: tuple[MetricWarning, ...]


def _warning(code: str, message: str) -> MetricWarning:
    return MetricWarning(code, message)


def _result(
    name: str,
    *,
    value: Decimal | None,
    unit: WorkingCapitalUnit,
    period: NormalizedPeriod | None,
    days: int | None,
    numerator: Decimal | None,
    denominator: Decimal | None,
    timestamp: datetime,
    inputs: tuple[MetricInput, ...],
    warnings: tuple[MetricWarning, ...],
) -> WorkingCapitalResult:
    return WorkingCapitalResult(
        metric_name=name,
        status="calculated" if value is not None else "unavailable",
        value=value,
        formula_id=f"{name}_v1",
        unit=unit,
        period=period,
        days_in_period=days,
        numerator=numerator,
        denominator=denominator,
        calculated_at=timestamp,
        inputs=inputs,
        source_refs=tuple(
            dict.fromkeys(ref for item in inputs for ref in item.source_refs)
        ),
        warnings=warnings,
    )


def _net_working_capital(
    ending: StatementSnapshot | None, timestamp: datetime
) -> WorkingCapitalResult:
    assets, assets_warning = _select(
        ending, RatioInput("ending_balance", "total_current_assets")
    )
    liabilities, liabilities_warning = _select(
        ending, RatioInput("ending_balance", "total_current_liabilities")
    )
    inputs = tuple(item for item in (assets, liabilities) if item is not None)
    warnings = [item for item in (assets_warning, liabilities_warning) if item]
    value = None
    if assets and liabilities:
        if assets.currency != liabilities.currency:
            warnings.append(
                _warning(
                    "currency_mismatch",
                    "Current assets and liabilities use different currencies.",
                )
            )
        else:
            value = assets.value - liabilities.value
    return _result(
        "net_working_capital",
        value=value,
        unit="currency",
        period=ending.period if ending else None,
        days=None,
        numerator=assets.value if assets else None,
        denominator=liabilities.value if liabilities else None,
        timestamp=timestamp,
        inputs=inputs,
        warnings=tuple(warnings),
    )


def _days_metric(
    name: Literal["dso", "dio", "dpo"],
    balance_field: str,
    flow_field: str,
    income: StatementSnapshot | None,
    ending: StatementSnapshot | None,
    opening: StatementSnapshot | None,
    timestamp: datetime,
) -> WorkingCapitalResult:
    period = income.period if income else None
    days = None
    warnings: list[MetricWarning] = []
    if (
        period
        and period.status == "normalized"
        and period.period_start
        and period.period_end
    ):
        days = (period.period_end - period.period_start).days + 1
    else:
        warnings.append(
            _warning("unresolved_period", "Income period dates need review.")
        )

    end, end_warning = _select(ending, RatioInput("ending_balance", balance_field))
    flow, flow_warning = _select(income, RatioInput("income", flow_field))
    warnings.extend(item for item in (end_warning, flow_warning) if item)
    inputs = tuple(item for item in (end, flow) if item is not None)
    average = end.value if end else None
    blocked = False
    if end:
        if opening is None:
            warnings.append(
                _warning(
                    "ending_balance_only",
                    "Opening balance is unavailable; ending balance was used.",
                )
            )
        else:
            start, start_warning = _select(
                opening, RatioInput("opening_balance", balance_field)
            )
            if start:
                inputs = (*inputs, start)
                if start.currency != end.currency:
                    warnings.append(
                        _warning(
                            "currency_mismatch",
                            "Opening and ending balances use different currencies.",
                        )
                    )
                    blocked = True
                else:
                    average = (start.value + end.value) / Decimal(2)
            elif start_warning and start_warning.code == "missing_input":
                warnings.append(
                    _warning(
                        "ending_balance_only",
                        "Opening line item is missing; ending balance was used.",
                    )
                )
            else:
                if start_warning:
                    warnings.append(start_warning)
                blocked = True

    if len({item.currency for item in inputs}) > 1:
        warnings.append(
            _warning("currency_mismatch", "Metric inputs use different currencies.")
        )
        blocked = True
    if average is not None and average < 0:
        warnings.append(
            _warning("negative_balance", "A negative average balance needs review.")
        )
        blocked = True
    denominator = flow.value if flow else None
    if denominator is not None and denominator <= 0:
        warnings.append(
            _warning(
                "nonpositive_denominator",
                "Revenue or cost of revenue must be positive.",
            )
        )
        blocked = True
    value = (
        average / denominator * Decimal(days)
        if not blocked and average is not None and denominator is not None and days
        else None
    )
    return _result(
        name,
        value=value,
        unit="days",
        period=period,
        days=days,
        numerator=average,
        denominator=denominator,
        timestamp=timestamp,
        inputs=inputs,
        warnings=tuple(warnings),
    )


def _cash_conversion_cycle(
    components: tuple[WorkingCapitalResult, ...], timestamp: datetime
) -> WorkingCapitalResult:
    dso, dio, dpo = components
    inputs = tuple(dict.fromkeys(item for part in components for item in part.inputs))
    warnings = tuple(
        dict.fromkeys(item for part in components for item in part.warnings)
    )
    value = None
    if all(part.value is not None for part in components):
        assert dso.value is not None and dio.value is not None and dpo.value is not None
        value = dso.value + dio.value - dpo.value
    else:
        warnings = (
            *warnings,
            _warning(
                "missing_component",
                "DSO, DIO, and DPO are all required for the cash conversion cycle.",
            ),
        )
    return _result(
        "cash_conversion_cycle",
        value=value,
        unit="days",
        period=dso.period,
        days=dso.days_in_period,
        numerator=None,
        denominator=None,
        timestamp=timestamp,
        inputs=inputs,
        warnings=warnings,
    )


def calculate_working_capital(
    *,
    income_statement: StatementSnapshot | None = None,
    ending_balance_sheet: StatementSnapshot | None = None,
    opening_balance_sheet: StatementSnapshot | None = None,
    calculated_at: datetime,
) -> tuple[WorkingCapitalResult, ...]:
    """Return net working capital, DSO, DIO, DPO, and CCC in that order.

    DPO uses cost of revenue as a proxy for purchases. Day counts use the
    inclusive income period; no calendar-year day count is assumed.
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
        nwc = _net_working_capital(ending_balance_sheet, timestamp)
        components = (
            _days_metric(
                "dso",
                "accounts_receivable",
                "revenue",
                income_statement,
                ending_balance_sheet,
                opening_balance_sheet,
                timestamp,
            ),
            _days_metric(
                "dio",
                "inventory",
                "cost_of_revenue",
                income_statement,
                ending_balance_sheet,
                opening_balance_sheet,
                timestamp,
            ),
            _days_metric(
                "dpo",
                "accounts_payable",
                "cost_of_revenue",
                income_statement,
                ending_balance_sheet,
                opening_balance_sheet,
                timestamp,
            ),
        )
        return (nwc, *components, _cash_conversion_cycle(components, timestamp))
