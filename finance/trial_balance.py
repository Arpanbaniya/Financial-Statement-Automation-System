"""Original trial-balance compiler. Money is Decimal; unknowns never become plugs."""

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ingestion import ingest_document
from normalization import SourceLocation, normalize_period
from normalization.taxonomy import fields_for_statement
from validation import SourceRef, StatementSnapshot, ValidationValue

ZERO = Decimal(0)
TOLERANCE = Decimal("0.01")
MAX_ROWS = 1000

# Category -> (canonical statement field, debit-positive, human label, aliases).
# Contra accounts deliberately use the sign of the parent statement field.
CATEGORIES = {
    "cash": (
        "cash_and_cash_equivalents",
        True,
        "Cash and bank",
        ("cash", "bank", "cash at bank", "petty cash", "cash in hand"),
    ),
    "receivables": (
        "accounts_receivable",
        True,
        "Trade receivables (net)",
        (
            "accounts receivable",
            "trade receivables",
            "sundry debtors",
            "allowance for doubtful debts",
        ),
    ),
    "inventory": (
        "inventory",
        True,
        "Inventory",
        ("inventory", "stock", "closing stock"),
    ),
    "other_current_assets": (
        "other_current_assets",
        True,
        "Other operating current assets",
        ("prepaid expenses", "prepayments"),
    ),
    "investments": (
        "short_term_investments",
        True,
        "Short-term investments",
        ("short term investments",),
    ),
    "ppe": (
        "property_plant_equipment",
        True,
        "Property, plant and equipment (net)",
        (
            "equipment",
            "land",
            "buildings",
            "machinery",
            "accumulated depreciation",
            "furniture",
            "vehicles",
        ),
    ),
    "intangibles": (
        "intangible_assets",
        True,
        "Intangible assets (net)",
        ("intangible assets", "accumulated amortization"),
    ),
    "other_noncurrent_assets": (
        "other_noncurrent_assets",
        True,
        "Other noncurrent assets",
        ("other noncurrent assets", "long term investments"),
    ),
    "payables": (
        "accounts_payable",
        False,
        "Trade payables",
        ("accounts payable", "trade payables", "sundry creditors"),
    ),
    "short_term_debt": (
        "short_term_debt",
        False,
        "Short-term borrowing",
        ("short term debt", "bank overdraft"),
    ),
    "other_current_liabilities": (
        "other_current_liabilities",
        False,
        "Other operating current liabilities",
        (
            "accrued expenses",
            "tax payable",
            "income tax payable",
            "salaries payable",
            "customer advances",
        ),
    ),
    "long_term_debt": (
        "long_term_debt",
        False,
        "Long-term borrowing",
        ("long term debt", "long term loan"),
    ),
    "other_noncurrent_liabilities": (
        "other_noncurrent_liabilities",
        False,
        "Other noncurrent liabilities",
        ("other noncurrent liabilities",),
    ),
    "capital": (
        "common_stock",
        False,
        "Owner / share capital",
        ("capital", "share capital", "common stock", "owners capital"),
    ),
    "retained_earnings": (
        "retained_earnings",
        False,
        "Retained earnings brought forward",
        ("retained earnings", "opening retained earnings"),
    ),
    "other_equity": (
        "other_equity",
        False,
        "Other equity reserves",
        ("other equity", "reserves", "revaluation reserve"),
    ),
    "oci": (
        "accumulated_other_comprehensive_income",
        False,
        "Accumulated other comprehensive income",
        ("accumulated other comprehensive income", "aoci"),
    ),
    "treasury_stock": (
        "treasury_stock",
        False,
        "Treasury stock (contra equity)",
        ("treasury stock",),
    ),
    "dividends": (
        "dividends",
        True,
        "Dividends declared / drawings",
        ("dividends", "dividends declared", "drawings", "owner drawings"),
    ),
    "revenue": (
        "revenue",
        False,
        "Revenue (net of returns)",
        (
            "revenue",
            "sales",
            "sales revenue",
            "service revenue",
            "sales returns",
            "sales discounts",
        ),
    ),
    "cost_of_revenue": (
        "cost_of_revenue",
        True,
        "Cost of goods / services sold",
        ("cost of goods sold", "cost of sales", "cogs"),
    ),
    "operating_expenses": (
        "operating_expenses",
        True,
        "Operating expenses",
        (
            "operating expenses",
            "rent expense",
            "salaries expense",
            "utilities expense",
            "insurance expense",
            "wages expense",
            "advertising expense",
            "bank charges",
        ),
    ),
    "depreciation": (
        "operating_expenses",
        True,
        "Depreciation and amortization expense",
        (
            "depreciation",
            "depreciation expense",
            "amortization expense",
            "depreciation and amortization",
        ),
    ),
    "interest_income": (
        "interest_income",
        False,
        "Interest income",
        ("interest income",),
    ),
    "interest_expense": (
        "interest_expense",
        True,
        "Interest expense",
        ("interest expense", "finance costs"),
    ),
    "other_income": (
        "other_income_expense",
        False,
        "Other income / expense (net)",
        ("other income", "other expense", "gain on disposal", "loss on disposal"),
    ),
    "income_tax": (
        "income_tax",
        True,
        "Income tax expense",
        ("income tax expense", "tax expense"),
    ),
}
PROFIT_CATEGORIES = {
    "revenue",
    "cost_of_revenue",
    "operating_expenses",
    "depreciation",
    "interest_income",
    "interest_expense",
    "other_income",
    "income_tax",
}


class CashInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool = False
    # Gross cash movements, entered explicitly including genuine zeros.
    capex: Decimal = Field(ge=0, le=Decimal("1e15"))
    asset_sale_proceeds: Decimal = Field(ge=0, le=Decimal("1e15"))
    other_investing: Decimal = Field(ge=Decimal("-1e15"), le=Decimal("1e15"))
    borrowing: Decimal = Field(ge=0, le=Decimal("1e15"))
    debt_repaid: Decimal = Field(ge=0, le=Decimal("1e15"))
    equity_issued: Decimal = Field(ge=0, le=Decimal("1e15"))
    dividends_paid: Decimal = Field(ge=0, le=Decimal("1e15"))
    shares_repurchased: Decimal = Field(ge=0, le=Decimal("1e15"))
    other_financing: Decimal = Field(ge=Decimal("-1e15"), le=Decimal("1e15"))
    operating_adjustments: Decimal = Field(ge=Decimal("-1e15"), le=Decimal("1e15"))
    fx_effect: Decimal = Field(ge=Decimal("-1e15"), le=Decimal("1e15"))
    notes: str = Field(min_length=1, max_length=2000)


class TrialBalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    period_start: date
    period_end: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    unit_scale: Literal["ones", "thousands", "millions", "billions"] = "ones"
    basis: Literal["pre_closing", "post_closing"] = "pre_closing"
    sheet: str | None = Field(default=None, max_length=255)
    mappings: dict[str, str] = Field(default_factory=dict, max_length=MAX_ROWS)
    exclusions: list[str] = Field(default_factory=list, max_length=MAX_ROWS)
    complete: bool = False
    opening_complete: bool = False
    cash: CashInputs | None = None

    @model_validator(mode="after")
    def validate_request(self):
        if not (
            date(1900, 1, 1)
            <= self.period_start
            <= self.period_end
            <= date(2200, 12, 31)
        ):
            raise ValueError("Choose a valid reporting period between 1900 and 2200")
        if any(value not in CATEGORIES for value in self.mappings.values()):
            raise ValueError("Unknown account category")
        return self


def key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def money(value: object) -> Decimal:
    if value is None or str(value).strip() in {"", "-", "—"}:
        return ZERO
    if isinstance(value, bool):
        raise ValueError("Boolean values are not amounts")
    raw = str(value).strip().replace(",", "")
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(
            "Use numeric values, without formulas, currency symbols or k suffixes"
        ) from exc
    if not result.is_finite() or result < 0 or result > Decimal("1e15"):
        raise ValueError(
            "Debit and credit must be finite, nonnegative amounts up to 1e15"
        )
    if result.as_tuple().exponent < -4:
        raise ValueError("Use at most four decimal places")
    return result


HEADERS = {
    "account": {"account", "account name", "ledger", "ledger name", "description"},
    "code": {"code", "account code", "account number", "gl code"},
    "debit": {"debit", "debits", "dr", "closing debit"},
    "credit": {"credit", "credits", "cr", "closing credit"},
    "opening_debit": {"opening debit", "opening dr", "prior debit"},
    "opening_credit": {"opening credit", "opening cr", "prior credit"},
}


