"""Canonical financial fields, source mapping, and metadata normalization."""

from normalization.amounts import (
    NormalizationWarning,
    NormalizedAmount,
    normalize_amount,
)
from normalization.mapping import (
    MappingEvidence,
    MappingRecord,
    SourceLocation,
    correct_mapping,
    map_label,
    map_table_rows,
    normalize_label_text,
)
from normalization.periods import NormalizedPeriod, normalize_period
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
    "NormalizationWarning",
    "NormalizedAmount",
    "NormalizedPeriod",
    "SourceLocation",
    "correct_mapping",
    "fields_for_statement",
    "get_field",
    "map_label",
    "map_table_rows",
    "normalize_label_text",
    "normalize_amount",
    "normalize_period",
]
