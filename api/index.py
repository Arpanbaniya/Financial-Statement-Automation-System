"""Vercel entrypoint for the application API."""

from fastapi import FastAPI

from api.documents import router as documents_router
from api.reports import router as reports_router

app = FastAPI(title="Financial Statement Automation API")
app.include_router(documents_router)
app.include_router(reports_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report basic availability without exposing configuration or user data."""
    return {"status": "ok"}