def parse_trial_balance(
    source: bytes, filename: str, mime: str, sheet: str | None = None
) -> dict:
    document = ingest_document(source, filename=filename, mime_type=mime)
    if document.file_type not in {"csv", "xlsx"}:
        raise ValueError("Trial balances must be CSV or XLSX")
    sources = (
        {item.name: item.rows for item in document.sheets}
        if document.file_type == "xlsx"
        else {"CSV": document.tables[0].rows}
    )
    candidates = {}
    for name, rows in sources.items():
        for index, row in enumerate(rows[:30]):
            headers = {}
            for cell in row.cells:
                for field, aliases in HEADERS.items():
                    if key(cell.value) in aliases:
                        if field in headers:
                            raise ValueError(f"{name}: duplicate {field} columns")
                        headers[field] = re.sub(r"\d", "", cell.coordinate)
            if {"account", "debit", "credit"} <= headers.keys():
                candidates[name] = (rows[index + 1 :], headers)
                break
    if not candidates:
        raise ValueError(
            "Add a header row with Account Name, Debit and Credit. "
            "Account Code and Opening Debit / Opening Credit are optional."
        )
    if sheet and sheet not in candidates:
        raise ValueError("The selected sheet has no trial-balance header")
    if not sheet and len(candidates) > 1:
        return {
            "sheets": list(candidates),
            "rows": [],
            "issues": [
                "Choose one trial-balance sheet; other sheets will not be combined."
            ],
            "has_opening": False,
        }
    selected = sheet or next(iter(candidates))
    source_rows, headers = candidates[selected]
    if ("opening_debit" in headers) != ("opening_credit" in headers):
        raise ValueError("Include both Opening Debit and Opening Credit columns")
    rows, issues = [], []
    for row in source_rows:
        cells = {re.sub(r"\d", "", cell.coordinate): cell for cell in row.cells}
        values = {
            field: cells[column].value if column in cells else None
            for field, column in headers.items()
        }
        if all(value is None or str(value).strip() == "" for value in values.values()):
            continue
        account = str(values.get("account") or "").strip()
        row_id = f"{selected}!{row.number}"
        subtotal = key(account) in {
            "total",
            "grand total",
            "trial balance total",
        } or key(account).startswith("total for ")
        errors = []
        amounts = {}
        for field in ("debit", "credit", "opening_debit", "opening_credit"):
            try:
                amounts[field] = str(money(values.get(field)))
            except ValueError as exc:
                amounts[field] = "0"
                errors.append(f"{field}: {exc}")
        if not account:
            errors.append("Account name is missing")
        if not subtotal and Decimal(amounts["debit"]) and Decimal(amounts["credit"]):
            errors.append(
                "Both debit and credit contain a balance; "
                "supply closing balances, not turnover"
            )
        if (
            not subtotal
            and Decimal(amounts["opening_debit"])
            and Decimal(amounts["opening_credit"])
        ):
            errors.append("Opening balance has both debit and credit")
        category = next(
            (
                name
                for name, spec in CATEGORIES.items()
                if key(account) in {key(alias) for alias in spec[3]}
            ),
            None,
        )
        rows.append(
            {
                "id": row_id,
                "account": account,
                "code": str(values.get("code") or ""),
                **amounts,
                "category": category,
                "subtotal": subtotal,
                "errors": errors,
                "source_sheet": selected,
                "source_cell": (
                    f"{headers['debit']}{row.number}:{headers['credit']}{row.number}"
                ),
            }
        )
    if len(rows) > MAX_ROWS:
        raise ValueError(f"Use at most {MAX_ROWS} account rows per trial balance")
    if not rows:
        issues.append("The trial balance has no account rows")
    return {
        "sheets": list(candidates),
        "sheet": selected,
        "rows": rows,
        "issues": issues,
        "has_opening": "opening_debit" in headers,
    }


def compile_trial_balance(parsed: dict, request: TrialBalanceRequest) -> dict:
    with localcontext() as context:
        context.prec = 40
        return _compile(parsed, request)


