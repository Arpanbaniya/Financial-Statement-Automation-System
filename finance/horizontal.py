"""Source-linked year-over-year and sequential changes across statements."""

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from types import MappingProxyType
from typing import Literal

from finance.ratio_registry import RatioInput
from finance.ratios import MetricInput, MetricWarning, _select
from normalization.periods import NormalizedPeriod
from normalization.taxonomy import StatementType
from validation.types import SourceRef, StatementSnapshot

ComparisonMode = Literal["year_over_year", "sequential"]
GrowthStatus = Literal["calculated", "unavailable"]


@dataclass(frozen=True, slots=True)
class GrowthDefinition:
    name: str
    formula_id: str
    statement_type: StatementType
    fields: tuple[str, ...]
    explanation: str


_DEFINITIONS = (
    GrowthDefinition(
        "revenue_growth",
        "revenue_growth_v1",
        "income_statement",
        ("revenue",),
        "Change in revenue.",
    ),
    GrowthDefinition(
        "gross_profit_growth",
        "gross_profit_growth_v1",
        "income_statement",
        ("gross_profit",),
        "Change in gross profit.",
    ),
    GrowthDefinition(
        "operating_income_growth",
        "operating_income_growth_v1",
        "income_statement",
        ("operating_income",),
        "Change in operating income.",
    ),
    GrowthDefinition(
        "net_income_growth",
        "net_income_growth_v1",
        "income_statement",
        ("net_income",),
        "Change in net income.",
    ),
    GrowthDefinition(
        "assets_growth",
        "assets_growth_v1",
        "balance_sheet",
        ("total_assets",),
        "Change in total assets.",
    ),
    GrowthDefinition(
        "debt_growth",
        "interest_bearing_debt_growth_v1",
        "balance_sheet",
        ("short_term_debt", "long_term_debt"),
        "Change in interest-bearing short- and long-term debt.",
    ),
    GrowthDefinition(
        "equity_growth",
        "equity_growth_v1",
        "balance_sheet",
        ("shareholders_equity",),
        "Change in shareholders' equity.",
    ),
    GrowthDefinition(
        "operating_cash_flow_growth",
        "operating_cash_flow_growth_v1",
        "cash_flow_statement",
        ("operating_cash_flow",),
        "Change in operating cash flow.",
    ),
    GrowthDefinition(
        "free_cash_flow_growth",
        "signed_capex_fcf_growth_v1",
        "cash_flow_statement",
        ("operating_cash_flow", "capital_expenditure"),
        "Change in operating cash flow plus signed capital expenditure.",
    ),
)
GROWTH_DEFINITIONS = MappingProxyType({item.name: item for item in _DEFINITIONS})


@dataclass(frozen=True, slots=True)
class HorizontalResult:
    metric_name: str
    status: GrowthStatus
    formula_id: str
    comparison: ComparisonMode
    current_period: NormalizedPeriod
    previous_period: NormalizedPeriod | None
    current_value: Decimal | None
    previous_value: Decimal | None
    absolute_change: Decimal | None
    percentage_change: Decimal | None
    unit: Literal["percent"]
    calculated_at: datetime
    inputs: tuple[MetricInput, ...]
    source_refs: tuple[SourceRef, ...]
    warnings: tuple[MetricWarning, ...]


def _one_year_earlier(day: date) -> date:
    year = day.year - 1
    target_last = calendar.monthrange(year, day.month)[1]
    if day.day == calendar.monthrange(day.year, day.month)[1]:
        return date(year, day.month, target_last)
    return date(year, day.month, min(day.day, target_last))


def _period_key(snapshot: StatementSnapshot) -> tuple | None:
    period = snapshot.period
    if period.status != "normalized" or period.period_end is None:
        return None
    if period.period_type != "instant" and period.period_start is None:
        return None
    return (
        snapshot.company_id,
        snapshot.statement_type,
        period.period_type,
        period.period_start,
        period.period_end,
    )


def _previous(
    current: StatementSnapshot,
    snapshots: tuple[StatementSnapshot, ...],
    mode: ComparisonMode,
) -> tuple[StatementSnapshot | None, MetricWarning | None]:
    period = current.period
    if _period_key(current) is None:
        return None, MetricWarning(
            "unresolved_period", "Current reporting period needs review."
        )
    peers = tuple(
        candidate
        for candidate in snapshots
        if candidate.id != current.id
        and candidate.company_id == current.company_id
        and candidate.statement_type == current.statement_type
        and candidate.period.period_type == period.period_type
        and _period_key(candidate) is not None
    )
    if mode == "year_over_year":
        earlier_end = _one_year_earlier(period.period_end)
        earlier_start = (
            _one_year_earlier(period.period_start) if period.period_start else None
        )
        matches = tuple(
            candidate
            for candidate in peers
            if candidate.period.period_end == earlier_end
            and candidate.period.period_start == earlier_start
        )
    elif period.period_type == "instant":
        candidates = tuple(
            candidate
            for candidate in peers
            if candidate.period.period_end < period.period_end
        )
        latest = max((item.period.period_end for item in candidates), default=None)
        matches = tuple(item for item in candidates if item.period.period_end == latest)
    else:
        matches = tuple(
            candidate
            for candidate in peers
            if candidate.period.period_end + timedelta(days=1) == period.period_start
            and (
                period.period_type != "other_duration"
                or (candidate.period.period_end - candidate.period.period_start)
                == (period.period_end - period.period_start)
            )
        )
    if not matches:
        return None, MetricWarning(
            "missing_comparable_period",
            "No matching earlier reporting period was supplied.",
        )
    if len(matches) > 1:
        return None, MetricWarning(
            "duplicate_period",
            "Several earlier statements match; choose an accepted version.",
        )
    if (
        mode == "sequential"
        and period.period_type == "instant"
        and (period.period_end - matches[0].period.period_end).days > 366
    ):
        return matches[0], MetricWarning(
            "long_balance_gap",
            "The nearest earlier balance sheet is more than a year old.",
        )
    return matches[0], None


