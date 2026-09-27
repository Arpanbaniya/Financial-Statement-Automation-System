"""Source-linked, already-calculated facts shared by both explanation providers."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from finance.cash_flow import CashFlowResult
from finance.horizontal import HorizontalResult
from finance.ratios import MetricResult
from finance.working_capital import WorkingCapitalResult
from validation.types import SourceRef, ValidationResult

Focus = Literal[
    "overview",
    "profitability",
    "liquidity",
    "leverage",
    "efficiency",
    "working_capital",
    "cash_flow",
    "validation",
]

_GROUPS: dict[Focus, set[str]] = {
    "overview": {
        "revenue_growth",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "current_ratio",
        "debt_to_equity",
        "return_on_assets",
        "return_on_equity",
        "operating_cash_flow",
        "free_cash_flow",
    },
    "profitability": {
        "gross_margin",
        "operating_margin",
        "net_margin",
        "return_on_assets",
        "return_on_equity",
        "revenue_growth",
    },
    "liquidity": {"current_ratio", "quick_ratio"},
    "leverage": {"debt_to_equity", "interest_coverage"},
    "efficiency": {"asset_turnover", "receivables_turnover", "inventory_turnover"},
    "working_capital": {
        "net_working_capital",
        "dso",
        "dio",
        "dpo",
        "cash_conversion_cycle",
    },
    "cash_flow": {
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "capital_expenditure_outflow",
        "free_cash_flow",
        "cash_conversion_gap",
        "cash_conversion_ratio",
        "operating_cash_flow_growth",
    },
    "validation": set(),
}


@dataclass(frozen=True, slots=True)
class AiFact:
    id: str
    kind: Literal["metric", "warning"]
    label: str
    value: Decimal | None
    unit: str | None
    period_end: date | None
    source_refs: tuple[SourceRef, ...]
    currency: str | None = None


def _metric_fact(
    item: MetricResult | WorkingCapitalResult | CashFlowResult,
) -> AiFact | None:
    if (
        item.status != "calculated"
        or item.value is None
        or not any(ref.line_item_id for ref in item.source_refs)
        or item.period is None
        or item.period.period_end is None
    ):
        return None
    currencies = {source.currency for source in item.inputs}
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    return AiFact(
        id=f"metric_{item.metric_name}_{item.period.period_end.isoformat()}",
        kind="metric",
        label=item.metric_name.replace("_", " "),
        value=item.value,
        unit=item.unit,
        period_end=item.period.period_end,
        source_refs=item.source_refs,
        currency=currency,
    )


def build_facts(
    focus: Focus,
    *,
    ratios: tuple[MetricResult, ...] = (),
    previous_ratios: tuple[MetricResult, ...] = (),
    working: tuple[WorkingCapitalResult, ...] = (),
    cash: tuple[CashFlowResult, ...] = (),
    growth: tuple[HorizontalResult, ...] = (),
    checks: tuple[ValidationResult, ...] = (),
) -> tuple[AiFact, ...]:
    """Select calculated results with traceable accepted source lines."""
    facts: list[AiFact] = []
    if focus == "validation":
        for index, check in enumerate(checks):
            if check.status not in {"warning", "fail"} or not any(
                ref.line_item_id for ref in check.source_refs
            ):
                continue
            facts.append(
                AiFact(
                    id=f"warning_{index}",
                    kind="warning",
                    label=f"{check.check_name.replace('_', ' ')}: {check.status}",
                    value=None,
                    unit=None,
                    period_end=None,
                    source_refs=check.source_refs,
                )
            )
    else:
        for item in (*ratios, *working, *cash, *previous_ratios):
            if item.metric_name in _GROUPS[focus]:
                fact = _metric_fact(item)
                if fact:
                    facts.append(fact)
        for item in growth:
            if (
                item.metric_name not in _GROUPS[focus]
                or item.status != "calculated"
                or item.percentage_change is None
                or not any(ref.line_item_id for ref in item.source_refs)
                or item.current_period.period_end is None
            ):
                continue
            facts.append(
                AiFact(
                    id=f"metric_{item.metric_name}_{item.current_period.period_end.isoformat()}",
                    kind="metric",
                    label=item.metric_name.replace("_", " "),
                    value=item.percentage_change,
                    unit="percent",
                    period_end=item.current_period.period_end,
                    source_refs=item.source_refs,
                )
            )
    return tuple(dict.fromkeys(facts))[:20]
