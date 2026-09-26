"""Authenticated, on-demand Excel export from accepted stored statements."""

import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from api.documents import UserId, _configuration, _service_headers
from finance import (
    calculate_cash_flow,
    calculate_common_size,
    calculate_horizontal,
    calculate_ratios,
    calculate_working_capital,
    generate_commentary,
)
from normalization import SourceLocation, normalize_period
from reports import build_excel_report, report_filename
from validation import (
    SourceRef,
    StatementSnapshot,
    ValidationValue,
    validate_statements,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])
_MAX_STATEMENTS = 100
_MAX_LINES = 2000


async def _rows(
    client: httpx.AsyncClient,
    url: str,
    key: str,
    table: str,
    params: dict[str, str],
) -> list[dict[str, Any]]:
    try:
        response = await client.get(
            f"{url}/rest/v1/{table}", params=params, headers=_service_headers(key)
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="Report data is unavailable"
        ) from exc
    if response.is_error:
        raise HTTPException(status_code=502, detail="Report data is unavailable")
    try:
        rows = json.loads(response.text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Invalid report data") from exc
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Invalid report data")
    return rows


def _snapshot(row: dict[str, Any], lines: list[dict[str, Any]]) -> StatementSnapshot:
    kind = row["statement_type"]
    if not row["currency"] or not row["unit_scale"]:
        raise ValueError("Accepted statement currency and unit must be resolved")
    for line in lines:
        if line["review_status"] == "accepted" and line["normalized_value"] is not None:
            if line["original_value"] is None or not (
                line["source_page"] or line["source_cell"]
            ):
                raise ValueError(
                    "Accepted source values need original text and a source location"
                )
    period = normalize_period(
        kind,
        start=row["period_start"] if kind != "balance_sheet" else None,
        end=row["period_end"],
    )
    values = tuple(
        ValidationValue(
            field=line["canonical_name"],
            normalized_value=Decimal(str(line["normalized_value"])),
            original_value=line["original_value"],
            source_ref=SourceRef(
                row["id"],
                line["id"],
                SourceLocation(
                    page=line["source_page"],
                    sheet=line["source_sheet"],
                    cell=line["source_cell"],
                ),
            ),
            currency=line["currency"] or row["currency"],
            unit_scale="ones",
            status="accepted",
        )
        for line in lines
        if line["review_status"] == "accepted"
        and line["canonical_name"]
        and line["normalized_value"] is not None
    )
    return StatementSnapshot(
        id=row["id"],
        company_id=row["company_id"],
        document_id=row["document_id"],
        statement_type=kind,
        period=period,
        values=values,
        currency=row["currency"],
        unit_scale=row["unit_scale"],
    )


def _one(
    statements: tuple[StatementSnapshot, ...], kind: str, period_end: date
) -> StatementSnapshot | None:
    matches = tuple(
        item
        for item in statements
        if item.statement_type == kind and item.period.period_end == period_end
    )
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Several accepted {kind.replace('_', ' ')} records share this date; "
                "choose one version first"
            ),
        )
    return matches[0] if matches else None


@router.get("/excel")
async def download_excel_report(
    user_id: UserId,
    company_id: Annotated[UUID, Query()],
    period_end: Annotated[date | None, Query()] = None,
) -> Response:
    """Build a current workbook; the download is not persisted in reports."""
    url, _, key = _configuration()
    async with httpx.AsyncClient(timeout=20) as client:
        companies = await _rows(
            client,
            url,
            key,
            "companies",
            {
                "select": "id,name",
                "id": f"eq.{company_id}",
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
                "company_id": f"eq.{company_id}",
                "user_id": f"eq.{user_id}",
                "status": "eq.accepted",
                "order": "period_end.desc",
                "limit": str(_MAX_STATEMENTS + 1),
            },
        )
        if len(rows) > _MAX_STATEMENTS:
            raise HTTPException(
                status_code=413, detail="Too many statements for one export"
            )
        if not rows:
            raise HTTPException(
                status_code=409, detail="No accepted statements are available"
            )
        target = period_end or date.fromisoformat(rows[0]["period_end"])
        chosen = tuple(row for row in rows if row["period_end"] == target.isoformat())
        if not chosen:
            raise HTTPException(
                status_code=404, detail="No accepted statements match that period"
            )
        statement_ids = ",".join(row["id"] for row in rows)
        lines = await _rows(
            client,
            url,
            key,
            "financial_line_items",
            {
                "select": (
                    "id,statement_id,canonical_name,original_value,"
                    "normalized_value,currency,source_page,source_sheet,"
                    "source_cell,review_status"
                ),
                "statement_id": f"in.({statement_ids})",
                "user_id": f"eq.{user_id}",
                "limit": str(_MAX_LINES + 1),
            },
        )
        if len(lines) > _MAX_LINES:
            raise HTTPException(
                status_code=413, detail="Too many source lines for one export"
            )
    by_statement: dict[str, list[dict[str, Any]]] = defaultdict(list)
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
            result
            for result in calculate_horizontal(all_snapshots, calculated_at=timestamp)
            if result.current_period.period_end == target
        )
        common = tuple(
            result
            for item in current
            if item.statement_type != "cash_flow_statement"
            for result in calculate_common_size(item, calculated_at=timestamp)
        )
        checks = validate_statements(current)
        commentary = generate_commentary(horizontal=growth)
        output = build_excel_report(
            company_name=companies[0]["name"],
            statements=current,
            ratios=ratios,
            horizontal=growth,
            common_size=common,
            working_capital=working,
            cash_flow=flows,
            commentary=commentary,
            validations=checks,
            generated_at=timestamp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    filename = report_filename(companies[0]["name"], target.isoformat())
    return Response(
        content=output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )
