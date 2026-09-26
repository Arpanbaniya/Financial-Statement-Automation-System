"""Immutable input snapshots and structured reconciliation results."""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from normalization.mapping import SourceLocation
from normalization.periods import NormalizedPeriod
from normalization.taxonomy import FIELDS_BY_STATEMENT, StatementType

ValidationStatus = Literal["pass", "warning", "fail", "unavailable"]
Severity = Literal["info", "warning", "error"]
ValueStatus = Literal["accepted", "suggested", "needs_review"]
_CASH_ANCHORS = {"beginning_cash", "ending_cash"}
_UNITS = {"ones", "thousands", "millions", "billions"}


@dataclass(frozen=True, slots=True)
class SourceRef:
    statement_id: str
    line_item_id: str | None = None
    location: SourceLocation = field(default_factory=SourceLocation)


@dataclass(frozen=True, slots=True)
class ValidationValue:
    """A mapped value already scaled to ones; only accepted values drive arithmetic."""

    field: str
    normalized_value: Decimal | None
    source_ref: SourceRef
    currency: str | None = None
    unit_scale: str | None = None
    original_value: str | None = None
    status: ValueStatus = "suggested"

    def __post_init__(self) -> None:
        if not self.field:
            raise ValueError("A value needs a canonical field")
        if self.normalized_value is not None and (
            not isinstance(self.normalized_value, Decimal)
            or not self.normalized_value.is_finite()
        ):
            raise ValueError("Normalized values must be finite Decimal amounts")
        if self.currency is not None and not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("Currency must be an uppercase three-letter code")
        if self.unit_scale is not None and self.unit_scale not in _UNITS:
            raise ValueError("Unknown unit scale")
        if self.status not in {"accepted", "suggested", "needs_review"}:
            raise ValueError("Unknown value review status")


@dataclass(frozen=True, slots=True)
class StatementSnapshot:
    id: str
    company_id: str
    document_id: str
    statement_type: StatementType
    period: NormalizedPeriod
    values: tuple[ValidationValue, ...]
    currency: str | None = None
    unit_scale: str | None = None
    current_assets_components_complete: bool = False
    current_liabilities_components_complete: bool = False
    operating_expenses_exclude_cost: bool = False
    cash_flow_components_complete: bool = False

    def __post_init__(self) -> None:
        if not self.id or not self.company_id or not self.document_id:
            raise ValueError("Statement, company, and document IDs are required")
        if self.statement_type not in FIELDS_BY_STATEMENT:
            raise ValueError("Unknown statement type")
        if self.period.statement_type != self.statement_type:
            raise ValueError("Period and statement types must agree")
        if self.currency is not None and not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("Currency must be an uppercase three-letter code")
        if self.unit_scale is not None and self.unit_scale not in _UNITS:
            raise ValueError("Unknown unit scale")
        allowed = set(FIELDS_BY_STATEMENT[self.statement_type])
        if self.statement_type == "cash_flow_statement":
            allowed |= _CASH_ANCHORS
        for value in self.values:
            if value.source_ref.statement_id != self.id:
                raise ValueError("A value source must belong to its statement")
            if value.field not in allowed:
                raise ValueError(
                    f"Unknown field for {self.statement_type}: {value.field}"
                )


@dataclass(frozen=True, slots=True)
class TolerancePolicy:
    absolute: Decimal = Decimal("1")
    relative: Decimal = Decimal("0.000001")

    def __post_init__(self) -> None:
        for value in (self.absolute, self.relative):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError("Tolerances must be finite nonnegative Decimals")

    def for_values(self, expected: Decimal, actual: Decimal) -> Decimal:
        return max(self.absolute, self.relative * max(abs(expected), abs(actual)))


@dataclass(frozen=True, slots=True)
class ValidationResult:
    check_name: str
    status: ValidationStatus
    expected_value: Decimal | None
    actual_value: Decimal | None
    difference: Decimal | None
    tolerance: Decimal | None
    severity: Severity
    source_refs: tuple[SourceRef, ...]
    explanation: str
    statement_id: str | None = None
