"""Separate data-quality indicators and traceability checks, without a score."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from finance.detection import StatementDetection
from finance.ratios import MetricInput
from normalization.mapping import MappingRecord
from normalization.taxonomy import fields_for_statement
from validation.types import SourceRef, StatementSnapshot, ValidationResult

IndicatorUnit = Literal["percent", "count"]


@dataclass(frozen=True, slots=True)
class QualityIndicator:
    name: str
    value: Decimal | None
    unit: IndicatorUnit
    numerator: int | None
    denominator: int | None
    explanation: str


@dataclass(frozen=True, slots=True)
class TraceStep:
    document_id: str
    statement_id: str
    canonical_field: str
    normalized_value: Decimal
    original_value: str | None
    source_ref: SourceRef


@dataclass(frozen=True, slots=True)
class MetricTrace:
    metric_name: str
    formula_id: str
    displayed_value: Decimal | None
    steps: tuple[TraceStep, ...]
    complete: bool
    missing_inputs: tuple[str, ...]


def _percent(
    name: str, numerator: int, denominator: int, explanation: str
) -> QualityIndicator:
    return QualityIndicator(
        name,
        Decimal(numerator) / Decimal(denominator) * 100 if denominator else None,
        "percent",
        numerator,
        denominator,
        explanation,
    )


def data_quality_report(
    *,
    detections: tuple[StatementDetection, ...] = (),
    mappings: tuple[MappingRecord, ...] = (),
    statements: tuple[StatementSnapshot, ...] = (),
    validations: tuple[ValidationResult, ...] = (),
    open_manual_reviews: int = 0,
) -> tuple[QualityIndicator, ...]:
    """Report independent indicators; never collapse them into a universal score."""
    if open_manual_reviews < 0:
        raise ValueError("Open review count cannot be negative")
    recognized = tuple(item for item in detections if item.statement_type != "unknown")
    confidence = (
        sum((Decimal(str(item.confidence)) for item in recognized), Decimal(0))
        / Decimal(len(recognized))
        * 100
        if recognized
        else None
    )
    required = tuple(
        (statement, field.machine_name)
        for statement in statements
        for field in fields_for_statement(statement.statement_type)
        if field.required
    )
    required_present = sum(
        any(
            value.field == field
            and value.status == "accepted"
            and value.normalized_value is not None
            for value in statement.values
        )
        for statement, field in required
    )
    applicable = tuple(item for item in validations if item.status != "unavailable")
    accepted = tuple(
        value
        for statement in statements
        for value in statement.values
        if value.status == "accepted" and value.normalized_value is not None
    )
    with_source = sum(
        value.original_value is not None
        and (
            value.source_ref.location.page is not None
            or value.source_ref.location.cell is not None
            or value.source_ref.location.line is not None
            or value.source_ref.location.row is not None
        )
        for value in accepted
    )
    unresolved = (
        sum(item.status != "accepted" for item in mappings) + open_manual_reviews
    )
    return (
        QualityIndicator(
            "statement_detection_confidence",
            confidence,
            "percent",
            None,
            len(recognized) if recognized else None,
            "Mean rule confidence of recognized statement regions; not a probability.",
        ),
        _percent(
            "mapping_completeness",
            sum(item.status == "accepted" for item in mappings),
            len(mappings),
            "Accepted mappings among mapped rows.",
        ),
        _percent(
            "required_field_completeness",
            required_present,
            len(required),
            "Accepted core fields among core fields for supplied statements.",
        ),
        _percent(
            "validation_checks_passed",
            sum(item.status == "pass" for item in applicable),
            len(applicable),
            "Passed checks among applicable checks.",
        ),
        QualityIndicator(
            "unresolved_review_items",
            Decimal(unresolved),
            "count",
            unresolved,
            None,
            "Mappings awaiting acceptance plus open manual reviews.",
        ),
        _percent(
            "source_coverage",
            with_source,
            len(accepted),
            "Accepted values with original text and page, cell, row, or line.",
        ),
    )


def trace_metric(
    metric: object, statements: tuple[StatementSnapshot, ...]
) -> MetricTrace:
    """Verify each calculation input against its original extracted value."""
    by_id = {statement.id: statement for statement in statements}
    steps: list[TraceStep] = []
    missing: list[str] = []
    for item in metric.inputs:
        assert isinstance(item, MetricInput)
        statement = by_id.get(item.statement_id)
        field = item.name.split(".", 1)[-1]
        if statement is None:
            missing.append(item.name)
            continue
        if not item.source_refs:
            missing.append(item.name)
            continue
        for ref in item.source_refs:
            matches = tuple(
                value
                for value in statement.values
                if value.field == field
                and value.status == "accepted"
                and value.normalized_value == item.value
                and value.source_ref == ref
            )
            location = ref.location
            has_location = any(
                value is not None
                for value in (location.page, location.cell, location.line, location.row)
            )
            if (
                len(matches) != 1
                or matches[0].original_value is None
                or not has_location
            ):
                missing.append(item.name)
                continue
            steps.append(
                TraceStep(
                    statement.document_id,
                    statement.id,
                    field,
                    item.value,
                    matches[0].original_value,
                    ref,
                )
            )
    return MetricTrace(
        metric.metric_name,
        metric.formula_id,
        metric.value,
        tuple(steps),
        metric.status == "calculated" and bool(metric.inputs) and not missing,
        tuple(dict.fromkeys(missing)),
    )