def _amount(
    snapshot: StatementSnapshot | None, definition: GrowthDefinition
) -> tuple[Decimal | None, tuple[MetricInput, ...], tuple[MetricWarning, ...]]:
    if snapshot is None:
        return None, (), ()
    role = {
        "income_statement": "income",
        "balance_sheet": "ending_balance",
        "cash_flow_statement": "cash_flow",
    }[definition.statement_type]
    inputs: list[MetricInput] = []
    warnings: list[MetricWarning] = []
    for field in definition.fields:
        item, warning = _select(snapshot, RatioInput(role, field))
        if item:
            inputs.append(item)
        if warning:
            warnings.append(warning)
    if len(inputs) != len(definition.fields):
        return None, tuple(inputs), tuple(warnings)
    if len({item.currency for item in inputs}) != 1:
        warnings.append(
            MetricWarning("currency_mismatch", "Inputs use different currencies.")
        )
        return None, tuple(inputs), tuple(warnings)
    if definition.name == "free_cash_flow_growth" and inputs[1].value > 0:
        warnings.append(
            MetricWarning(
                "positive_capex",
                "Capital expenditure is positive; check its signed convention.",
            )
        )
        return None, tuple(inputs), tuple(warnings)
    return (
        sum((item.value for item in inputs), Decimal(0)),
        tuple(inputs),
        tuple(warnings),
    )


def _result(
    definition: GrowthDefinition,
    current: StatementSnapshot,
    previous: StatementSnapshot | None,
    mode: ComparisonMode,
    timestamp: datetime,
    extra_warning: MetricWarning | None,
) -> HorizontalResult:
    current_value, current_inputs, current_warnings = _amount(current, definition)
    previous_value, previous_inputs, previous_warnings = _amount(previous, definition)
    inputs = (*current_inputs, *previous_inputs)
    warnings = [*current_warnings, *previous_warnings]
    if extra_warning:
        warnings.append(extra_warning)
    currencies = {item.currency for item in inputs}
    blocked = len(currencies) > 1
    if blocked:
        warnings.append(
            MetricWarning("currency_mismatch", "Periods use different currencies.")
        )
    change = (
        current_value - previous_value
        if current_value is not None and previous_value is not None and not blocked
        else None
    )
    percentage = None
    if change is not None:
        if previous_value == 0:
            warnings.append(
                MetricWarning(
                    "zero_baseline", "Percentage growth is undefined from zero."
                )
            )
        elif previous_value < 0:
            warnings.append(
                MetricWarning(
                    "negative_baseline",
                    "Percentage growth from a negative prior value is misleading.",
                )
            )
        else:
            percentage = change / previous_value * Decimal(100)
            if current_value < 0:
                warnings.append(
                    MetricWarning(
                        "sign_change", "The value changed from positive to negative."
                    )
                )
    return HorizontalResult(
        metric_name=definition.name,
        status="calculated" if percentage is not None else "unavailable",
        formula_id=definition.formula_id,
        comparison=mode,
        current_period=current.period,
        previous_period=previous.period if previous else None,
        current_value=current_value,
        previous_value=previous_value,
        absolute_change=change,
        percentage_change=percentage,
        unit="percent",
        calculated_at=timestamp,
        inputs=inputs,
        source_refs=tuple(
            dict.fromkeys(ref for item in inputs for ref in item.source_refs)
        ),
        warnings=tuple(warnings),
    )


def calculate_horizontal(
    statements: tuple[StatementSnapshot, ...] | list[StatementSnapshot],
    *,
    calculated_at: datetime,
    comparison: ComparisonMode = "year_over_year",
) -> tuple[HorizontalResult, ...]:
    """Compare compatible periods; never guess a previous version or base."""
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise ValueError("Calculation timestamp must include a timezone")
    if comparison not in {"year_over_year", "sequential"}:
        raise ValueError("Unknown comparison mode")
    snapshots = tuple(statements)
    if len({item.id for item in snapshots}) != len(snapshots):
        raise ValueError("Statement IDs must be unique")
    ordered = tuple(
        sorted(
            snapshots,
            key=lambda item: (
                item.company_id,
                item.statement_type,
                item.period.period_end or date.min,
                item.id,
            ),
        )
    )
    counts: dict[tuple, int] = {}
    for item in ordered:
        key = _period_key(item)
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
    numbers = [
        value.normalized_value
        for item in ordered
        for value in item.values
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
        results: list[HorizontalResult] = []
        for item in ordered:
            key = _period_key(item)
            previous, warning = _previous(item, ordered, comparison)
            if key is not None and counts[key] > 1:
                previous = None
                warning = MetricWarning(
                    "duplicate_period",
                    "Several current statements match; choose an accepted version.",
                )
            for definition in GROWTH_DEFINITIONS.values():
                if definition.statement_type == item.statement_type:
                    results.append(
                        _result(
                            definition,
                            item,
                            previous,
                            comparison,
                            calculated_at.astimezone(UTC),
                            warning,
                        )
                    )
    return tuple(results)
