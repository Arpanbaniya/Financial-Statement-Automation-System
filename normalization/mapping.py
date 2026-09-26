"""Conservative source-label mapping with explicit manual correction."""

import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from ingestion.types import ExtractedTable
from normalization.taxonomy import FIELDS_BY_STATEMENT, StatementType, get_field

DetectedType = StatementType | Literal["unknown"]
MappingMethod = Literal["exact_alias", "normalized_alias", "manual", "unmapped"]
MappingStatus = Literal["suggested", "needs_review", "accepted"]
ReviewReason = Literal[
    "ambiguous_label", "unmatched_label", "unknown_statement", "empty_label"
]
MAX_MATCH_LABEL_CHARS = 500


@dataclass(frozen=True, slots=True)
class SourceLocation:
    page: int | None = None
    sheet: str | None = None
    cell: str | None = None
    table: str | None = None
    row: int | None = None
    line: int | None = None

    def __post_init__(self) -> None:
        if any(
            value is not None and value < 1
            for value in (self.page, self.row, self.line)
        ):
            raise ValueError("Source page, row, and line numbers must be positive")


@dataclass(frozen=True, slots=True)
class MappingEvidence:
    method: MappingMethod
    matched_alias: str | None
    compared_text: str | None
    candidate_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MappingRecord:
    source_label: str
    statement_type: DetectedType
    canonical_field: str | None
    method: MappingMethod
    confidence: float
    status: MappingStatus
    reviewer_id: str | None
    reviewed_at: datetime | None
    source_location: SourceLocation
    evidence: tuple[MappingEvidence, ...]
    review_reason: ReviewReason | None
    candidate_fields: tuple[str, ...]


def normalize_label_text(label: str) -> str:
    """Fold case and harmless punctuation while keeping every word."""
    text = unicodedata.normalize("NFKC", label).casefold()
    text = text.replace("&", " and ")
    text = text.replace("’", "").replace("'", "")
    text = "".join(
        " " if unicodedata.category(char).startswith("P") else char for char in text
    )
    return " ".join(text.replace("_", " ").split())


def _index(normalized: bool) -> MappingProxyType:
    index: dict[StatementType, dict[str, list[tuple[str, str]]]] = {}
    for statement_type, fields in FIELDS_BY_STATEMENT.items():
        labels: dict[str, list[tuple[str, str]]] = {}
        for field in fields.values():
            for alias in (field.display_name, *field.aliases):
                key = normalize_label_text(alias) if normalized else alias
                labels.setdefault(key, []).append((field.machine_name, alias))
        index[statement_type] = labels
    return MappingProxyType(index)


_EXACT_INDEX = _index(False)
_NORMALIZED_INDEX = _index(True)


