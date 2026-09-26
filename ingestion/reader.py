"""Validate a source and dispatch it to the matching extraction adapter."""

from pathlib import PurePath

from extraction.csv_file import extract_csv
from extraction.pdf import extract_pdf
from extraction.xlsx import extract_xlsx
from ingestion.errors import IngestionError
from ingestion.limits import MAX_SOURCE_BYTES
from ingestion.types import ExtractedDocument, FileType


def ingest_document(
    source: bytes, *, filename: str, mime_type: str | None = None
) -> ExtractedDocument:
    """Read source bytes without changing the original or interpreting its figures."""
    if not isinstance(source, bytes):
        raise IngestionError("INVALID_SOURCE", "Source must be bytes")
    if not source:
        raise IngestionError("EMPTY_SOURCE", "The source file is empty")
    if len(source) > MAX_SOURCE_BYTES:
        raise IngestionError("SOURCE_TOO_LARGE", "The source exceeds 10 MB")
    if (
        not filename
        or len(filename) > 255
        or "/" in filename
        or "\\" in filename
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)
    ):
        raise IngestionError("INVALID_FILENAME", "A plain source filename is required")

    extension = PurePath(filename).suffix.lower()
    file_type: FileType
    if extension == ".pdf":
        file_type = "pdf"
        allowed_mimes = {"application/pdf"}
    elif extension == ".xlsx":
        file_type = "xlsx"
        allowed_mimes = {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        }
    elif extension == ".csv":
        file_type = "csv"
        allowed_mimes = {"text/csv", "application/csv", "application/vnd.ms-excel"}
    else:
        raise IngestionError(
            "UNSUPPORTED_FILE_TYPE", "Only PDF, XLSX, and CSV are supported"
        )
    if mime_type is not None and mime_type not in allowed_mimes:
        raise IngestionError("MIME_MISMATCH", "MIME type does not match the filename")

    if file_type == "pdf":
        return extract_pdf(source, filename)
    if file_type == "xlsx":
        return extract_xlsx(source, filename)
    return extract_csv(source, filename)
