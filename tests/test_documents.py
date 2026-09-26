"""Exercise metadata validation and the reservation-to-uploaded transition."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from api import documents
from api.index import app

USER_ID = str(uuid4())
OTHER_USER_ID = str(uuid4())
DOCUMENT_ID = str(uuid4())
HASH = "a" * 64
PATH = f"{USER_ID}/{DOCUMENT_ID}/report.pdf"
PAYLOAD = {
    "filename": "report.pdf",
    "mime_type": "application/pdf",
    "file_size": 42,
    "sha256": HASH,
}


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    """Serve fake Supabase responses without contacting production data."""
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    rows: list[dict] = []
    object_info: dict | None = None
    original_client = httpx.AsyncClient

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal object_info
        if request.url.path == "/auth/v1/user":
            token = request.headers.get("Authorization")
            if token == "Bearer owner":
                return httpx.Response(200, json={"id": USER_ID})
            if token == "Bearer other":
                return httpx.Response(200, json={"id": OTHER_USER_ID})
            return httpx.Response(401, json={"message": "Invalid token"})
        if request.url.path == "/rest/v1/documents":
            assert request.headers["apikey"] == "sb_secret_test"
            assert "Authorization" not in request.headers
            params = request.url.params
            matched = [
                row
                for row in rows
                if all(
                    str(row.get(name)) == value.removeprefix("eq.")
                    for name, value in params.multi_items()
                    if name in {"user_id", "id", "sha256", "status"}
                    and value.startswith("eq.")
                )
                and all(
                    row.get(name, "") < value.removeprefix("lt.")
                    for name, value in params.multi_items()
                    if value.startswith("lt.")
                )
            ]
            if request.method == "GET":
                return httpx.Response(200, json=matched)
            if request.method == "POST":
                import json

                row = json.loads(request.content)
                row["created_at"] = datetime.now(UTC).isoformat()
                rows.append(row)
                return httpx.Response(201, json=[row])
            if request.method == "PATCH":
                import json

                update = json.loads(request.content)
                for row in matched:
                    row.update(update)
                return httpx.Response(200, json=matched)
            if request.method == "DELETE":
                for row in matched:
                    rows.remove(row)
                return httpx.Response(204)
        if request.url.path.startswith("/storage/v1/object/info/"):
            return (
                httpx.Response(200, json=object_info)
                if object_info
                else httpx.Response(404)
            )
        if request.url.path.startswith("/storage/v1/object/"):
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    monkeypatch.setattr(
        documents.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_client(
            *args, **{**kwargs, "transport": httpx.MockTransport(handle)}
        ),
    )

    class Fixture:
        client = TestClient(app)

        @staticmethod
        def set_object(info: dict) -> None:
            nonlocal object_info
            object_info = info

    fixture = Fixture()
    fixture.rows = rows
    return fixture


def test_document_routes_require_authentication(api) -> None:
    assert api.client.get("/api/documents").status_code == 401
    assert api.client.post("/api/documents", json=PAYLOAD).status_code == 401
    assert api.client.post(f"/api/documents/{DOCUMENT_ID}/complete").status_code == 401


def test_reservation_rejects_bad_extensions_and_mime(api) -> None:
    headers = {"Authorization": "Bearer owner"}
    macro = {**PAYLOAD, "filename": "report.xlsm"}
    mismatch = {**PAYLOAD, "mime_type": "text/csv"}
    oversized = {**PAYLOAD, "file_size": 10 * 1024 * 1024 + 1}
    assert (
        api.client.post("/api/documents", json=macro, headers=headers).status_code
        == 422
    )
    assert (
        api.client.post("/api/documents", json=mismatch, headers=headers).status_code
        == 422
    )
    assert (
        api.client.post("/api/documents", json=oversized, headers=headers).status_code
        == 422
    )
    assert not api.rows


def test_reservation_retry_and_duplicate_detection(api) -> None:
    headers = {"Authorization": "Bearer owner"}
    first = api.client.post("/api/documents", json=PAYLOAD, headers=headers)
    second = api.client.post("/api/documents", json=PAYLOAD, headers=headers)
    assert first.status_code == 201
    assert second.json() == first.json()
    assert first.json()["storage_path"].startswith(f"{USER_ID}/")
    assert len(api.rows) == 1

    api.rows[0]["status"] = "uploaded"
    duplicate = api.client.post("/api/documents", json=PAYLOAD, headers=headers)
    assert duplicate.status_code == 409


def test_completion_checks_owner_object_size_and_mime(api) -> None:
    api.rows.append(
        {
            "id": DOCUMENT_ID,
            "user_id": USER_ID,
            "storage_path": PATH,
            "mime_type": "application/pdf",
            "file_size": 42,
            "status": "reserved",
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    endpoint = f"/api/documents/{DOCUMENT_ID}/complete"
    assert (
        api.client.post(endpoint, headers={"Authorization": "Bearer other"}).status_code
        == 404
    )
    assert (
        api.client.post(endpoint, headers={"Authorization": "Bearer owner"}).status_code
        == 409
    )
    api.set_object({"metadata": {"size": 40, "mimetype": "application/pdf"}})
    assert (
        api.client.post(endpoint, headers={"Authorization": "Bearer owner"}).status_code
        == 409
    )
    api.set_object({"metadata": {"size": 42, "mimetype": "application/pdf"}})
    response = api.client.post(endpoint, headers={"Authorization": "Bearer owner"})
    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"
    assert api.rows[0]["status"] == "uploaded"
    assert (
        api.client.post(endpoint, headers={"Authorization": "Bearer owner"}).status_code
        == 200
    )


def test_expired_reservation_is_cleaned_on_document_request(api) -> None:
    api.rows.append(
        {
            "id": DOCUMENT_ID,
            "user_id": USER_ID,
            "storage_path": PATH,
            "mime_type": "application/pdf",
            "file_size": 42,
            "status": "reserved",
            "created_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        }
    )
    response = api.client.get(
        "/api/documents", headers={"Authorization": "Bearer owner"}
    )
    assert response.status_code == 200
    assert response.json() == []
    assert api.rows == []
