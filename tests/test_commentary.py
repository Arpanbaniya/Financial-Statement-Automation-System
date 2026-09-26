"""Commentary stays factual and only uses calculated source-linked values."""

from datetime import UTC, datetime
from decimal import Decimal

from finance import calculate_horizontal, calculate_ratios, generate_commentary
from normalization import SourceLocation, normalize_period
from validation import SourceRef, StatementSnapshot, ValidationValue

NOW = datetime(2026, 9, 26, tzinfo=UTC)


def income(
    statement_id: str, year: int, revenue: str, operating: str
) -> StatementSnapshot:
    return StatementSnapshot(
        id=statement_id,
        company_id="company",
        document_id=f"doc-{statement_id}",
        statement_type="income_statement",
        period=normalize_period(
            "income_statement", start=f"{year}-01-01", end=f"{year}-12-31"
        ),
        values=tuple(
            ValidationValue(
                field=field,
                normalized_value=Decimal(amount),
                source_ref=SourceRef(statement_id, field, SourceLocation(page=1)),
                currency="USD",
                unit_scale="ones",
                status="accepted",
            )
            for field, amount in (("revenue", revenue), ("operating_income", operating))
        ),
        currency="USD",
        unit_scale="ones",
    )


def test_observed_growth_and_margin_changes_have_values_and_sources() -> None:
    earlier = income("old", 2024, "1000", "200")
    current = income("new", 2025, "1124", "187.36")
    growth = calculate_horizontal((earlier, current), calculated_at=NOW)
    current_ratios = calculate_ratios(income_statement=current, calculated_at=NOW)
    earlier_ratios = calculate_ratios(income_statement=earlier, calculated_at=NOW)
    findings = generate_commentary(
        horizontal=growth,
        current_ratios=current_ratios,
        previous_ratios=earlier_ratios,
    )
    assert any(
        "Revenue increased 12.4% from 1,000.0 to 1,124.0" in item.text
        for item in findings
    )
    assert any(
        "Operating margin decreased from 20.0% to 16.7%" in item.text
        for item in findings
    )
    assert all(item.source_refs for item in findings)
    assert all(item.kind == "observation" for item in findings)
    assert not any(
        "good" in item.text.lower() or "bad" in item.text.lower() for item in findings
    )


def test_missing_comparison_produces_no_claim() -> None:
    current = income("new", 2025, "1124", "187.36")
    growth = calculate_horizontal((current,), calculated_at=NOW)
    assert generate_commentary(horizontal=growth) == ()
