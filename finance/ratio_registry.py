"""Versioned ratio definitions shared by calculation and documentation."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

RatioUnit = Literal["percent", "times"]
StatementRole = Literal["income", "ending_balance", "opening_balance"]


@dataclass(frozen=True, slots=True)
class RatioInput:
    role: StatementRole
    field: str
    sign: int = 1


@dataclass(frozen=True, slots=True)
class RatioFormula:
    formula_id: str
    name: str
    explanation: str
    expression: str
    numerator: tuple[RatioInput, ...]
    denominator: RatioInput
    output_unit: RatioUnit
    prefers_average: bool = False
    missing_behavior: str = "Unavailable if a required accepted input is missing."
    zero_denominator_behavior: str = "Unavailable; division by zero is not reported."
    ending_only_behavior: str = ""

    @property
    def required_inputs(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                f"{item.role}.{item.field}"
                for item in (*self.numerator, self.denominator)
            )
        )


def _income(field: str, sign: int = 1) -> RatioInput:
    return RatioInput("income", field, sign)


def _balance(field: str, sign: int = 1) -> RatioInput:
    return RatioInput("ending_balance", field, sign)


_AVERAGE_NOTE = (
    "Use the ending balance with a warning when an opening balance is missing."
)
_FORMULAS = (
    RatioFormula(
        "gross_margin_v1",
        "gross_margin",
        "Share of revenue remaining after direct costs.",
        "gross_profit / revenue × 100",
        (_income("gross_profit"),),
        _income("revenue"),
        "percent",
    ),
    RatioFormula(
        "operating_margin_v1",
        "operating_margin",
        "Operating profit or loss as a share of revenue.",
        "operating_income / revenue × 100",
        (_income("operating_income"),),
        _income("revenue"),
        "percent",
    ),
    RatioFormula(
        "net_margin_v1",
        "net_margin",
        "Profit or loss after tax as a share of revenue.",
        "net_income / revenue × 100",
        (_income("net_income"),),
        _income("revenue"),
        "percent",
    ),
    RatioFormula(
        "return_on_assets_v1",
        "return_on_assets",
        "Profit or loss relative to average total assets.",
        "net_income / average(total_assets) × 100",
        (_income("net_income"),),
        _balance("total_assets"),
        "percent",
        prefers_average=True,
        ending_only_behavior=_AVERAGE_NOTE,
    ),
    RatioFormula(
        "return_on_equity_v1",
        "return_on_equity",
        "Profit or loss relative to average shareholders' equity.",
        "net_income / average(shareholders_equity) × 100",
        (_income("net_income"),),
        _balance("shareholders_equity"),
        "percent",
        prefers_average=True,
        ending_only_behavior=_AVERAGE_NOTE,
    ),
    RatioFormula(
        "current_ratio_v1",
        "current_ratio",
        "Current assets compared with current liabilities.",
        "total_current_assets / total_current_liabilities",
        (_balance("total_current_assets"),),
        _balance("total_current_liabilities"),
        "times",
    ),
    RatioFormula(
        "quick_ratio_simplified_v1",
        "quick_ratio",
        "Simplified liquidity ratio that excludes inventory from current assets.",
        "(total_current_assets - inventory) / total_current_liabilities",
        (_balance("total_current_assets"), _balance("inventory", -1)),
        _balance("total_current_liabilities"),
        "times",
    ),
    RatioFormula(
        "interest_bearing_debt_to_equity_v1",
        "debt_to_equity",
        "Interest-bearing short- and long-term debt compared with equity.",
        "(short_term_debt + long_term_debt) / shareholders_equity",
        (_balance("short_term_debt"), _balance("long_term_debt")),
        _balance("shareholders_equity"),
        "times",
    ),
    RatioFormula(
        "interest_coverage_operating_income_v1",
        "interest_coverage",
        "Operating income compared with positive interest expense.",
        "operating_income / interest_expense",
        (_income("operating_income"),),
        _income("interest_expense"),
        "times",
    ),
    RatioFormula(
        "asset_turnover_v1",
        "asset_turnover",
        "Revenue earned for each unit of average assets.",
        "revenue / average(total_assets)",
        (_income("revenue"),),
        _balance("total_assets"),
        "times",
        prefers_average=True,
        ending_only_behavior=_AVERAGE_NOTE,
    ),
    RatioFormula(
        "receivables_turnover_v1",
        "receivables_turnover",
        "Revenue relative to average accounts receivable.",
        "revenue / average(accounts_receivable)",
        (_income("revenue"),),
        _balance("accounts_receivable"),
        "times",
        prefers_average=True,
        ending_only_behavior=_AVERAGE_NOTE,
    ),
    RatioFormula(
        "inventory_turnover_v1",
        "inventory_turnover",
        "Cost of revenue relative to average inventory.",
        "cost_of_revenue / average(inventory)",
        (_income("cost_of_revenue"),),
        _balance("inventory"),
        "times",
        prefers_average=True,
        ending_only_behavior=_AVERAGE_NOTE,
    ),
)

FORMULAS = MappingProxyType({formula.name: formula for formula in _FORMULAS})
