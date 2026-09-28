"""Hand-reconciled trial balances, negative cases and shared analysis/export."""

from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from api.trial_balance import analysis
from finance.trial_balance import (
    CashInputs,
    TrialBalanceRequest,
    compile_trial_balance,
    parse_trial_balance,
)
from reports.trial_balance import build_trial_balance_report

COMPANY = "11111111-1111-4111-8111-111111111111"
DOCUMENT = "22222222-2222-4222-8222-222222222222"
# Opening: A=1500, L=300, E=1200. NI=400; dividends=100.
# Closing: A=1900, L=400, E=1500. Cash: 500+500-100-100=800.
SOURCE = b"""Account Code,Account Name,Debit,Credit,Opening Debit,Opening Credit
100,Cash,800,0,500,0
110,Accounts receivable,300,0,200,0
120,Inventory,200,0,100,0
150,Equipment,800,0,700,0
151,Accumulated depreciation,0,200,0,0
200,Accounts payable,0,200,0,100
210,Long term debt,0,200,0,200
300,Capital,0,1000,0,1000
310,Retained earnings,0,200,0,200
320,Dividends,100,0,0,0
400,Sales revenue,0,1500,0,0
500,Cost of goods sold,600,0,0,0
510,Rent expense,300,0,0,0
520,Depreciation expense,200,0,0,0
"""


def request(**kwargs):
    return TrialBalanceRequest(
        company_id=COMPANY,
        period_start="2025-01-01",
        period_end="2025-12-31",
        currency="USD",
        **{"complete": True, **kwargs},
    )


def cash(**kwargs):
    return CashInputs(
        **{
            **dict.fromkeys(
                (
                    "capex",
                    "asset_sale_proceeds",
                    "other_investing",
                    "borrowing",
                    "debt_repaid",
                    "equity_issued",
                    "dividends_paid",
                    "shares_repurchased",
                    "other_financing",
                    "operating_adjustments",
                    "fx_effect",
                ),
                "0",
            ),
            "capex": "100",
            "borrowing": "0",
            "dividends_paid": "100",
            "confirmed": True,
            "notes": "Synthetic movements; no other adjustments.",
            **kwargs,
        }
    )


def compile(source=SOURCE, **kwargs):
    return compile_trial_balance(
        parse_trial_balance(source, "trial.csv", "text/csv"), request(**kwargs)
    )


def test_preclosing_profit_and_distributions_flow_once():
    result = compile()
    assert result["ready"], result["issues"]
    income = result["statements"]["income_statement"]
    balance = result["statements"]["balance_sheet"]
    assert income["net_income"] == 400
    assert balance["retained_earnings"] == 500
    assert balance["total_assets"] == 1900
    assert balance["total_liabilities"] == 400
    assert balance["shareholders_equity"] == 1500
    assert "cash_flow_statement" not in result["statements"]


def test_cash_flow_requires_comparative_and_confirmed_schedule():
    result = compile(opening_complete=True, cash=cash())
    assert not result["cash_flow_issues"], result["cash_flow_issues"]
    cf = result["statements"]["cash_flow_statement"]
    assert cf["operating_cash_flow"] == 500
    assert cf["investing_cash_flow"] == -100
    assert cf["financing_cash_flow"] == -100
    assert cf["net_change_in_cash"] == 300
    assert result["cash_bridge"]["difference"] == 0
    blocked = compile(opening_complete=True, cash=cash(capex="200"))
    assert "cash_flow_statement" not in blocked["statements"]
    assert "difference -100" in blocked["cash_flow_issues"][0]


@pytest.mark.parametrize(
    "source,fragment",
    [
        (SOURCE.replace(b"Cash,800", b"Cash,801"), "does not balance"),
        (SOURCE + b"100,Cash,0,0,0,0\n", "duplicate account"),
        (SOURCE.replace(b"Rent expense", b"Unclear cost"), "map Unclear cost"),
        (SOURCE.replace(b"Cash,800,0", b"Cash,900,100"), "Both debit and credit"),
        (SOURCE.replace(b"Cash,800", b"Cash,=400+400"), "numeric values"),
        (SOURCE.replace(b"Cash,800", b"Cash,NaN"), "finite"),
        (SOURCE.replace(b"Cash,800", b"Cash,-800"), "nonnegative"),
    ],
)
def test_bad_inputs_block_statements(source, fragment):
    result = compile(source)
    assert not result["ready"]
    assert not result["statements"]
    assert any(fragment in issue for issue in result["issues"])


