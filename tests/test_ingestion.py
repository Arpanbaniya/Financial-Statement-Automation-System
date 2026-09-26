"""Check that each adapter keeps source values and reports recoverable problems."""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import Workbook
from pypdf import PdfWriter

from ingestion import IngestionError, ingest_document

FIXTURES = Path(__file__).parent / "fixtures"


def pdf_with_stream(stream: bytes) -> bytes:
    """Build a small PDF fixture from a drawing stream."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_start = len(content)
    content.extend(f"xref\n0 {len(offsets)}\n".encode())
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    trailer = (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF"
    )
    content.extend(trailer.encode())
    return bytes(content)


def pdf_with_text(text: str) -> bytes:
    return pdf_with_stream(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())


def pdf_with_table() -> bytes:
    stream = b"\n".join(
        [
            b"BT /F1 12 Tf 80 740 Td (Year) Tj ET",
            b"BT /F1 12 Tf 200 740 Td (Revenue) Tj ET",
            b"BT /F1 12 Tf 80 710 Td (2025) Tj ET",
            b"BT /F1 12 Tf 200 710 Td (100) Tj ET",
            b"0.5 w",
            b"70 700 m 300 700 l S",
            b"70 730 m 300 730 l S",
            b"70 760 m 300 760 l S",
            b"70 700 m 70 760 l S",
            b"180 700 m 180 760 l S",
            b"300 700 m 300 760 l S",
        ]
    )
    return pdf_with_stream(stream)


def workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Income statement"
    sheet["A1"] = "Revenue"
    sheet["B1"] = 100
    sheet["B2"] = "=B1-40"
    sheet["A5"] = "Separate section"
    workbook.create_sheet("Notes")["C3"] = "Source note"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_csv_preserves_text_delimiter_records_and_lines() -> None:
    source = (FIXTURES / "sample_statement.csv").read_bytes()
    original = bytes(source)
    result = ingest_document(source, filename="statement.csv", mime_type="text/csv")

    assert source == original
    assert result.file_type == "csv"
    assert result.raw_text == source.decode("utf-8")
    assert result.tables[0].delimiter == ";"
    assert result.tables[0].headers == ("Item", "2025", "2024")
    assert result.tables[0].rows[2].cells[0].value == "Cost of\nsales"
    assert result.tables[0].rows[2].source_line == 4
    assert result.tables[0].rows[1].cells[1].coordinate == "B2"
    assert result.extraction_method == "python-csv"
    assert result.extraction_version
    assert result.source_encoding == "utf-8"


def test_csv_reports_irregular_rows_and_bad_encoding() -> None:
    result = ingest_document(b"A,B\n1\n", filename="odd.csv")
    assert any(warning.code == "COLUMN_COUNT_MISMATCH" for warning in result.warnings)
    with pytest.raises(IngestionError, match="encoding") as error:
        ingest_document(b"\xff\xfe\x00", filename="old.csv")
    assert error.value.code == "UNSUPPORTED_ENCODING"


def test_csv_handles_bom_legacy_encoding_and_binary_data() -> None:
    utf16 = ingest_document(
        "Name;Amount\nCafé;10\n".encode("utf-16"), filename="utf16.csv"
    )
    assert utf16.source_encoding == "utf-16"
    assert utf16.tables[0].delimiter == ";"
    assert utf16.tables[0].rows[1].cells[0].value == "Café"

    legacy = ingest_document(b"Name,Amount\nCaf\xe9,10\n", filename="legacy.csv")
    assert legacy.source_encoding == "cp1252"
    assert legacy.tables[0].rows[1].cells[0].value == "Café"
    assert any(warning.code == "LEGACY_ENCODING" for warning in legacy.warnings)

    with pytest.raises(IngestionError) as error:
        ingest_document(b"A,B\n1,\x00\n", filename="binary.csv")
    assert error.value.code == "UNSUPPORTED_ENCODING"


def test_xlsx_preserves_sheet_cell_coordinates_types_and_formulas() -> None:
    source = workbook_bytes()
    original = bytes(source)
    result = ingest_document(source, filename="statement.xlsx")

    assert source == original
    assert result.file_type == "xlsx"
    assert [sheet.name for sheet in result.sheets] == ["Income statement", "Notes"]
    first_row = result.sheets[0].rows[0]
    assert first_row.cells[0].coordinate == "A1"
    assert first_row.cells[1].value == 100
    assert result.sheets[0].rows[1].cells[0].value == "=B1-40"
    assert result.sheets[0].rows[1].cells[0].data_type == "f"
    assert result.sheets[1].rows[0].cells[0].coordinate == "C3"
    assert [table.range_reference for table in result.tables] == [
        "A1:B2",
        "A5:A5",
        "C3:C3",
    ]
    assert result.extraction_method == "openpyxl-read-only"
    assert result.extraction_version


def test_pdf_keeps_page_text_and_warns_for_image_only_page() -> None:
    text_result = ingest_document(pdf_with_text("Revenue 100"), filename="text.pdf")
    assert text_result.pages[0].number == 1
    assert "Revenue 100" in text_result.pages[0].text
    assert text_result.raw_text == text_result.pages[0].text
    assert text_result.extraction_method == "pypdf+pdfplumber"
    assert text_result.extraction_version

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    blank_result = ingest_document(output.getvalue(), filename="scan.pdf")
    assert blank_result.pages[0].text == ""
    assert blank_result.warnings[0].code == "NO_EXTRACTABLE_TEXT"
    assert blank_result.extraction_status == "needs_review"
    assert any(warning.code == "OCR_UNSUPPORTED" for warning in blank_result.warnings)


def test_pdf_attempts_tables_and_keeps_page_provenance() -> None:
    result = ingest_document(pdf_with_table(), filename="table.pdf")
    assert result.extraction_status == "extracted"
    assert result.tables[0].page_number == 1
    assert result.tables[0].rows[0].cells[1].value == "Revenue"
    assert result.tables[0].rows[1].cells[1].value == "100"


def test_encrypted_pdf_has_a_clear_failure_code() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("example-password")
    output = BytesIO()
    writer.write(output)
    with pytest.raises(IngestionError) as error:
        ingest_document(output.getvalue(), filename="locked.pdf")
    assert error.value.code == "ENCRYPTED_PDF"


def test_xlsx_archive_expansion_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    import ingestion.limits as limits

    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("large.xml", b"x" * 101)
    monkeypatch.setattr(limits, "MAX_UNCOMPRESSED_XLSX_BYTES", 100)
    with pytest.raises(IngestionError) as error:
        ingest_document(output.getvalue(), filename="large.xlsx")
    assert error.value.code == "DOCUMENT_TOO_COMPLEX"


@pytest.mark.parametrize(
    ("source", "filename", "code"),
    [
        (b"", "file.pdf", "EMPTY_SOURCE"),
        (b"hello", "file.exe", "UNSUPPORTED_FILE_TYPE"),
        (b"hello", "file.pdf", "INVALID_PDF"),
        (b"PKbad", "file.xlsx", "INVALID_XLSX"),
        (b"x", "../file.csv", "INVALID_FILENAME"),
    ],
)
def test_invalid_sources_have_stable_error_codes(
    source: bytes, filename: str, code: str
) -> None:
    with pytest.raises(IngestionError) as error:
        ingest_document(source, filename=filename)
    assert error.value.code == code


def test_mime_mismatch_is_rejected() -> None:
    with pytest.raises(IngestionError) as error:
        ingest_document(b"a,b\n", filename="data.csv", mime_type="application/pdf")
    assert error.value.code == "MIME_MISMATCH"
