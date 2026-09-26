"""The optional provider receives only source-linked calculated facts."""

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from ai_layer.explain import (
    AiFact,
    AiProviderError,
    _provider_payload,
    build_facts,
    generate_notes,
)
from finance.ratios import MetricResult
from normalization.periods import normalize_period
from validation.types import SourceRef


def fact() -> AiFact:
    return AiFact(
        id="metric_gross_margin",
        kind="metric",
        label="gross margin",
        value=Decimal(60),
        unit="percent",
        period_end=date(2025, 12, 31),
        source_refs=(SourceRef("statement-1", "line-1"),),
    )


def test_only_calculated_source_linked_metrics_are_sent() -> None:
    period = normalize_period("income_statement", start="2025-01-01", end="2025-12-31")
    known = MetricResult(
        metric_name="gross_margin",
        status="calculated",
        value=Decimal(60),
        formula_id="gross_margin_v1",
        numerator=Decimal(600),
        denominator=Decimal(1000),
        period=period,
        unit="percent",
        calculated_at=datetime.now(UTC),
        inputs=(),
        source_refs=(SourceRef("statement-1", "line-1"),),
        warnings=(),
    )
    missing_source = MetricResult(
        metric_name="net_margin",
        status="calculated",
        value=Decimal(20),
        formula_id="net_margin_v1",
        numerator=Decimal(200),
        denominator=Decimal(1000),
        period=period,
        unit="percent",
        calculated_at=known.calculated_at,
        inputs=(),
        source_refs=(),
        warnings=(),
    )
    facts = build_facts("profitability", ratios=(known, missing_source))
    assert [item.id for item in facts] == ["metric_gross_margin"]
    payload = _provider_payload(facts)
    assert "statement-1" not in str(payload)
    assert "line-1" not in str(payload)
    assert payload["response_format"]["json_schema"]["strict"] is True


def test_groq_response_must_refer_to_supplied_fact() -> None:
    seen = []

    def good(request: httpx.Request) -> httpx.Response:
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
                                            "fact_id": "metric_gross_margin",
                                            "text": "Gross profit share.",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    async def request_notes() -> tuple:
        async with httpx.AsyncClient(transport=httpx.MockTransport(good)) as client:
            return await generate_notes((fact(),), api_key="fake-key", client=client)

    notes = asyncio.run(request_notes())
    assert notes[0].fact_id == "metric_gross_margin"
    assert seen[0].url.host == "api.groq.com"
    assert seen[0].headers["Authorization"] == "Bearer fake-key"

    def bad(_request: httpx.Request) -> httpx.Response:
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
                                            "fact_id": "made_up",
                                            "text": "Unknown source.",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    async def invalid_notes() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(bad)) as client:
            await generate_notes((fact(),), api_key="fake-key", client=client)

    with pytest.raises(AiProviderError, match="grounded"):
        asyncio.run(invalid_notes())


def test_numeric_claims_in_model_text_are_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
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
                                            "fact_id": "metric_gross_margin",
                                            "text": "Profit will rise 50%.",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    async def invalid_notes() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await generate_notes((fact(),), api_key="fake-key", client=client)

    with pytest.raises(AiProviderError, match="grounded"):
        asyncio.run(invalid_notes())
