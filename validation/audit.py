"""Immutable manual correction records for persistence in audit_events."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from normalization.mapping import MappingRecord, correct_mapping
from normalization.taxonomy import StatementType


@dataclass(frozen=True, slots=True)
class AuditEvent:
    action: str
    user_id: str
    occurred_at: datetime
    entity_type: str
    entity_id: str
    previous_value: dict[str, Any]
    new_value: dict[str, Any]
    reason: str


def record_mapping_correction(
    record: MappingRecord,
    *,
    mapping_id: str,
    statement_type: StatementType,
    canonical_field: str,
    reviewer_id: str,
    reason: str,
    reviewed_at: datetime,
) -> tuple[MappingRecord, AuditEvent]:
    """Return a corrected mapping and an event; leave the source record intact."""
    if not reason.strip():
        raise ValueError("A correction reason is required")
    try:
        entity_id = str(UUID(mapping_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Mapping ID must be a UUID") from exc
    corrected = correct_mapping(
        record,
        statement_type=statement_type,
        canonical_field=canonical_field,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
    )
    event = AuditEvent(
        action="mapping_corrected",
        user_id=corrected.reviewer_id or reviewer_id,
        occurred_at=corrected.reviewed_at or reviewed_at.astimezone(UTC),
        entity_type="line_item_mapping",
        entity_id=entity_id,
        previous_value={
            "canonical_field": record.canonical_field,
            "status": record.status,
            "source_label": record.source_label,
        },
        new_value={
            "canonical_field": corrected.canonical_field,
            "status": corrected.status,
            "source_label": corrected.source_label,
        },
        reason=reason.strip(),
    )
    return corrected, event
