"""Canonical fields for a typical non-financial company's three statements.

Aliases describe common source labels. They are not automatic mapping rules.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

StatementType = Literal["income_statement", "balance_sheet", "cash_flow_statement"]
PeriodBasis = Literal["instant", "duration"]


@dataclass(frozen=True, slots=True)
class CanonicalField:
    machine_name: str
    display_name: str
    statement_type: StatementType
    definition: str
    aliases: tuple[str, ...]
    sign_convention: str
    required: bool  # Core project completeness target, not a universal disclosure rule.
    period_basis: PeriodBasis


_Spec = tuple[str, str, str, tuple[str, ...], str, bool]

POSITIVE_INCOME = "Positive for income earned; reversals or losses are negative."
POSITIVE_EXPENSE = "Positive expense magnitude; refunds or reversals are negative."
SIGNED_PROFIT = "Positive for profit; negative for a loss."
POSITIVE_ASSET = "Positive asset balance; contra balances reduce the total."
POSITIVE_LIABILITY = "Positive amount owed; reversals or debit balances are negative."
SIGNED_EQUITY = "Positive equity balance; a deficit is negative."
POSITIVE_CASH = "Positive cash inflow or noncash add-back; reversal is negative."
NEGATIVE_CASH = "Negative cash outflow; a refund or recovery is positive."
SIGNED_CASH = "Positive cash source; negative cash use."


def _fields(
    statement_type: StatementType, period_basis: PeriodBasis, specs: tuple[_Spec, ...]
) -> tuple[CanonicalField, ...]:
    return tuple(
        CanonicalField(
            machine_name=name,
            display_name=display,
            statement_type=statement_type,
            definition=definition,
            aliases=aliases,
            sign_convention=sign,
            required=required,
            period_basis=period_basis,
        )
        for name, display, definition, aliases, sign, required in specs
    )


INCOME_STATEMENT_FIELDS = _fields(
    "income_statement",
    "duration",
    (
        (
            "revenue",
            "Revenue",
            "Income from goods sold or services provided before expenses.",
            ("Net sales", "Sales revenue", "Turnover"),
            POSITIVE_INCOME,
            True,
        ),
        (
            "cost_of_revenue",
            "Cost of revenue",
            "Direct costs of the goods or services that generated revenue.",
            ("Cost of sales", "Cost of goods sold", "COGS"),
            POSITIVE_EXPENSE,
            False,
        ),
        (
            "gross_profit",
            "Gross profit",
            "Revenue less cost of revenue.",
            ("Gross income", "Gross margin amount"),
            SIGNED_PROFIT,
            False,
        ),
        (
            "research_and_development",
            "Research and development",
            "Expense for research and development activities in the period.",
            ("R&D expense", "Research and development expense"),
            POSITIVE_EXPENSE,
            False,
        ),
        (
            "selling_general_administrative",
            "Selling, general and administrative",
            "Selling, administrative, and general overhead expense.",
            ("SG&A", "Selling, general and administrative expenses"),
            POSITIVE_EXPENSE,
            False,
        ),
        (
            "operating_expenses",
            "Operating expenses",
            "Expenses of operating the business excluding cost of revenue.",
            ("Total operating expenses", "Operating costs"),
            POSITIVE_EXPENSE,
            False,
        ),
        (
            "operating_income",
            "Operating income",
            "Profit or loss from operating activities before nonoperating items.",
            ("Operating profit", "Income from operations"),
            SIGNED_PROFIT,
            False,
        ),
        (
            "interest_income",
            "Interest income",
            "Interest earned on cash, investments, or loans in the period.",
            ("Finance income", "Interest earned"),
            POSITIVE_INCOME,
            False,
        ),
        (
            "interest_expense",
            "Interest expense",
            "Cost of borrowing recognized in the period.",
            ("Finance costs", "Interest costs"),
            POSITIVE_EXPENSE,
            False,
        ),
        (
            "other_income_expense",
            "Other income or expense",
            "Net nonoperating income and expense not shown in another field.",
            ("Other income (expense), net", "Other nonoperating income"),
            "Positive for net income; negative for net expense.",
            False,
        ),
        (
            "income_before_tax",
            "Income before tax",
            "Profit or loss before income tax expense or benefit.",
            ("Pretax income", "Profit before tax", "Earnings before tax"),
            SIGNED_PROFIT,
            False,
        ),
        (
            "income_tax",
            "Income tax",
            "Income tax expense or benefit recognized in the period.",
            ("Income tax expense", "Provision for income taxes"),
            "Positive for tax expense; negative for a tax benefit.",
            False,
        ),
        (
            "net_income",
            "Net income",
            "Profit or loss after income tax for the reporting period.",
            ("Net earnings", "Profit for the year", "Net loss"),
            SIGNED_PROFIT,
            True,
        ),
    ),
)


BALANCE_SHEET_FIELDS = _fields(
    "balance_sheet",
    "instant",
    (
        (
            "cash_and_cash_equivalents",
            "Cash and cash equivalents",
            "Cash and highly liquid short-term equivalents held at the date.",
            ("Cash equivalents", "Cash and short-term deposits"),
            POSITIVE_ASSET,
            False,
        ),
        (
            "short_term_investments",
            "Short-term investments",
            "Investments expected to be realized within the operating cycle or year.",
            ("Marketable securities, current", "Current investments"),
            POSITIVE_ASSET,
            False,
        ),
        (
            "accounts_receivable",
            "Accounts receivable",
            "Amounts owed by customers, generally net of allowances.",
            ("Trade receivables", "Receivables, net"),
            POSITIVE_ASSET,
            False,
        ),
        (
            "inventory",
            "Inventory",
            "Goods held for sale or use in production, at carrying amount.",
            ("Inventories", "Inventory, net"),
            POSITIVE_ASSET,
            False,
        ),
        (
            "other_current_assets",
            "Other current assets",
            "Current assets not assigned to a more specific taxonomy field.",
            ("Prepaid expenses and other current assets", "Other short-term assets"),
            POSITIVE_ASSET,
            False,
        ),
        (
            "total_current_assets",
            "Total current assets",
            "Assets expected to be realized or used in the operating cycle or year.",
            ("Current assets", "Total short-term assets"),
            POSITIVE_ASSET,
            False,
        ),
        (
            "property_plant_equipment",
            "Property, plant and equipment",
            "Tangible long-lived operating assets at net carrying amount.",
            ("PP&E, net", "Property and equipment, net", "Fixed assets"),
            POSITIVE_ASSET,
            False,
        ),
        (
            "goodwill",
            "Goodwill",
            "Acquisition goodwill remaining at the reporting date.",
            ("Goodwill, net",),
            POSITIVE_ASSET,
            False,
        ),
        (
            "intangible_assets",
            "Intangible assets",
            "Identifiable nonphysical assets at net carrying amount.",
            ("Other intangible assets, net", "Intangibles, net"),
            POSITIVE_ASSET,
            False,
        ),
        (
            "other_noncurrent_assets",
            "Other noncurrent assets",
            "Noncurrent assets not assigned to a more specific field.",
            ("Other long-term assets", "Other assets, noncurrent"),
            POSITIVE_ASSET,
            False,
        ),
        (
            "total_assets",
            "Total assets",
            "Total resources controlled by the entity at the reporting date.",
            ("Assets, total",),
            POSITIVE_ASSET,
            True,
        ),
        (
            "accounts_payable",
            "Accounts payable",
            "Amounts owed to suppliers for goods or services received.",
            ("Trade payables", "Trade and other payables"),
            POSITIVE_LIABILITY,
            False,
        ),
        (
            "short_term_debt",
            "Short-term debt",
            "Borrowings due within the operating cycle or year.",
            ("Current borrowings", "Current portion of long-term debt"),
            POSITIVE_LIABILITY,
            False,
        ),
        (
            "other_current_liabilities",
            "Other current liabilities",
            "Current obligations not assigned to a more specific field.",
            ("Accrued expenses and other current liabilities",),
            POSITIVE_LIABILITY,
            False,
        ),
        (
            "total_current_liabilities",
            "Total current liabilities",
            "Total obligations due within the operating cycle or year.",
            ("Current liabilities", "Total short-term liabilities"),
            POSITIVE_LIABILITY,
            False,
        ),
        (
            "long_term_debt",
            "Long-term debt",
            "Borrowings due beyond the operating cycle or year.",
            ("Long-term borrowings", "Noncurrent debt"),
            POSITIVE_LIABILITY,
            False,
        ),
        (
            "other_noncurrent_liabilities",
            "Other noncurrent liabilities",
            "Long-term obligations not assigned to a more specific field.",
            ("Other long-term liabilities",),
            POSITIVE_LIABILITY,
            False,
        ),
        (
            "total_liabilities",
            "Total liabilities",
            "Total present obligations at the reporting date.",
            ("Liabilities, total",),
            POSITIVE_LIABILITY,
            True,
        ),
        (
            "common_stock",
            "Common stock",
            "Carrying amount of issued common shares and related share capital.",
            ("Ordinary share capital", "Common shares"),
            SIGNED_EQUITY,
            False,
        ),
        (
            "retained_earnings",
            "Retained earnings",
            "Cumulative earnings retained after distributions and adjustments.",
            ("Accumulated earnings", "Accumulated deficit"),
            SIGNED_EQUITY,
            False,
        ),
        (
            "accumulated_other_comprehensive_income",
            "Accumulated other comprehensive income",
            "Cumulative other comprehensive income or loss in equity.",
            ("AOCI", "Accumulated other comprehensive loss"),
            SIGNED_EQUITY,
            False,
        ),
        (
            "treasury_stock",
            "Treasury stock",
            "Cost of the entity's own shares held in treasury.",
            ("Treasury shares", "Repurchased shares held"),
            "Negative contra-equity balance; reissuance reduces the deduction.",
            False,
        ),
        (
            "shareholders_equity",
            "Shareholders' equity",
            "Residual interest in assets after deducting liabilities.",
            ("Stockholders' equity", "Total equity", "Owners' equity"),
            SIGNED_EQUITY,
            True,
        ),
    ),
)


CASH_FLOW_FIELDS = _fields(
    "cash_flow_statement",
    "duration",
    (
        (
            "net_income",
            "Net income",
            "Profit or loss reported in an indirect cash flow reconciliation.",
            ("Net earnings", "Profit for the period"),
            SIGNED_PROFIT,
            False,
        ),
        (
            "depreciation_amortization",
            "Depreciation and amortization",
            "Noncash depreciation and amortization adjustment to operating cash flow.",
            ("Depreciation and amortisation", "D&A"),
            POSITIVE_CASH,
            False,
        ),
        (
            "stock_based_compensation",
            "Stock-based compensation",
            "Noncash share-based compensation adjustment to operating cash flow.",
            ("Share-based compensation", "Equity compensation expense"),
            POSITIVE_CASH,
            False,
        ),
        (
            "change_in_receivables",
            "Change in receivables",
            "Operating cash effect of the change in receivables.",
            ("Changes in accounts receivable", "Increase in receivables"),
            "Increase in receivables is negative; decrease is positive.",
            False,
        ),
        (
            "change_in_inventory",
            "Change in inventory",
            "Operating cash effect of the change in inventory.",
            ("Changes in inventories", "Increase in inventory"),
            "Increase in inventory is negative; decrease is positive.",
            False,
        ),
        (
            "change_in_payables",
            "Change in payables",
            "Operating cash effect of the change in trade payables.",
            ("Changes in accounts payable", "Increase in payables"),
            "Increase in payables is positive; decrease is negative.",
            False,
        ),
        (
            "operating_cash_flow",
            "Operating cash flow",
            "Net cash generated by or used in operating activities.",
            ("Net cash from operating activities", "Cash from operations"),
            SIGNED_CASH,
            True,
        ),
        (
            "capital_expenditure",
            "Capital expenditure",
            "Cash spent to acquire or improve long-lived operating assets.",
            ("Purchases of property and equipment", "Capex"),
            NEGATIVE_CASH,
            False,
        ),
        (
            "acquisitions",
            "Acquisitions",
            "Net cash paid to acquire businesses during the period.",
            ("Business acquisitions, net of cash acquired",),
            NEGATIVE_CASH,
            False,
        ),
        (
            "investing_cash_flow",
            "Investing cash flow",
            "Net cash generated by or used in investing activities.",
            ("Net cash from investing activities",),
            SIGNED_CASH,
            True,
        ),
        (
            "debt_issuance",
            "Debt issuance",
            "Cash proceeds from issuing or drawing borrowings.",
            ("Proceeds from borrowings", "Debt proceeds"),
            POSITIVE_CASH,
            False,
        ),
        (
            "debt_repayment",
            "Debt repayment",
            "Cash paid to repay borrowing principal.",
            ("Repayments of borrowings", "Debt principal payments"),
            NEGATIVE_CASH,
            False,
        ),
        (
            "dividends",
            "Dividends",
            "Cash dividends paid to owners during the period.",
            ("Dividends paid", "Cash distributions to shareholders"),
            NEGATIVE_CASH,
            False,
        ),
        (
            "share_repurchases",
            "Share repurchases",
            "Cash paid to buy back the entity's own shares.",
            ("Repurchases of common stock", "Treasury share purchases"),
            NEGATIVE_CASH,
            False,
        ),
        (
            "financing_cash_flow",
            "Financing cash flow",
            "Net cash generated by or used in financing activities.",
            ("Net cash from financing activities",),
            SIGNED_CASH,
            True,
        ),
        (
            "net_change_in_cash",
            "Net change in cash",
            "Overall increase or decrease in cash and cash equivalents for the period.",
            ("Net increase in cash", "Net decrease in cash"),
            SIGNED_CASH,
            True,
        ),
    ),
)


TAXONOMY = INCOME_STATEMENT_FIELDS + BALANCE_SHEET_FIELDS + CASH_FLOW_FIELDS
FIELDS_BY_STATEMENT = MappingProxyType(
    {
        statement_type: MappingProxyType(
            {
                field.machine_name: field
                for field in TAXONOMY
                if field.statement_type == statement_type
            }
        )
        for statement_type in (
            "income_statement",
            "balance_sheet",
            "cash_flow_statement",
        )
    }
)


def get_field(statement_type: StatementType, machine_name: str) -> CanonicalField:
    """Find an exact canonical key in a known statement type."""
    return FIELDS_BY_STATEMENT[statement_type][machine_name]


def fields_for_statement(statement_type: StatementType) -> tuple[CanonicalField, ...]:
    """List the fields in their documented statement order."""
    return tuple(FIELDS_BY_STATEMENT[statement_type].values())
