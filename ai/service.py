"""Choose Groq or the deterministic fallback without changing finance data."""

import os
from dataclasses import dataclass
from typing import Literal

import httpx

from ai.facts import AiFact
from ai.fallback_agent import fallback_text
from ai.groq_provider import AiNote, AiProviderError, generate_notes


@dataclass(frozen=True, slots=True)
class AnalysisResponse:
    provider: Literal["groq", "deterministic"]
    fallback_used: bool
    text: str
    notes: tuple[AiNote, ...] = ()


def _timeout(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        return 20.0
    return value if 1 <= value <= 60 else 20.0


async def analyze(
    facts: tuple[AiFact, ...],
    *,
    client: httpx.AsyncClient | None = None,
) -> AnalysisResponse:
    """Use one configured provider call, then fall back on every failure."""
    fallback = AnalysisResponse("deterministic", True, fallback_text(facts))
    if not facts or os.getenv("AI_PROVIDER", "none").lower() != "groq":
        return fallback
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return fallback
    try:
        notes = await generate_notes(
            facts,
            api_key=key,
            model=os.getenv("AI_MODEL", "openai/gpt-oss-20b").strip(),
            timeout_seconds=_timeout(os.getenv("AI_TIMEOUT_SECONDS", "20")),
            client=client,
        )
    except AiProviderError:
        return fallback
    if not notes:
        return fallback
    observations = " ".join(note.text for note in notes if note.kind == "observation")
    questions = " ".join(note.text for note in notes if note.kind == "question")
    text = " ".join(
        part
        for part in (
            observations,
            f"Questions to investigate: {questions}" if questions else "",
        )
        if part
    )
    return AnalysisResponse("groq", False, text, notes)
