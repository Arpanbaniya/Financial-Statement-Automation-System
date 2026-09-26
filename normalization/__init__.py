"""Canonical financial fields and source-label mapping."""

from normalization.mapping import (
    MappingEvidence,
    MappingRecord,
    SourceLocation,
    correct_mapping,
    map_label,
    map_table_rows,
    normalize_label_text,
)
from normalization.taxonomy import (
    BALANCE_SHEET_FIELDS,
    CASH_FLOW_FIELDS,
    FIELDS_BY_STATEMENT,
    INCOME_STATEMENT_FIELDS,
    TAXONOMY,
    CanonicalField,
    fields_for_statement,
    get_field,
)

__all__ = [
    "BALANCE_SHEET_FIELDS",
    "CASH_FLOW_FIELDS",
    "FIELDS_BY_STATEMENT",
    "INCOME_STATEMENT_FIELDS",
    "TAXONOMY",
    "CanonicalField",
    "MappingEvidence",
    "MappingRecord",
    "SourceLocation",
    "correct_mapping",
    "fields_for_statement",
    "get_field",
    "map_label",
    "map_table_rows",
    "normalize_label_text",
]
