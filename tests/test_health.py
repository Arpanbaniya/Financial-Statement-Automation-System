"""Verify the only Phase 2 API endpoint."""

from fastapi.testclient import TestClient

from api.index import app


def test_health_returns_public_minimal_status() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
