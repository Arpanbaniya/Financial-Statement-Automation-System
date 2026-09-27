"""Optional, authenticated explanations of accepted financial results."""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ai.facts import Focus, build_facts
from ai.service import analyze
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
        periods: dict[date, list] = defaultdict(list)
        for item in all_snapshots:
            periods[item.period.period_end].append(item)
        period_checks = {
            period: validate_statements(tuple(items))
            for period, items in periods.items()
        }
        checks = period_checks[target]
        if any(check.status == "fail" for check in checks):
            raise HTTPException(
                status_code=409,
                detail="Resolve failed validation checks before requesting AI",
            )
        valid_periods = {
            period
            for period, results in period_checks.items()
            if not any(check.status == "fail" for check in results)
        }
        valid_snapshots = tuple(
            item for item in all_snapshots if item.period.period_end in valid_periods
        )
        income = _one(valid_snapshots, "income_statement", target)
        balance = _one(valid_snapshots, "balance_sheet", target)
        cash = _one(valid_snapshots, "cash_flow_statement", target)
        opening = (
            _one(
                valid_snapshots,
                "balance_sheet",
                income.period.period_start - timedelta(days=1),
            )
            if income and income.period.period_start and balance
            else None
        )
        earlier_income = sorted(
            (
                item
                for item in valid_snapshots
                if income
                and item.statement_type == "income_statement"
                and item.period.period_end < target
                and item.period.period_type == income.period.period_type
                and item.currency == income.currency
            ),
            key=lambda item: item.period.period_end,
            reverse=True,
        )
        previous_income = earlier_income[0] if earlier_income else None
        previous_end = previous_income.period.period_end if previous_income else None
        previous_balance = (
            _one(valid_snapshots, "balance_sheet", previous_end)
            if previous_end
            else None
        )
        previous_opening = (
            _one(
                valid_snapshots,
                "balance_sheet",
                previous_income.period.period_start - timedelta(days=1),
            )
            if previous_income
            and previous_income.period.period_start
            and previous_balance
            else None
        )
        timestamp = datetime.now(UTC)
        ratios = calculate_ratios(
            income_statement=income,
            ending_balance_sheet=balance,
            opening_balance_sheet=opening,
            calculated_at=timestamp,
        )
        previous_ratios = (
            calculate_ratios(
                income_statement=previous_income,
                ending_balance_sheet=previous_balance,
                opening_balance_sheet=previous_opening,
                calculated_at=timestamp,
            )
            if previous_income
            else ()
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
            for item in calculate_horizontal(valid_snapshots, calculated_at=timestamp)
            if item.current_period.period_end == target
        )
        facts = build_facts(
            payload.focus,
            ratios=ratios,
            previous_ratios=previous_ratios,
            working=working,
            cash=flows,
            growth=growth,
            checks=checks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    analysis = await analyze(facts)
    documents = {item.id: item.document_id for item in all_snapshots}
    return JSONResponse(
        {
            "provider": analysis.provider,
            "fallback_used": analysis.fallback_used,
            "text": analysis.text,
            "period_end": target.isoformat(),
            "facts": [
                {
                    "id": fact.id,
                    "kind": fact.kind,
                    "label": fact.label,
                    "value": str(fact.value) if fact.value is not None else None,
                    "unit": fact.unit,
                    "currency": fact.currency,
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
            "notes": [
                {"fact_id": note.fact_id, "kind": note.kind, "text": note.text}
                for note in analysis.notes
            ],
        },
        headers={"Cache-Control": "private, no-store"},
    )
