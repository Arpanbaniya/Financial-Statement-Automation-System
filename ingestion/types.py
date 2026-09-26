"""Common source-preserving structures returned by every ingestion adapter."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

CellValue = str | int | float | bool | date | datetime | time | timedelta | None
FileType = Literal["pdf", "xlsx", "csv"]


@dataclass(frozen=True, slots=True)
class IngestionWarning:
    code: str
    message: str
    location: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    number: int  # One-based page number.
    text: str
    method: str = "pypdf-text"


@dataclass(frozen=True, slots=True)
class ExtractedCell:
    coordinate: str  # XLSX A1 notation or CSV column letter and record number.
    value: CellValue
    data_type: str  # Library source type; no financial conversion is performed.


@dataclass(frozen=True, slots=True)
class ExtractedRow:
    number: int  # XLSX row number or one-based CSV record number.
    cells: tuple[ExtractedCell, ...]
    source_line: int | None = None  # CSV physical line where this record ends.


@dataclass(frozen=True, slots=True)
class ExtractedSheet:
    name: str
    index: int  # One-based workbook order.
    rows: tuple[ExtractedRow, ...]


@dataclass(frozen=True, slots=True)
class ExtractedTable:
    name: str
    source: str  # Sheet name, "CSV", or PDF page label.
    rows: tuple[ExtractedRow, ...]
    headers: tuple[str, ...] = ()
    delimiter: str | None = None
    page_number: int | None = None
    range_reference: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    source_filename: str
    file_type: FileType
    pages: tuple[ExtractedPage, ...]
    sheets: tuple[ExtractedSheet, ...]
    raw_text: str
    tables: tuple[ExtractedTable, ...]
    warnings: tuple[IngestionWarning, ...]
    extraction_method: str
    extraction_version: str
    extraction_status: Literal["extracted", "needs_review"] = "extracted"
    source_encoding: str | None = None
