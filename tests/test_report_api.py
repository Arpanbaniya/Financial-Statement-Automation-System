"""Report downloads require ownership and produce an inspectable workbook."""

from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from api import reports
from api.index import app

USER = str(uuid4())
OTHER = str(uuid4())
COMPANY = str(uuid4())
DOCUMENT = str(uuid4())
INCOME = str(uuid4())
LINE = str(uuid4())


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    original = httpx.AsyncClient

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/user":
            if request.headers.get("Authorization") == "Bearer owner":
                return httpx.Response(200, json={"id": USER})
            if request.headers.get("Authorization") == "Bearer other":
                return httpx.Response(200, json={"id": OTHER})
            return httpx.Response(401)
        if request.url.path.startswith("/rest/v1/"):
            assert request.headers["apikey"] == "sb_secret_test"
            assert "Authorization" not in request.headers
            assert (
                request.url.params["user_id"] == f"eq.{USER}"
                or request.url.params["user_id"] == f"eq.{OTHER}"
            )
            if request.url.params["user_id"] != f"eq.{USER}":
                return httpx.Response(200, json=[])
            if request.url.path.endswith("/companies"):
                return httpx.Response(
                    200, json=[{"id": COMPANY, "name": "Example Ltd"}]
                )
            if request.url.path.endswith("/financial_statements"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": INCOME,
                            "company_id": COMPANY,
                            "document_id": DOCUMENT,
                            "statement_type": "income_statement",
                            "period_start": "2025-01-01",
                            "period_end": "2025-12-31",
                            "currency": "USD",
                            "unit_scale": "ones",
                        }
                    ],
                )
            if request.url.path.endswith("/financial_line_items"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": LINE,
                            "statement_id": INCOME,
                            "canonical_name": "revenue",
                            "original_value": "1,000",
                            "normalized_value": 1000,
                            "currency": "USD",
                            "source_page": 2,
                            "source_sheet": None,
                            "source_cell": None,
                            "review_status": "accepted",
                        }
                    ],
                )
        return httpx.Response(404)

    monkeypatch.setattr(
        reports.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original(
            *args, **{**kwargs, "transport": httpx.MockTransport(handle)}
        ),
    )
    return TestClient(app)


def test_export_owner_and_workbook(client: TestClient) -> None:
    route = f"/api/reports/excel?company_id={COMPANY}"
    assert client.get(route).status_code == 401
    assert (
        client.get(route, headers={"Authorization": "Bearer other"}).status_code == 404
    )
    response = client.get(route, headers={"Authorization": "Bearer owner"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert (
        "Financial_Analysis_Example_Ltd_2025-12-31.xlsx"
        in response.headers["content-disposition"]
    )
    book = load_workbook(BytesIO(response.content))
    assert book["Income Statement"]["C5"].value == 1000
    assert book["Source Data"]["D5"].value == "1,000"
