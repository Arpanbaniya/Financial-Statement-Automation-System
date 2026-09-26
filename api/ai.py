"""Optional, authenticated explanations of accepted financial results."""

import os
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ai_layer import build_facts, generate_notes
from ai_layer.explain import AiProviderError, Focus
from api.documents import UserId, _configuration
from api.reports import _one, _rows, _snapshot
from finance import (
    calculate_cash_flow,
    calculate_horizontal,
    calculate_ratios,
    calculate_working_capital,
)
from validation import validate_statements

router = APIRouter(prefix="/api/ai", tags=["ai"])
_MAX_STATEMENTS = 50
_MAX_LINES = 1000


class ExplanationRequest(BaseModel):
    company_id: UUID
    focus: Focus
    period_end: date | None = None


@router.post("/explain")
async def explain_financial_results(
    payload: ExplanationRequest, user_id: UserId
) -> JSONResponse:
    """Return source-linked facts and optional Groq notes on an explicit request."""
    url, _, key = _configuration()
    async with httpx.AsyncClient(timeout=15) as client:
        companies = await _rows(
            client,
            url,
            key,
            "companies",
            {
                "select": "id",
                "id": f"eq.{payload.company_id}",
                "user_id": f"eq.{user_id}",
                "limit": "1",
            },
        )
        if not companies:
            raise HTTPException(status_code=404, detail="Company not found")
        rows = await _rows(
            client,
            url,
            key,
            "financial_statements",
            {
                "select": (
                    "id,company_id,document_id,statement_type,period_start,"
                    "period_end,currency,unit_scale"
                ),
                "company_id": f"eq.{payload.company_id}",
                "user_id": f"eq.{user_id}",
                "status": "eq.accepted",
                "order": "period_end.desc",
                "limit": str(_MAX_STATEMENTS + 1),
            },
        )
        if len(rows) > _MAX_STATEMENTS:
            raise HTTPException(status_code=413, detail="Too many statements")
        if not rows:
            raise HTTPException(
                status_code=409, detail="No accepted statements are available"
            )
        target = payload.period_end or date.fromisoformat(rows[0]["period_end"])
        if not any(row["period_end"] == target.isoformat() for row in rows):
            raise HTTPException(
                status_code=404, detail="No statements match that period"
            )
        statement_ids = ",".join(row["id"] for row in rows)
        lines = await _rows(
            client,
            url,
            key,
            "financial_line_items",
            {
                "select": (
                    "id,statement_id,canonical_name,original_value,normalized_value,"
                    "currency,source_page,source_sheet,source_cell,review_status"
                ),
                "statement_id": f"in.({statement_ids})",
                "user_id": f"eq.{user_id}",
                "limit": str(_MAX_LINES + 1),
            },
        )
        if len(lines) > _MAX_LINES:
            raise HTTPException(status_code=413, detail="Too many source lines")
    by_statement: dict[str, list[dict]] = defaultdict(list)
    for line in lines:
        by_statement[line["statement_id"]].append(line)
    try:
        all_snapshots = tuple(_snapshot(row, by_statement[row["id"]]) for row in rows)
        current = tuple(
            item for item in all_snapshots if item.period.period_end == target
        )
        income = _one(all_snapshots, "income_statement", target)
        balance = _one(all_snapshots, "balance_sheet", target)
        cash = _one(all_snapshots, "cash_flow_statement", target)
        opening = (
            _one(
                all_snapshots,
                "balance_sheet",
                income.period.period_start - timedelta(days=1),
            )
            if income and income.period.period_start and balance
            else None
        )
        checks = validate_statements(current)
        if any(check.status == "fail" for check in checks):
            raise HTTPException(
                status_code=409,
                detail="Resolve failed validation checks before requesting AI",
            )
        timestamp = datetime.now(UTC)
        ratios = calculate_ratios(
            income_statement=income,
            ending_balance_sheet=balance,
            opening_balance_sheet=opening,
            calculated_at=timestamp,
        )
        working = calculate_working_capital(
            income_statement=income,
            ending_balance_sheet=balance,
            opening_balance_sheet=opening,
            calculated_at=timestamp,
        )
        flows = (
            calculate_cash_flow(
                cash_flow_statement=cash,
                income_statement=income,
                calculated_at=timestamp,
            )
            if cash
            else ()
        )
        growth = tuple(
            item
            for item in calculate_horizontal(all_snapshots, calculated_at=timestamp)
            if item.current_period.period_end == target
        )
        facts = build_facts(
            payload.focus,
            ratios=ratios,
            working=working,
            cash=flows,
            growth=growth,
            checks=checks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not facts:
        raise HTTPException(
            status_code=409,
            detail="No validated, source-linked facts are available for this area",
        )
    notes = ()
    mode: Literal["ai", "facts_only"] = "facts_only"
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if api_key:
        try:
            notes = await generate_notes(facts, api_key=api_key)
            mode = "ai"
        except AiProviderError:
            pass
    documents = {item.id: item.document_id for item in all_snapshots}
    return JSONResponse(
        {
            "mode": mode,
            "period_end": target.isoformat(),
            "facts": [
                {
                    "id": fact.id,
                    "kind": fact.kind,
                    "label": fact.label,
                    "value": str(fact.value) if fact.value is not None else None,
                    "unit": fact.unit,
                    "period_end": (
                        fact.period_end.isoformat() if fact.period_end else None
                    ),
                    "sources": [
                        {
                            "document_id": documents[ref.statement_id],
                            "line_item_id": ref.line_item_id,
                        }
                        for ref in fact.source_refs
                        if ref.statement_id in documents and ref.line_item_id
                    ],
                }
                for fact in facts
            ],
            "notes": [{"fact_id": note.fact_id, "text": note.text} for note in notes],
        },
        headers={"Cache-Control": "private, no-store"},
    )
