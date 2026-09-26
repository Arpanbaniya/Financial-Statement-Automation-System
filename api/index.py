"""Vercel's Python entrypoint for the public API health route."""

from fastapi import FastAPI

app = FastAPI(title="Financial Statement Automation API")


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report basic availability without exposing configuration or user data."""
    return {"status": "ok"}
