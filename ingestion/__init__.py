"""Read supported source documents without interpreting their financial meaning."""

from ingestion.errors import IngestionError
from ingestion.reader import ingest_document
from ingestion.types import (
    ExtractedCell,
    ExtractedDocument,
    ExtractedPage,
    ExtractedRow,
    ExtractedSheet,
    ExtractedTable,
    IngestionWarning,
)

__all__ = [
    "ExtractedCell",
    "ExtractedDocument",
    "ExtractedPage",
    "ExtractedRow",
    "ExtractedSheet",
    "ExtractedTable",
    "IngestionError",
    "IngestionWarning",
    "ingest_document",
]