def _compile(parsed: dict, request: TrialBalanceRequest) -> dict:
    """Aggregate once, derive statements, and expose every failed prerequisite."""
    issues = list(parsed["issues"])
    warnings = []
    scale = Decimal(
        {"ones": 1, "thousands": 1000, "millions": 1000000, "billions": 1000000000}[
            request.unit_scale
        ]
    )
    groups, opening = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    debit = credit = opening_debit = opening_credit = ZERO
    rows, seen = [], set()
    known_ids = {row["id"] for row in parsed["rows"]}
    if (set(request.mappings) | set(request.exclusions)) - known_ids:
        issues.append("Mappings or exclusions refer to rows outside the selected sheet")
    for source_row in parsed["rows"]:
        row = {
            **source_row,
            "category": request.mappings.get(source_row["id"], source_row["category"]),
        }
        row["excluded"] = row["subtotal"] or row["id"] in request.exclusions
        rows.append(row)
        if row["excluded"]:
            continue
        if row["errors"]:
            issues.extend(f"{row['id']}: {error}" for error in row["errors"])
        identity = row["code"].strip() or key(row["account"])
        if identity in seen:
            issues.append(
                f"{row['id']}: duplicate account {identity}; "
                "consolidate it or exclude an accidental duplicate"
            )
        seen.add(identity)
        d, c, od, oc = (
            Decimal(row[field]) * scale
            for field in ("debit", "credit", "opening_debit", "opening_credit")
        )
        debit += d
        credit += c
        opening_debit += od
        opening_credit += oc
        if not row["category"]:
            issues.append(f"{row['id']}: map {row['account']} to a category")
            continue
        groups[row["category"]] += d - c
        opening[row["category"]] += od - oc
    if not seen:
        issues.append("At least one account must be included")
    if abs(debit - credit) > TOLERANCE:
        issues.append(
            f"Trial balance does not balance: debit minus credit = {debit - credit}"
        )
    if not request.complete:
        issues.append(
            "Confirm the complete adjusted trial balance and review the mappings"
        )
    if request.basis == "post_closing" and any(
        groups[name] for name in PROFIT_CATEGORIES | {"dividends"}
    ):
        issues.append(
            "Post-closing balances must have zero income, expenses and dividends"
        )
    for row in rows:
        if row["subtotal"]:
            warnings.append(f"Excluded subtotal: {row['id']} {row['account']}")
    output = {
        **parsed,
        "rows": rows,
        "issues": issues,
        "warnings": warnings,
        "debit": str(debit),
        "credit": str(credit),
        "difference": str(debit - credit),
        "statements": {},
        "opening_balance": None,
        "cash_flow_issues": [],
        "retained_earnings": {},
        "ready": not issues,
    }
    if issues:
        return output

    def amount(category, balances=groups):
        return balances[category] * (1 if CATEGORIES[category][1] else -1)

    def balance(balances, profit=ZERO):
        result = {
            spec[0]: ZERO
            for name, spec in CATEGORIES.items()
            if name not in PROFIT_CATEGORIES | {"dividends"}
        }
        for name, spec in CATEGORIES.items():
            if name not in PROFIT_CATEGORIES | {"dividends"}:
                result[spec[0]] += amount(name, balances)
        result["retained_earnings"] += profit - amount("dividends", balances)
        result["total_current_assets"] = sum(
            result[f]
            for f in (
                "cash_and_cash_equivalents",
                "accounts_receivable",
                "inventory",
                "other_current_assets",
                "short_term_investments",
            )
        )
        result["total_assets"] = result["total_current_assets"] + sum(
            result[f]
            for f in (
                "property_plant_equipment",
                "intangible_assets",
                "other_noncurrent_assets",
            )
        )
        result["total_current_liabilities"] = sum(
            result[f]
            for f in (
                "accounts_payable",
                "short_term_debt",
                "other_current_liabilities",
            )
        )
        result["total_liabilities"] = (
            result["total_current_liabilities"]
            + result["long_term_debt"]
            + result["other_noncurrent_liabilities"]
        )
        result["shareholders_equity"] = sum(
            result[f]
            for f in (
                "common_stock",
                "retained_earnings",
                "accumulated_other_comprehensive_income",
                "other_equity",
                "treasury_stock",
            )
        )
        return result

    income = {}
    if request.basis == "pre_closing":
        income = {
            field.machine_name: ZERO
            for field in fields_for_statement("income_statement")
        }
        for name in PROFIT_CATEGORIES:
            income[CATEGORIES[name][0]] += amount(name)
        income["gross_profit"] = income["revenue"] - income["cost_of_revenue"]
        income["operating_income"] = (
            income["gross_profit"] - income["operating_expenses"]
        )
        income["income_before_tax"] = (
            income["operating_income"]
            + income["interest_income"]
            - income["interest_expense"]
            + income["other_income_expense"]
        )
        income["net_income"] = income["income_before_tax"] - income["income_tax"]
        output["statements"]["income_statement"] = income
    else:
        warnings.append(
            "Post-closing TB generates a balance sheet only. "
            "Upload a pre-closing TB for income and cash flow."
        )
    current = balance(groups, income.get("net_income", ZERO))
    if (
        abs(
            current["total_assets"]
            - current["total_liabilities"]
            - current["shareholders_equity"]
        )
        > TOLERANCE
    ):
        raise ValueError("Generated balance sheet failed reconciliation")
    output["statements"]["balance_sheet"] = current
    output["retained_earnings"] = {
        "brought_forward": amount("retained_earnings"),
        "profit": income.get("net_income", ZERO),
        "distributions": amount("dividends"),
        "closing": current["retained_earnings"],
    }
    cf_issues = output["cash_flow_issues"]
    if not parsed["has_opening"] or not request.opening_complete:
        cf_issues.append(
            "Supply complete opening debit / credit balances "
            "at the day before the period starts"
        )
    elif abs(opening_debit - opening_credit) > TOLERANCE:
        cf_issues.append(
            f"Opening trial balance differs by {opening_debit - opening_credit}"
        )
    elif any(opening[name] for name in PROFIT_CATEGORIES | {"dividends"}):
        cf_issues.append(
            "Opening TB must be post-closing: "
            "income, expenses and dividends must be zero"
        )
    else:
        output["opening_balance"] = balance(opening)
    if not income:
        cf_issues.append(
            "A pre-closing current trial balance is required for cash flow"
        )
    if not request.cash or not request.cash.confirmed:
        cf_issues.append(
            "Complete and confirm the cash movement schedule, "
            "including noncash / FX adjustments"
        )
    if not cf_issues:
        prior = output["opening_balance"]
        cash = request.cash
        cash_values = {
            name: value * scale
            for name, value in cash.model_dump().items()
            if isinstance(value, Decimal)
        }
        c = cash_values
        cash_flow = {
            "net_income": income["net_income"],
            "depreciation_amortization": amount("depreciation"),
        }
        for field, cf_field, sign in (
            ("accounts_receivable", "change_in_receivables", -1),
            ("inventory", "change_in_inventory", -1),
            ("accounts_payable", "change_in_payables", 1),
        ):
            cash_flow[cf_field] = (current[field] - prior[field]) * sign
        other_wc = (
            -(current["other_current_assets"] - prior["other_current_assets"])
            + current["other_current_liabilities"]
            - prior["other_current_liabilities"]
        )
        cash_flow["operating_cash_flow"] = (
            sum(cash_flow.values()) + other_wc + c["operating_adjustments"]
        )
        cash_flow["other_working_capital"] = other_wc
        cash_flow["other_operating_adjustments"] = c["operating_adjustments"]
        cash_flow["capital_expenditure"] = -c["capex"]
        cash_flow["investing_cash_flow"] = (
            -c["capex"] + c["asset_sale_proceeds"] + c["other_investing"]
        )
        cash_flow["asset_sale_proceeds"] = c["asset_sale_proceeds"]
        cash_flow["other_investing_cash_flow"] = c["other_investing"]
        cash_flow["equity_issuance"] = c["equity_issued"]
        cash_flow["other_financing_cash_flow"] = c["other_financing"]
        cash_flow["debt_issuance"] = c["borrowing"]
        cash_flow["debt_repayment"] = -c["debt_repaid"]
        cash_flow["dividends"] = -c["dividends_paid"]
        cash_flow["share_repurchases"] = -c["shares_repurchased"]
        cash_flow["financing_cash_flow"] = (
            c["borrowing"]
            - c["debt_repaid"]
            + c["equity_issued"]
            - c["dividends_paid"]
            - c["shares_repurchased"]
            + c["other_financing"]
        )
        # FX is a separate cash reconciliation item, never an operating plug.
        cash_flow["fx_effect"] = c["fx_effect"]
        cash_flow["net_change_in_cash"] = sum(
            cash_flow[f]
            for f in (
                "operating_cash_flow",
                "investing_cash_flow",
                "financing_cash_flow",
                "fx_effect",
            )
        )
        closing = prior["cash_and_cash_equivalents"] + cash_flow["net_change_in_cash"]
        cash_flow["beginning_cash"] = prior["cash_and_cash_equivalents"]
        cash_flow["ending_cash"] = current["cash_and_cash_equivalents"]
        output["cash_bridge"] = {
            "opening_cash": prior["cash_and_cash_equivalents"],
            "fx_effect": c["fx_effect"],
            "closing_cash": current["cash_and_cash_equivalents"],
            "difference": closing - current["cash_and_cash_equivalents"],
            "other_working_capital": other_wc,
            "operating_adjustments": c["operating_adjustments"],
        }
        if abs(closing - current["cash_and_cash_equivalents"]) > TOLERANCE:
            cf_issues.append(
                "Cash flow does not reconcile to closing cash; unexplained "
                f"difference {closing - current['cash_and_cash_equivalents']}. "
                "Review the movement schedule."
            )
        else:
            order = (
                "net_income",
                "depreciation_amortization",
                "change_in_receivables",
                "change_in_inventory",
                "change_in_payables",
                "other_working_capital",
                "other_operating_adjustments",
                "operating_cash_flow",
                "capital_expenditure",
                "asset_sale_proceeds",
                "other_investing_cash_flow",
                "investing_cash_flow",
                "debt_issuance",
                "debt_repayment",
                "equity_issuance",
                "dividends",
                "share_repurchases",
                "other_financing_cash_flow",
                "financing_cash_flow",
                "fx_effect",
                "net_change_in_cash",
                "beginning_cash",
                "ending_cash",
            )
            output["statements"]["cash_flow_statement"] = {
                field: cash_flow[field] for field in order
            }
    return output