def test_mapping_correction_rebuilds_without_mutating_source():
    source = SOURCE.replace(b"Rent expense", b"Office occupancy")
    parsed = parse_trial_balance(source, "trial.csv", "text/csv")
    row = next(item for item in parsed["rows"] if item["account"] == "Office occupancy")
    result = compile_trial_balance(
        parsed, request(mappings={row["id"]: "operating_expenses"})
    )
    assert result["ready"]
    assert row["category"] is None
    assert result["statements"]["income_statement"]["net_income"] == 400


def test_subtotals_are_not_double_counted():
    result = compile(SOURCE + b",Grand total,3300,3300,1400,1400\n")
    assert result["ready"]
    assert result["statements"]["income_statement"]["net_income"] == 400
    assert result["warnings"]


def test_missing_confirmation_and_postclosing_rules():
    assert not compile(complete=False)["ready"]
    assert not compile(basis="post_closing")["ready"]
    result = compile(
        b"Account Name,Debit,Credit\nCash,100,0\nRetained earnings,0,100\n",
        basis="post_closing",
    )
    assert result["ready"]
    assert set(result["statements"]) == {"balance_sheet"}
    assert result["statements"]["balance_sheet"]["retained_earnings"] == 100


def test_loss_and_contra_revenue_keep_signs():
    result = compile(
        b"Account Name,Debit,Credit\nCash,50,0\nCapital,0,100\n"
        b"Sales,0,20\nSales returns,10,0\nRent expense,60,0\n"
    )
    assert result["ready"]
    assert result["statements"]["income_statement"]["revenue"] == 10
    assert result["statements"]["income_statement"]["net_income"] == -50
    assert result["statements"]["balance_sheet"]["shareholders_equity"] == 50


def test_decimal_scaling_and_cash_confirmation():
    result = compile(unit_scale="thousands", opening_complete=True, cash=cash())
    assert result["statements"]["income_statement"]["net_income"] == Decimal("400000")
    assert result["statements"]["cash_flow_statement"]["net_change_in_cash"] == 300000
    assert (
        "cash_flow_statement"
        not in compile(opening_complete=True, cash=cash(confirmed=False))["statements"]
    )


def test_fx_is_separate_and_net_change_matches_actual_cash():
    source = SOURCE.replace(b"Cash,800", b"Cash,820").replace(
        b"Retained earnings,0,200", b"Retained earnings,0,220"
    )
    payload = request(opening_complete=True, cash=cash(fx_effect="20"))
    result = compile_trial_balance(
        parse_trial_balance(source, "tb.csv", "text/csv"), payload
    )
    cf = result["statements"]["cash_flow_statement"]
    assert cf["net_change_in_cash"] == 320
    assert cf["operating_cash_flow"] == 500
    assert cf["beginning_cash"] + cf["net_change_in_cash"] == cf["ending_cash"]
    assert not any(
        check.status == "fail" for check in analysis(result, payload, DOCUMENT)[-1]
    )


def test_multi_sheet_requires_selection_and_preserves_row_locations():
    workbook = Workbook()
    for sheet in (workbook.active, workbook.create_sheet("Second")):
        sheet.append(["Account Name", "Debit", "Credit"])
        sheet.append(["Cash", 100, 0])
        sheet.append(["Capital", 0, 100])
    data = BytesIO()
    workbook.save(data)
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    parsed = parse_trial_balance(data.getvalue(), "trial.xlsx", mime)
    assert not parsed["rows"]
    chosen = parse_trial_balance(data.getvalue(), "trial.xlsx", mime, "Second")
    assert chosen["rows"][0]["id"] == "Second!2"
    assert chosen["rows"][0]["source_cell"] == "B2:C2"


def test_shared_analysis_and_excel_are_reconciled():
    payload = request(opening_complete=True, cash=cash())
    result = compile(opening_complete=True, cash=cash())
    statements, ratios, working, flows, checks = analysis(result, payload, DOCUMENT)
    assert not any(check.status == "fail" for check in checks)
    assert (
        next(item for item in ratios if item.metric_name == "gross_margin").value == 60
    )
    output = build_trial_balance_report(
        "Test Co", result, payload, statements, ratios, working, flows, checks
    )
    workbook = load_workbook(BytesIO(output))
    assert "Trial Balance" in workbook.sheetnames
    assert workbook["Trial Balance"].max_row == 15
    assert len(workbook["Charts"]._charts) == 2
    assert workbook["Trial Balance"]["D2"].value == 800
