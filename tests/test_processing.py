"""Small source documents with amounts that can be checked by hand."""

from datetime import date
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfWriter

from api import processing
from api.documents import _user_id
from api.index import app
from api.processing import ProcessRequest, _records


def request(column: str = "B") -> ProcessRequest:
    return ProcessRequest(
        company_id=uuid4(),
        period_start="2025-01-01",
        period_end="2025-12-31",
        currency="USD",
        unit_scale="ones",
        value_column=column,
    )


def test_csv_pipeline_preserves_source_and_uses_selected_period_column() -> None:
    source = (
        b"Item,2025,2024\nRevenue,1000,900\nCost of goods sold,600,500\n"
        b"Gross profit,400,400\nOperating expenses,200,180\n"
        b"Operating income,200,220\nNet income,135,150\n"
    )
    statements, unresolved = _records(source, "golden.csv", "text/csv", request())
    assert not unresolved
    assert len(statements) == 1
    statement = statements[0]
    assert statement["status"] == "accepted"
    values = {line["canonical_name"]: line for line in statement["lines"]}
    assert values["revenue"]["normalized_value"] == "1000"
    assert values["cost_of_revenue"]["normalized_value"] == "600"
    assert values["gross_profit"]["normalized_value"] == "400"
    assert values["net_income"]["source_cell"] == "B7"
    previous, _ = _records(source, "golden.csv", "text/csv", request("C"))
    assert previous[0]["lines"][0]["normalized_value"] == "900"


def test_unknown_and_ambiguous_rows_do_not_become_accepted() -> None:
    source = b"Item,Amount\nRevenue,100\nOther,40\nCost of goods sold,60\n"
    statements, unresolved = _records(source, "review.csv", "text/csv", request())
    assert unresolved
    assert statements[0]["status"] == "needs_review"
    assert any(
        line["review_status"] == "needs_review" for line in statements[0]["lines"]
    )


def test_xlsx_pipeline_and_textless_pdf_are_handled_without_guessing() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Income Statement"
    sheet.append(["Item", "Amount"])
    sheet.append(["Revenue", 1000])
    sheet.append(["Cost of goods sold", 600])
    sheet.append(["Gross profit", 400])
    output = BytesIO()
    workbook.save(output)
    statements, unresolved = _records(
        output.getvalue(),
        "golden.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        request(),
    )
    assert not unresolved
    assert statements[0]["lines"][0]["source_sheet"] == "Income Statement"
    assert statements[0]["lines"][0]["normalized_value"] == "1000"

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    pdf = BytesIO()
    writer.write(pdf)
    statements, unresolved = _records(
        pdf.getvalue(),
        "scan.pdf",
        "application/pdf",
        request(),
    )
    assert statements == []
    assert unresolved


def test_committed_demo_statement_has_hand_checked_income_lines() -> None:
    source = Path("tests/fixtures/smoke_income_2025.csv").read_bytes()
    statements, unresolved = _records(
        source,
        "smoke_income_2025.csv",
        "text/csv",
        request(),
    )
    assert not unresolved
    lines = {row["canonical_name"]: row for row in statements[0]["lines"]}
    assert int(lines["revenue"]["normalized_value"]) - int(
        lines["cost_of_revenue"]["normalized_value"]
    ) == int(lines["gross_profit"]["normalized_value"])
    assert int(lines["operating_income"]["normalized_value"]) - int(
        lines["interest_expense"]["normalized_value"]
    ) - int(lines["income_tax"]["normalized_value"]) == int(
        lines["net_income"]["normalized_value"]
    )


@pytest.mark.parametrize(
    ("year", "extension", "mime"),
    [
        (
            2024,
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (2023, "pdf", "application/pdf"),
    ],
)
def test_demo_files_extract_accepted_income_statements(
    year: int, extension: str, mime: str
) -> None:
    path = Path(f"tests/fixtures/smoke_income_{year}.{extension}")
    payload = ProcessRequest(
        company_id=uuid4(),
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        currency="USD",
        unit_scale="ones",
        value_column="B",
    )
    statements, unresolved = _records(path.read_bytes(), path.name, mime, payload)
    assert not unresolved
    assert len(statements) == 1
    assert statements[0]["status"] == "accepted"
    lines = {row["canonical_name"]: row for row in statements[0]["lines"]}
    assert lines["revenue"]["normalized_value"] == "1000"
    assert lines["gross_profit"]["normalized_value"] == "400"
    assert lines["net_income"]["normalized_value"] == "135"


def test_processing_persists_lines_checks_and_metrics(monkeypatch) -> None:
    user_id = str(uuid4())
    document_id = str(uuid4())
    company_id = str(uuid4())
    source = (
        b"Item,Amount\nRevenue,1000\nCost of goods sold,600\n"
        b"Gross profit,400\nOperating expenses,200\nOperating income,200\n"
        b"Net income,135\n"
    )
    path = f"{user_id}/{document_id}/golden.csv"
    written: dict[str, list[dict]] = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url, **_):
            if url.endswith("/rest/v1/companies"):
                return httpx.Response(200, json=[{"id": company_id}])
            if url.endswith(path):
                return httpx.Response(200, content=source)
            raise AssertionError(url)

        async def patch(self, url, **_):
            return httpx.Response(200, json=[{"id": document_id}])

        async def delete(self, url, **_):
            raise AssertionError("Successful processing must not delete rows")

    async def documents(*_args, **_kwargs):
        return [
            {
                "id": document_id,
                "storage_path": path,
                "original_filename": "golden.csv",
                "mime_type": "text/csv",
                "file_size": len(source),
                "status": "uploaded",
            }
        ]

    async def state(*_args, **_kwargs):
        return True

    async def write(_client, _url, _key, table, rows):
        written.setdefault(table, []).extend(rows)
        return rows

    monkeypatch.setattr(
        processing,
        "_configuration",
        lambda: ("https://example.supabase.co", "public", "private"),
    )
    monkeypatch.setattr(processing, "_documents", documents)
    monkeypatch.setattr(processing, "_state", state)
    monkeypatch.setattr(processing, "_write", write)
    monkeypatch.setattr(processing.httpx, "AsyncClient", lambda **_: FakeClient())
    app.dependency_overrides[_user_id] = lambda: user_id
    try:
        response = TestClient(app).post(
            f"/api/documents/{document_id}/process",
            json={
                "company_id": company_id,
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
                "currency": "USD",
                "unit_scale": "ones",
                "value_column": "B",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"
    assert len(written["financial_statements"]) == 1
    assert len(written["financial_line_items"]) == 6
    assert written["validation_results"]
    assert any(
        row["metric_name"] == "gross_margin" for row in written["financial_metrics"]
    )
