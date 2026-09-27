"""Provider failures always return a useful rule-based explanation."""

import asyncio
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from ai.facts import AiFact
from ai.fallback_agent import fallback_text
from ai.groq_provider import AiProviderError, generate_notes
from ai.prompts import fact_pack
from ai.service import analyze
from validation.types import SourceRef


def fact(
    name: str,
    value: str,
    *,
    period: date = date(2025, 12, 31),
    unit: str = "percent",
) -> AiFact:
    return AiFact(
        id=f"metric_{name}_{period.isoformat()}",
        kind="metric",
        label=name.replace("_", " "),
        value=Decimal(value),
        unit=unit,
        period_end=period,
        source_refs=(SourceRef("statement-1", "line-1"),),
        currency="USD",
    )


def test_fallback_revenue_both_directions_and_zero() -> None:
    assert "increased by 15.0%" in fallback_text((fact("revenue_growth", "15"),))
    assert "decreased by 8.0%" in fallback_text((fact("revenue_growth", "-8"),))
    assert "unchanged" in fallback_text((fact("revenue_growth", "0"),))


def test_fallback_margin_and_ratio_changes() -> None:
    previous = date(2024, 12, 31)
    facts = (
        fact("gross_margin", "38"),
        fact("gross_margin", "40", period=previous),
        fact("operating_margin", "16"),
        fact("operating_margin", "18", period=previous),
        fact("net_margin", "12"),
        fact("net_margin", "11", period=previous),
        fact("current_ratio", "1.6", unit="times"),
        fact("current_ratio", "1.8", period=previous, unit="times"),
        fact("debt_to_equity", "0.8", unit="times"),
        fact("debt_to_equity", "0.7", period=previous, unit="times"),
    )
    text = fallback_text(facts)
    assert "Gross margin decreased from 40.0% to 38.0%" in text
    assert "Operating margin decreased from 18.0% to 16.0%" in text
    assert "Net margin increased from 11.0% to 12.0%" in text
    assert "current ratio decreased from 1.8 to 1.6" in text
    assert "Debt-to-equity increased from 0.7 to 0.8" in text


def test_fallback_returns_and_cash_flow_signs() -> None:
    facts = (
        fact("return_on_assets", "8"),
        fact("return_on_equity", "14"),
        fact("operating_cash_flow", "95000000", unit="currency"),
        fact("free_cash_flow", "-82000000", unit="currency"),
    )
    text = fallback_text(facts)
    assert "Return on assets was 8.0%" in text
    assert "Return on equity was 14.0%" in text
    assert "Operating cash flow was positive at USD 95.0 million" in text
    assert "Free cash flow was negative at USD -82.0 million" in text
    assert "positive at USD 82.0 million" in fallback_text(
        (fact("free_cash_flow", "82000000", unit="currency"),)
    )


def test_missing_metrics_are_skipped_and_empty_pack_is_explicit() -> None:
    assert (
        fallback_text(())
        == "No validated, source-linked metrics are available to explain."
    )
    text = fallback_text((fact("gross_margin", "0"),))
    assert "Gross margin was 0.0%" in text
    assert "Revenue" not in text
    assert "Free cash flow" not in text


def test_fact_pack_contains_no_raw_source_identifiers() -> None:
    payload = fact_pack((fact("gross_margin", "38"),))
    serialized = json.dumps(payload)
    assert "statement-1" not in serialized
    assert "line-1" not in serialized
    assert payload["metrics"][0]["value"] == "38"


def test_service_uses_groq_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("AI_MODEL", "openai/gpt-oss-20b")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "7")
    seen = []
    item = fact("gross_margin", "38")

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "notes": [
                                        {
                                            "fact_id": item.id,
                                            "kind": "observation",
                                            "text": "Gross margin compares profits.",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    async def run() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await analyze((item,), client=client)

    result = asyncio.run(run())
    assert result.provider == "groq"
    assert result.fallback_used is False
    assert "Gross margin compares profits." in result.text
    assert seen[0].headers["Authorization"] == "Bearer fake-key"
    assert seen[0].url.host == "api.groq.com"
    assert json.loads(seen[0].content)["model"] == "openai/gpt-oss-20b"


@pytest.mark.parametrize("status", [429, 500])
def test_rate_limit_and_api_error_fall_back(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setenv("AI_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")

    async def run() -> object:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(status))
        ) as client:
            return await analyze((fact("revenue_growth", "15"),), client=client)

    result = asyncio.run(run())
    assert result.provider == "deterministic"
    assert result.fallback_used is True
    assert "Revenue increased by 15.0%" in result.text


def test_timeout_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async def run() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            return await analyze((fact("gross_margin", "38"),), client=client)

    result = asyncio.run(run())
    assert result.provider == "deterministic"
    assert "Gross margin was 38.0%" in result.text


def test_malformed_provider_output_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")

    async def run() -> object:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"choices": []})
            )
        ) as client:
            return await analyze((fact("gross_margin", "38"),), client=client)

    result = asyncio.run(run())
    assert result.provider == "deterministic"
    assert result.fallback_used is True


def test_missing_key_and_disabled_provider_use_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = fact("gross_margin", "38")
    monkeypatch.setenv("AI_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    missing = asyncio.run(analyze((item,)))
    assert (missing.provider, missing.fallback_used) == ("deterministic", True)
    monkeypatch.setenv("AI_PROVIDER", "none")
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    disabled = asyncio.run(analyze((item,)))
    assert (disabled.provider, disabled.fallback_used) == ("deterministic", True)


def test_ungrounded_note_is_rejected_without_exposing_text() -> None:
    item = fact("gross_margin", "38")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "notes": [
                                                {
                                                    "fact_id": "made_up",
                                                    "kind": "observation",
                                                    "text": "Buy stock.",
                                                }
                                            ]
                                        }
                                    )
                                }
                            }
                        ]
                    },
                )
            )
        ) as client:
            await generate_notes(
                (item,),
                api_key="fake-key",
                model="openai/gpt-oss-20b",
                timeout_seconds=20,
                client=client,
            )

    with pytest.raises(AiProviderError, match="grounded"):
        asyncio.run(run())
