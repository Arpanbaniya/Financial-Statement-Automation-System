"""Conservative cash flow analysis from accepted signed statement amounts."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Literal

from finance.ratio_registry import RatioInput
from finance.ratios import MetricInput, MetricWarning, _select
from normalization.periods import NormalizedPeriod
from validation.types import SourceRef, StatementSnapshot

CashFlowStatus = Literal["calculated", "unavailable"]
CashFlowUnit = Literal["currency", "times"]


@dataclass(frozen=True, slots=True)
class CashFlowResult:
    metric_name: str
    company_id: str | None
    status: CashFlowStatus
    value: Decimal | None
    formula_id: str
    unit: CashFlowUnit
    period: NormalizedPeriod | None
    calculated_at: datetime
    inputs: tuple[MetricInput, ...]
    source_refs: tuple[SourceRef, ...]
    warnings: tuple[MetricWarning, ...]


@dataclass(frozen=True, slots=True)
class CashFlowTrend:
    metric_name: str
    current: CashFlowResult
    previous: CashFlowResult
    absolute_change: Decimal | None
    percentage_change: Decimal | None
    warnings: tuple[MetricWarning, ...]


def _result(
    name: str,
    company_id: str | None,
    value: Decimal | None,
    unit: CashFlowUnit,
    period: NormalizedPeriod | None,
    timestamp: datetime,
    inputs: tuple[MetricInput, ...],
    warnings: tuple[MetricWarning, ...] = (),
) -> CashFlowResult:
    return CashFlowResult(
        metric_name=name,
        company_id=company_id,
        status="calculated" if value is not None else "unavailable",
        value=value,
        formula_id=f"{name}_v1",
        unit=unit,
        period=period,
        calculated_at=timestamp,
        inputs=inputs,
        source_refs=tuple(
            dict.fromkeys(ref for item in inputs for ref in item.source_refs)
        ),
        warnings=warnings,
    )


def calculate_cash_flow(
    *,
    cash_flow_statement: StatementSnapshot | None,
    income_statement: StatementSnapshot | None = None,
    calculated_at: datetime,
) -> tuple[CashFlowResult, ...]:
    """Calculate reported cash flows, signed CapEx, FCF, and profit conversion.

    Capital expenditure is an accepted negative cash outflow. A positive
    source value needs review and cannot produce free cash flow.
    """
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise ValueError("Calculation timestamp must include a timezone")
    if (
        cash_flow_statement
        and cash_flow_statement.statement_type != "cash_flow_statement"
    ):
        raise ValueError("Cash flow snapshot must be a cash flow statement")
    if income_statement and income_statement.statement_type != "income_statement":
        raise ValueError("Income snapshot must be an income statement")
    if cash_flow_statement and income_statement:
        if cash_flow_statement.company_id != income_statement.company_id:
            raise ValueError("Statements must belong to one company")
        a, b = cash_flow_statement.period, income_statement.period
        if a.period_start and b.period_start and a.period_start != b.period_start:
            raise ValueError("Income and cash flow periods must match")
        if a.period_end and b.period_end and a.period_end != b.period_end:
            raise ValueError("Income and cash flow periods must match")
    period = cash_flow_statement.period if cash_flow_statement else None
    company_id = cash_flow_statement.company_id if cash_flow_statement else None
    timestamp = calculated_at.astimezone(UTC)
    numbers = [
        value.normalized_value
        for snapshot in (cash_flow_statement, income_statement)
        if snapshot
        for value in snapshot.values
        if value.normalized_value is not None
    ]
    integer_digits = max(
        (max(len(n.as_tuple().digits) + n.as_tuple().exponent, 0) for n in numbers),
        default=1,
    )
    fractional_digits = max(
        (max(-n.as_tuple().exponent, 0) for n in numbers), default=0
    )
    with localcontext() as context:
        context.prec = max(50, integer_digits + fractional_digits + 20)
        selected: dict[str, MetricInput | None] = {}
        warnings: dict[str, tuple[MetricWarning, ...]] = {}
        for field in (
            "operating_cash_flow",
            "investing_cash_flow",
            "financing_cash_flow",
            "capital_expenditure",
        ):
            selected[field], warning = _select(
                cash_flow_statement, RatioInput("cash_flow", field)
            )
            warnings[field] = (warning,) if warning else ()
        cfo = selected["operating_cash_flow"]
        capex = selected["capital_expenditure"]
        results = []
        for name in (
            "operating_cash_flow",
            "investing_cash_flow",
            "financing_cash_flow",
        ):
            source = selected[name]
            results.append(
                _result(
                    name,
                    company_id,
                    source.value if source else None,
                    "currency",
                    period,
                    timestamp,
                    (source,) if source else (),
                    warnings[name],
                )
            )
        capex_warnings = list(warnings["capital_expenditure"])
        if capex and capex.value > 0:
            capex_warnings.append(
                MetricWarning(
                    "positive_capex",
                    "Positive capital expenditure needs sign review.",
                )
            )
        valid_capex = capex is not None and capex.value <= 0
        results.append(
            _result(
                "capital_expenditure_outflow",
                company_id,
                -capex.value if valid_capex and capex else None,
                "currency",
                period,
                timestamp,
                (capex,) if capex else (),
                tuple(capex_warnings),
            )
        )
        fcf_inputs = tuple(item for item in (cfo, capex) if item)
        fcf_warnings = (*warnings["operating_cash_flow"], *capex_warnings)
        if len({item.currency for item in fcf_inputs}) > 1:
            fcf_warnings = (
                *fcf_warnings,
                MetricWarning(
                    "currency_mismatch", "Cash flow inputs use different currencies."
                ),
            )
        fcf = (
            cfo.value + capex.value
            if cfo
            and capex
            and valid_capex
            and len({item.currency for item in fcf_inputs}) == 1
            else None
        )
        results.append(
            _result(
                "free_cash_flow",
                company_id,
                fcf,
                "currency",
                period,
                timestamp,
                fcf_inputs,
                fcf_warnings,
            )
        )
        profit_snapshot = income_statement or cash_flow_statement
        profit_role = "income" if income_statement else "cash_flow"
        profit, profit_warning = _select(
            profit_snapshot, RatioInput(profit_role, "net_income")
        )
        conversion_inputs = tuple(item for item in (cfo, profit) if item)
        conversion_warnings = [*warnings["operating_cash_flow"]]
        if profit_warning:
            conversion_warnings.append(profit_warning)
        blocked = len({item.currency for item in conversion_inputs}) > 1
        if blocked:
            conversion_warnings.append(
                MetricWarning(
                    "currency_mismatch", "Net income and CFO use different currencies."
                )
            )
        gap = cfo.value - profit.value if cfo and profit and not blocked else None
        results.append(
            _result(
                "cash_conversion_gap",
                company_id,
                gap,
                "currency",
                period,
                timestamp,
                conversion_inputs,
                tuple(conversion_warnings),
            )
        )
        ratio = None
        if cfo and profit and not blocked:
            if profit.value > 0:
                ratio = cfo.value / profit.value
            else:
                conversion_warnings.append(
                    MetricWarning(
                        "nonpositive_net_income",
                        "CFO-to-net-income ratio needs positive net income.",
                    )
                )
        results.append(
            _result(
                "cash_conversion_ratio",
                company_id,
                ratio,
                "times",
                period,
                timestamp,
                conversion_inputs,
                tuple(conversion_warnings),
            )
        )
    return tuple(results)


def compare_cash_flow(
    current: tuple[CashFlowResult, ...],
    previous: tuple[CashFlowResult, ...],
) -> tuple[CashFlowTrend, ...]:
    """Compare two explicitly selected, comparable nonoverlapping periods."""
    if not current or not previous:
        raise ValueError("Cash flow result sets cannot be empty")
    if {item.metric_name for item in current} != {
        item.metric_name for item in previous
    }:
        raise ValueError("Cash flow result sets must contain the same metrics")
    if len({item.metric_name for item in current}) != len(current) or len(
        {item.metric_name for item in previous}
    ) != len(previous):
        raise ValueError("Cash flow result sets cannot contain duplicate metrics")
    if current[0].company_id != previous[0].company_id:
        raise ValueError("Cash flow trends must belong to one company")
    current_by_name = {item.metric_name: item for item in current}
    previous_by_name = {item.metric_name: item for item in previous}
    current_period = current[0].period
    previous_period = previous[0].period
    if (
        not current_period
        or not previous_period
        or (
            current_period.status != "normalized"
            or previous_period.status != "normalized"
            or current_period.period_start is None
            or previous_period.period_start is None
            or current_period.period_end is None
            or previous_period.period_end is None
            or current_period.period_type != previous_period.period_type
            or (
                current_period.period_type == "other_duration"
                and (current_period.period_end - current_period.period_start)
                != (previous_period.period_end - previous_period.period_start)
            )
            or previous_period.period_end >= current_period.period_start
        )
    ):
        raise ValueError("Cash flow trends need comparable, nonoverlapping periods")
    trends = []
    for name, item in current_by_name.items():
        earlier = previous_by_name[name]
        warnings = []
        currencies = {
            source.currency for result in (item, earlier) for source in result.inputs
        }
        if len(currencies) > 1:
            warnings.append(
                MetricWarning("currency_mismatch", "Periods use different currencies.")
            )
        change = (
            item.value - earlier.value
            if item.value is not None and earlier.value is not None and not warnings
            else None
        )
        percentage = None
        if change is not None:
            if earlier.value > 0:
                percentage = change / earlier.value * Decimal(100)
            else:
                warnings.append(
                    MetricWarning(
                        "nonpositive_baseline",
                        "Percentage change needs a positive prior value.",
                    )
                )
        trends.append(
            CashFlowTrend(name, item, earlier, change, percentage, tuple(warnings))
        )
    return tuple(trends)
