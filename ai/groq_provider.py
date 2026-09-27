"""Groq chat completion client with strict output validation."""

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from ai.facts import AiFact
from ai.prompts import request_body

_UNSAFE_NOTE = re.compile(
    r"\b(?:buy|sell|hold|invest|recommend|should|will|forecast|predict|"
    r"because|caused|undervalued|overvalued|fraud)\b|due to|target price|share price",
    re.IGNORECASE,
)
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,99}")


@dataclass(frozen=True, slots=True)
class AiNote:
    fact_id: str
    kind: Literal["observation", "question"]
    text: str


class AiProviderError(RuntimeError):
    """The provider could not produce a usable grounded explanation."""


def parse_notes(data: dict[str, Any], facts: tuple[AiFact, ...]) -> tuple[AiNote, ...]:
    try:
        content = data["choices"][0]["message"]["content"]
        notes = json.loads(content)["notes"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AiProviderError("Invalid AI response") from exc
    if not isinstance(notes, list) or len(notes) > 5:
        raise AiProviderError("Invalid AI response")
    valid_ids = {fact.id for fact in facts}
    result = []
    for note in notes:
        if not isinstance(note, dict):
            raise AiProviderError("Invalid AI response")
        fact_id, kind, text = (
            note.get("fact_id"),
            note.get("kind"),
            note.get("text"),
        )
        if (
            not isinstance(fact_id, str)
            or fact_id not in valid_ids
            or kind not in {"observation", "question"}
            or not isinstance(text, str)
            or not 1 <= len(text.strip()) <= 240
            or re.search(r"\d", text)
            or _UNSAFE_NOTE.search(text)
        ):
            raise AiProviderError("AI response is not grounded in supplied facts")
        result.append(AiNote(fact_id, kind, text.strip()))
    return tuple(result)


async def generate_notes(
    facts: tuple[AiFact, ...],
    *,
    api_key: str,
    model: str,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
) -> tuple[AiNote, ...]:
    """Send the structured fact pack without raw files or source locations."""
    if not facts:
        return ()
    if not api_key or not _MODEL_ID.fullmatch(model):
        raise AiProviderError("AI provider is not configured")
    if not 1 <= timeout_seconds <= 60:
        raise AiProviderError("Invalid AI timeout")
    own_client = client is None
    client = client or httpx.AsyncClient(
        timeout=timeout_seconds, follow_redirects=False
    )
    try:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=request_body(facts, model),
        )
    except httpx.HTTPError as exc:
        raise AiProviderError("AI provider is unavailable") from exc
    finally:
        if own_client:
            await client.aclose()
    if response.status_code != 200:
        raise AiProviderError(f"AI provider returned HTTP {response.status_code}")
    try:
        return parse_notes(response.json(), facts)
    except ValueError as exc:
        raise AiProviderError("Invalid AI response") from exc
