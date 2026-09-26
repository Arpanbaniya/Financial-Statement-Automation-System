"""Independent quality indicators, complete source traces, and correction events."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from finance import calculate_ratios
from normalization import SourceLocation, map_label, normalize_period
from normalization.taxonomy import FIELDS_BY_STATEMENT
from validation import (
    SourceRef,
    StatementSnapshot,
    ValidationResult,
    ValidationValue,
)
from validation.audit import record_mapping_correction
from validation.quality import data_quality_report, trace_metric

NOW = datetime(2026, 9, 26, tzinfo=UTC)
REVIEWER = "11111111-1111-4111-8111-111111111111"
MAPPING_ID = "22222222-2222-4222-8222-222222222222"


def test_quality_indicators_are_separate_and_missing_is_not_zero() -> None:
    record = map_label(
        "Revenue", "income_statement", source_location=SourceLocation(page=1)
    )
    report = {item.name: item for item in data_quality_report(mappings=(record,))}
    assert report["mapping_completeness"].value == Decimal("0")
    assert report["unresolved_review_items"].value == Decimal("1")
    assert report["source_coverage"].value is None
    assert report["validation_checks_passed"].value is None
    assert len(report) == 6


def test_metric_trace_reaches_original_value_and_location() -> None:
    snapshot = StatementSnapshot(
        id="income",
        company_id="company",
        document_id="doc-1",
        statement_type="income_statement",
        period=normalize_period(
            "income_statement", start="2025-01-01", end="2025-12-31"
        ),
        values=(
            ValidationValue(
                field="revenue",
                normalized_value=Decimal("1000"),
                original_value="1,000",
                source_ref=SourceRef("income", "line-1", SourceLocation(page=2)),
                currency="USD",
                unit_scale="ones",
                status="accepted",
            ),
            ValidationValue(
                field="gross_profit",
                normalized_value=Decimal("400"),
                original_value="400",
                source_ref=SourceRef("income", "line-2", SourceLocation(page=2)),
                currency="USD",
                unit_scale="ones",
                status="accepted",
            ),
        ),
        currency="USD",
        unit_scale="ones",
    )
    ratios = calculate_ratios(income_statement=snapshot, calculated_at=NOW)
    margin = next(item for item in ratios if item.metric_name == "gross_margin")
    trace = trace_metric(margin, (snapshot,))
    assert trace.complete
    assert trace.displayed_value == Decimal("40")
    assert {step.original_value for step in trace.steps} == {"1,000", "400"}
    assert {step.document_id for step in trace.steps} == {"doc-1"}
    assert not trace_metric(margin, ()).complete

    checks = (
        ValidationResult(
            "balance_sheet_equation",
            "pass",
            None,
            None,
            None,
            None,
            "info",
            (),
            "Balanced",
        ),
    )
    report = {
        item.name: item
        for item in data_quality_report(
            statements=(snapshot,),
            validations=checks,
        )
    }
    assert report["source_coverage"].value == Decimal("100")
    assert report["validation_checks_passed"].value == Decimal("100")


def test_review_migration_matches_the_canonical_taxonomy() -> None:
    sql = Path(
        "supabase/migrations/20260926000200_phase21_review_audit.sql"
    ).read_text()
    names = set(
        re.findall(
            r"\('(income_statement|balance_sheet|cash_flow_statement)','([^']+)'\)", sql
        )
    )
    expected = {
        (kind, name) for kind, fields in FIELDS_BY_STATEMENT.items() for name in fields
    }
    assert names == expected
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    assert "auth.uid()" in sql


def test_manual_correction_keeps_original_and_records_before_after() -> None:
    original = map_label(
        "Sales",
        "income_statement",
        source_location=SourceLocation(sheet="FY25", cell="A2"),
    )
    updated, event = record_mapping_correction(
        original,
        mapping_id=MAPPING_ID,
        statement_type="income_statement",
        canonical_field="revenue",
        reviewer_id=REVIEWER,
        reason="Checked against source note",
        reviewed_at=NOW,
    )
    assert original.status == "suggested"
    assert original.source_label == updated.source_label == "Sales"
    assert updated.status == "accepted"
    assert event.previous_value["status"] == "suggested"
    assert event.new_value["canonical_field"] == "revenue"
    assert event.user_id == REVIEWER
    assert event.reason == "Checked against source note"
    with pytest.raises(ValueError, match="reason"):
        record_mapping_correction(
            original,
            mapping_id=MAPPING_ID,
            statement_type="income_statement",
            canonical_field="revenue",
            reviewer_id=REVIEWER,
            reason=" ",
            reviewed_at=NOW,
        )