def _candidates(matches: list[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(sorted({machine_name for machine_name, _ in matches}))


def _review(
    label: str,
    statement_type: DetectedType,
    location: SourceLocation,
    reason: ReviewReason,
    candidates: tuple[str, ...] = (),
    evidence: tuple[MappingEvidence, ...] = (),
) -> MappingRecord:
    if not evidence:
        evidence = (
            MappingEvidence(
                "unmapped",
                None,
                normalize_label_text(label[:MAX_MATCH_LABEL_CHARS]),
                candidates,
            ),
        )
    return MappingRecord(
        source_label=label,
        statement_type=statement_type,
        canonical_field=None,
        method="unmapped",
        confidence=0.0,
        status="needs_review",
        reviewer_id=None,
        reviewed_at=None,
        source_location=location,
        evidence=evidence,
        review_reason=reason,
        candidate_fields=candidates,
    )


def map_label(
    source_label: str,
    statement_type: DetectedType,
    *,
    source_location: SourceLocation,
) -> MappingRecord:
    """Suggest one exact or normalized alias; never guess from a partial phrase."""
    if not isinstance(source_label, str):
        raise TypeError("Source label must be text")
    if not source_label.strip():
        return _review(source_label, statement_type, source_location, "empty_label")
    if len(source_label) > MAX_MATCH_LABEL_CHARS:
        return _review(source_label, statement_type, source_location, "unmatched_label")
    if statement_type == "unknown":
        return _review(
            source_label, statement_type, source_location, "unknown_statement"
        )
    if statement_type not in FIELDS_BY_STATEMENT:
        raise ValueError("Unsupported statement type")

    for method, key, index, confidence in (
        ("exact_alias", source_label, _EXACT_INDEX, 0.97),
        (
            "normalized_alias",
            normalize_label_text(source_label),
            _NORMALIZED_INDEX,
            0.90,
        ),
    ):
        matches = index[statement_type].get(key, [])
        if not matches:
            continue
        candidates = _candidates(matches)
        evidence = tuple(
            MappingEvidence(method, alias, key, candidates)
            for _, alias in dict.fromkeys(matches)
        )
        if len(candidates) > 1:
            return _review(
                source_label,
                statement_type,
                source_location,
                "ambiguous_label",
                candidates,
                evidence,
            )
        return MappingRecord(
            source_label=source_label,
            statement_type=statement_type,
            canonical_field=candidates[0],
            method=method,
            confidence=confidence,
            status="suggested",
            reviewer_id=None,
            reviewed_at=None,
            source_location=source_location,
            evidence=evidence,
            review_reason=None,
            candidate_fields=candidates,
        )

    key = normalize_label_text(source_label)
    generic = key in {
        "other",
        "others",
        "other assets",
        "other liabilities",
        "other income",
        "other expenses",
        "miscellaneous",
        "total",
    }
    if generic:
        candidates = tuple(
            name
            for name in FIELDS_BY_STATEMENT[statement_type]
            if name.startswith("other_")
            and (
                key in {"other", "others", "miscellaneous", "total"}
                or ("assets" in key and name.endswith("assets"))
                or ("liabilities" in key and name.endswith("liabilities"))
                or ("income" in key and "income" in name)
                or ("expenses" in key and "expense" in name)
            )
        )
        return _review(
            source_label,
            statement_type,
            source_location,
            "ambiguous_label",
            candidates,
        )
    return _review(source_label, statement_type, source_location, "unmatched_label")


def map_table_rows(
    table: ExtractedTable, statement_type: DetectedType
) -> tuple[MappingRecord, ...]:
    """Map the first textual cell of each row and keep its source coordinates."""
    records: list[MappingRecord] = []
    for row in table.rows:
        label_cell = next(
            (
                cell
                for cell in row.cells
                if isinstance(cell.value, str) and cell.value.strip()
            ),
            None,
        )
        if label_cell is None:
            continue
        records.append(
            map_label(
                label_cell.value,
                statement_type,
                source_location=SourceLocation(
                    page=table.page_number,
                    sheet=(
                        table.source
                        if table.page_number is None and table.source != "CSV"
                        else None
                    ),
                    cell=label_cell.coordinate,
                    table=table.name,
                    row=row.number,
                    line=row.source_line,
                ),
            )
        )
    return tuple(records)


def correct_mapping(
    record: MappingRecord,
    *,
    statement_type: StatementType,
    canonical_field: str,
    reviewer_id: str,
    reviewed_at: datetime | None = None,
) -> MappingRecord:
    """Return a new accepted record, leaving the source and old record intact."""
    get_field(statement_type, canonical_field)
    try:
        reviewer = str(UUID(reviewer_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Reviewer ID must be a UUID") from exc
    timestamp = reviewed_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Review timestamp must include a time zone")
    return replace(
        record,
        statement_type=statement_type,
        canonical_field=canonical_field,
        method="manual",
        confidence=1.0,
        status="accepted",
        reviewer_id=reviewer,
        reviewed_at=timestamp.astimezone(UTC),
        evidence=(
            *record.evidence,
            MappingEvidence("manual", None, None, (canonical_field,)),
        ),
        review_reason=None,
        candidate_fields=(canonical_field,),
    )
