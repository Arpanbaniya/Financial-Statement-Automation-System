"""Factual, deterministic sentences from calculated financial measures."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from finance.cash_flow import CashFlowTrend
from finance.horizontal import HorizontalResult
from finance.ratios import MetricResult
from finance.working_capital import WorkingCapitalResult
from validation.types import SourceRef

CommentaryKind = Literal["observation", "question"]


@dataclass(frozen=True, slots=True)
class CommentaryFinding:
    kind: CommentaryKind
    text: str
    metric_names: tuple[str, ...]
    source_refs: tuple[SourceRef, ...]


def _number(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):,.1f}"


def _refs(*items: object) -> tuple[SourceRef, ...]:
    return tuple(dict.fromkeys(ref for item in items for ref in item.source_refs))


def generate_commentary(
    *,
    horizontal: tuple[HorizontalResult, ...] = (),
    current_ratios: tuple[MetricResult, ...] = (),
    previous_ratios: tuple[MetricResult, ...] = (),
    cash_flow_trends: tuple[CashFlowTrend, ...] = (),
    current_working_capital: tuple[WorkingCapitalResult, ...] = (),
    previous_working_capital: tuple[WorkingCapitalResult, ...] = (),
) -> tuple[CommentaryFinding, ...]:
    """State observed values and changes; never infer causes or advice."""
    findings: list[CommentaryFinding] = []
    for item in horizontal:
        if (
            item.metric_name == "revenue_growth"
            and item.status == "calculated"
            and item.percentage_change is not None
            and item.previous_value is not None
            and item.current_value is not None
            and item.source_refs
        ):
            verb = (
                "increased"
                if item.percentage_change > 0
                else "decreased"
                if item.percentage_change < 0
                else "was unchanged"
            )
            findings.append(
                CommentaryFinding(
                    "observation",
                    (
                        f"Revenue {verb} {_number(abs(item.percentage_change))}% "
                        f"from {_number(item.previous_value)} to "
                        f"{_number(item.current_value)} "
                        f"({item.comparison.replace('_', ' ')})."
                    ),
                    ("revenue_growth",),
                    item.source_refs,
                )
            )
    current_by_name = {item.metric_name: item for item in current_ratios}
    previous_by_name = {item.metric_name: item for item in previous_ratios}
    for name, label in (
        ("operating_margin", "Operating margin"),
        ("net_margin", "Net margin"),
    ):
        current = current_by_name.get(name)
        earlier = previous_by_name.get(name)
        if (
            not current
            or not earlier
            or current.status != "calculated"
            or earlier.status != "calculated"
        ):
            continue
        if (
            current.value is None
            or earlier.value is None
            or not _refs(current, earlier)
            or len(
                {
                    item.currency
                    for result in (current, earlier)
                    for item in result.inputs
                }
            )
            > 1
        ):
            continue
        if (
            current.period
            and earlier.period
            and (
                current.period.period_end is None
                or earlier.period.period_end is None
                or current.period.period_end <= earlier.period.period_end
            )
        ):
            continue
        verb = (
            "increased"
            if current.value > earlier.value
            else "decreased"
            if current.value < earlier.value
            else "was unchanged"
        )
        findings.append(
            CommentaryFinding(
                "observation",
                (
                    f"{label} {verb} from {_number(earlier.value)}% "
                    f"to {_number(current.value)}%."
                ),
                (name,),
                _refs(current, earlier),
            )
        )
    for trend in cash_flow_trends:
        if trend.metric_name not in {"operating_cash_flow", "free_cash_flow"}:
            continue
        if (
            trend.absolute_change is None
            or trend.current.value is None
            or trend.previous.value is None
        ):
            continue
        if not _refs(trend.current, trend.previous):
            continue
        label = (
            "Operating cash flow"
            if trend.metric_name == "operating_cash_flow"
            else "Free cash flow"
        )
        verb = (
            "increased"
            if trend.absolute_change > 0
            else "decreased"
            if trend.absolute_change < 0
            else "was unchanged"
        )
        findings.append(
            CommentaryFinding(
                "observation",
                (
                    f"{label} {verb} from {_number(trend.previous.value)} "
                    f"to {_number(trend.current.value)} "
                    f"(change {_number(trend.absolute_change)})."
                ),
                (trend.metric_name,),
                _refs(trend.current, trend.previous),
            )
        )
    earlier_wc = {item.metric_name: item for item in previous_working_capital}
    for current in current_working_capital:
        if current.metric_name not in {"dso", "dio", "dpo", "cash_conversion_cycle"}:
            continue
        earlier = earlier_wc.get(current.metric_name)
        if not earlier or current.value is None or earlier.value is None:
            continue
        if not _refs(current, earlier):
            continue
        if (
            len(
                {
                    item.currency
                    for result in (current, earlier)
                    for item in result.inputs
                }
            )
            > 1
        ):
            continue
        if (
            current.period
            and earlier.period
            and (
                current.period.period_end is None
                or earlier.period.period_end is None
                or current.period.period_end <= earlier.period.period_end
            )
        ):
            continue
        label = (
            current.metric_name.upper()
            if current.metric_name != "cash_conversion_cycle"
            else "Cash conversion cycle"
        )
        verb = (
            "increased"
            if current.value > earlier.value
            else "decreased"
            if current.value < earlier.value
            else "was unchanged"
        )
        findings.append(
            CommentaryFinding(
                "observation",
                (
                    f"{label} {verb} from {_number(earlier.value)} "
                    f"to {_number(current.value)} days."
                ),
                (current.metric_name,),
                _refs(current, earlier),
            )
        )
    return tuple(findings)
