"""Keep the published canonical field inventory complete and unambiguous."""

from dataclasses import FrozenInstanceError

import pytest

from normalization import FIELDS_BY_STATEMENT, TAXONOMY, fields_for_statement, get_field

EXPECTED = {
    "income_statement": {
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "research_and_development",
        "selling_general_administrative",
        "operating_expenses",
        "operating_income",
        "interest_income",
        "interest_expense",
        "other_income_expense",
        "income_before_tax",
        "income_tax",
        "net_income",
    },
    "balance_sheet": {
        "cash_and_cash_equivalents",
        "short_term_investments",
        "accounts_receivable",
        "inventory",
        "other_current_assets",
        "total_current_assets",
        "property_plant_equipment",
        "goodwill",
        "intangible_assets",
        "other_noncurrent_assets",
        "total_assets",
        "accounts_payable",
        "short_term_debt",
        "other_current_liabilities",
        "total_current_liabilities",
        "long_term_debt",
        "other_noncurrent_liabilities",
        "total_liabilities",
        "common_stock",
        "retained_earnings",
        "accumulated_other_comprehensive_income",
        "treasury_stock",
        "shareholders_equity",
    },
    "cash_flow_statement": {
        "net_income",
        "depreciation_amortization",
        "stock_based_compensation",
        "change_in_receivables",
        "change_in_inventory",
        "change_in_payables",
        "operating_cash_flow",
        "capital_expenditure",
        "acquisitions",
        "investing_cash_flow",
        "debt_issuance",
        "debt_repayment",
        "dividends",
        "share_repurchases",
        "financing_cash_flow",
        "net_change_in_cash",
    },
}


def test_inventory_matches_all_three_planned_statements() -> None:
    assert len(TAXONOMY) == 52
    assert set(FIELDS_BY_STATEMENT) == set(EXPECTED)
    for statement_type, expected_names in EXPECTED.items():
        fields = fields_for_statement(statement_type)
        assert {field.machine_name for field in fields} == expected_names
        assert len(fields) == len(expected_names)
        assert all(field.statement_type == statement_type for field in fields)


def test_every_field_has_useful_metadata_and_period_basis() -> None:
    for field in TAXONOMY:
        assert field.machine_name and field.display_name
        assert field.definition and field.sign_convention
        assert field.aliases and all(alias.strip() for alias in field.aliases)
        assert isinstance(field.required, bool)
        assert field.period_basis == (
            "instant" if field.statement_type == "balance_sheet" else "duration"
        )
        assert field.machine_name == field.machine_name.lower()


def test_required_fields_and_sign_conventions_are_explicit() -> None:
    required = {
        statement_type: {
            field.machine_name
            for field in fields_for_statement(statement_type)
            if field.required
        }
        for statement_type in EXPECTED
    }
    assert required == {
        "income_statement": {"revenue", "net_income"},
        "balance_sheet": {
            "total_assets",
            "total_liabilities",
            "shareholders_equity",
        },
        "cash_flow_statement": {
            "operating_cash_flow",
            "investing_cash_flow",
            "financing_cash_flow",
            "net_change_in_cash",
        },
    }
    assert (
        "Negative"
        in get_field("cash_flow_statement", "capital_expenditure").sign_convention
    )
    assert "Negative" in get_field("balance_sheet", "treasury_stock").sign_convention
    assert (
        "Increase"
        in get_field("cash_flow_statement", "change_in_receivables").sign_convention
    )


def test_lookup_is_scoped_exact_and_immutable() -> None:
    income = get_field("income_statement", "net_income")
    cash_flow = get_field("cash_flow_statement", "net_income")
    assert income is not cash_flow
    assert income.definition != cash_flow.definition
    with pytest.raises(KeyError):
        get_field("income_statement", "Net earnings")
    with pytest.raises(TypeError):
        FIELDS_BY_STATEMENT["income_statement"]["made_up"] = income
    with pytest.raises(FrozenInstanceError):
        income.display_name = "Changed"
