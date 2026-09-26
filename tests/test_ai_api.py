"""Explanation requests enforce ownership and use accepted source values."""

from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_layer.explain import AiNote
from api import ai
from api.index import app

USER = str(uuid4())
OTHER = str(uuid4())
COMPANY = str(uuid4())
DOCUMENT = str(uuid4())
INCOME = str(uuid4())
LINES = [str(uuid4()) for _ in range(4)]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    original = httpx.AsyncClient

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/user":
            token = request.headers.get("Authorization")
            if token == "Bearer owner":
                return httpx.Response(200, json={"id": USER})
            if token == "Bearer other":
                return httpx.Response(200, json={"id": OTHER})
            return httpx.Response(401)
        if request.url.path.startswith("/rest/v1/"):
            assert request.headers["apikey"] == "sb_secret_test"
            if request.url.params["user_id"] != f"eq.{USER}":
                return httpx.Response(200, json=[])
            if request.url.path.endswith("/companies"):
                return httpx.Response(200, json=[{"id": COMPANY}])
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
                result = []
                for index, (field, value) in enumerate(
                    [
                        ("revenue", 1000),
                        ("cost_of_revenue", 400),
                        ("gross_profit", 600),
                        ("net_income", 200),
                    ]
                ):
                    result.append(
                        {
                            "id": LINES[index],
                            "statement_id": INCOME,
                            "canonical_name": field,
                            "original_value": str(value),
                            "normalized_value": value,
                            "currency": "USD",
                            "source_page": 1,
                            "source_sheet": None,
                            "source_cell": None,
                            "review_status": "accepted",
                        }
                    )
                return httpx.Response(200, json=result)
        return httpx.Response(404)

    monkeypatch.setattr(
        ai.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original(
            *args, **{**kwargs, "transport": httpx.MockTransport(handle)}
        ),
    )
    return TestClient(app)


def test_explanation_requires_login_and_company_ownership(client: TestClient) -> None:
    payload = {"company_id": COMPANY, "focus": "profitability"}
    assert client.post("/api/ai/explain", json=payload).status_code == 401
    response = client.post(
        "/api/ai/explain", json=payload, headers={"Authorization": "Bearer other"}
    )
    assert response.status_code == 404


def test_no_key_returns_only_calculated_facts(client: TestClient) -> None:
    response = client.post(
        "/api/ai/explain",
        json={"company_id": COMPANY, "focus": "profitability"},
        headers={"Authorization": "Bearer owner"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "facts_only"
    assert data["notes"] == []
    margin = next(fact for fact in data["facts"] if fact["id"] == "metric_gross_margin")
    assert margin["value"] == "60.0"
    assert margin["sources"][0]["document_id"] == DOCUMENT
    assert margin["sources"][0]["line_item_id"] in LINES
    assert response.headers["Cache-Control"] == "private, no-store"


def test_configured_provider_adds_grounded_note(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")

    async def fake_generate(facts: tuple, *, api_key: str) -> tuple[AiNote, ...]:
        assert api_key == "fake-key"
        assert {fact.id for fact in facts} >= {"metric_gross_margin"}
        return (
            AiNote("metric_gross_margin", "This compares gross profit with revenue."),
        )

    monkeypatch.setattr(ai, "generate_notes", fake_generate)
    response = client.post(
        "/api/ai/explain",
        json={"company_id": COMPANY, "focus": "profitability"},
        headers={"Authorization": "Bearer owner"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "ai"
    assert response.json()["notes"][0]["fact_id"] == "metric_gross_margin"
