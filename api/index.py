"""Vercel entrypoint for the Phase 2 FastAPI skeleton."""

from fastapi import FastAPI

app = FastAPI(title="Financial Statement Automation API")


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report basic availability without exposing configuration or user data."""
    return {"status": "ok"}