def snapshots(
    result: dict, request: TrialBalanceRequest, document_id: str
) -> tuple[StatementSnapshot, ...]:
    statements = []
    for kind, amounts in result["statements"].items():
        statement_id = str(uuid5(NAMESPACE_URL, f"{document_id}:{kind}"))
        statements.append(
            StatementSnapshot(
                id=statement_id,
                company_id=request.company_id,
                document_id=document_id,
                statement_type=kind,
                period=normalize_period(
                    kind,
                    start=request.period_start if kind != "balance_sheet" else None,
                    end=request.period_end,
                ),
                currency=request.currency,
                unit_scale="ones",
                current_assets_components_complete=True,
                current_liabilities_components_complete=True,
                operating_expenses_exclude_cost=True,
                cash_flow_components_complete=True,
                values=tuple(
                    ValidationValue(
                        field=field,
                        normalized_value=value,
                        original_value=str(value),
                        source_ref=SourceRef(
                            statement_id,
                            str(uuid5(NAMESPACE_URL, f"{statement_id}:{field}")),
                            SourceLocation(sheet=result.get("sheet"), cell="TB"),
                        ),
                        currency=request.currency,
                        unit_scale="ones",
                        status="accepted",
                    )
                    for field, value in amounts.items()
                ),
            )
        )
    if result.get("opening_balance"):
        statement_id = str(uuid5(NAMESPACE_URL, f"{document_id}:opening"))
        statements.append(
            StatementSnapshot(
                id=statement_id,
                company_id=request.company_id,
                document_id=document_id,
                statement_type="balance_sheet",
                period=normalize_period(
                    "balance_sheet", end=request.period_start - timedelta(days=1)
                ),
                currency=request.currency,
                unit_scale="ones",
                values=tuple(
                    ValidationValue(
                        field=field,
                        normalized_value=value,
                        original_value=str(value),
                        source_ref=SourceRef(
                            statement_id,
                            str(uuid5(NAMESPACE_URL, f"{statement_id}:{field}")),
                            SourceLocation(
                                sheet=result.get("sheet"), cell="Opening TB"
                            ),
                        ),
                        currency=request.currency,
                        unit_scale="ones",
                        status="accepted",
                    )
                    for field, value in result["opening_balance"].items()
                ),
            )
        )
    return tuple(statements)
