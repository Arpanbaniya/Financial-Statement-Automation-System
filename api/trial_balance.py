"""Owner-scoped trial-balance preview, atomic generation, export and explanation."""

import hashlib
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from ai.facts import build_facts
from ai.service import analyze
from api.documents import (
    BUCKET,
    MAX_BYTES,
    UserId,
    _configuration,
    _documents,
    _service_headers,
)
from api.reports import _rows
from finance import calculate_cash_flow, calculate_ratios, calculate_working_capital
from finance.trial_balance import (
    CATEGORIES,
    TrialBalanceRequest,
    compile_trial_balance,
    parse_trial_balance,
    snapshots,
)
from ingestion import IngestionError
from reports.trial_balance import build_trial_balance_report
from validation import validate_statements

router = APIRouter(prefix="/api/trial-balance", tags=["trial balance"])


def encode(value):
    return jsonable_encoder(value, custom_encoder={Decimal: str})


async def load_source(client, url, key, document_id, user_id):
    documents = await _documents(
        client,
        url,
        key,
        {
            "select": (
                "id,storage_path,original_filename,mime_type,file_size,sha256,status"
            ),
            "id": f"eq.{document_id}",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        },
    )
    if not documents:
        raise HTTPException(404, "Document not found")
    document = documents[0]
    if document["status"] not in {"uploaded", "failed", "ready", "needs_review"}:
        raise HTTPException(
            409, "Finish the upload or wait for processing before continuing"
        )
    path = document["storage_path"]
    if (
        not path.startswith(f"{user_id}/{document_id}/")
        or document["file_size"] > MAX_BYTES
    ):
        raise HTTPException(409, "Invalid source metadata")
    response = await client.get(
        f"{url}/storage/v1/object/{BUCKET}/{quote(path, safe='/')}",
        headers=_service_headers(key),
    )
    if (
        response.is_error
        or len(response.content) != document["file_size"]
        or (
            document.get("sha256")
            and hashlib.sha256(response.content).hexdigest() != document["sha256"]
        )
    ):
        raise HTTPException(409, "Source file could not be verified")
    return document, response.content


def analysis(result, request, document_id):
    all_snapshots = snapshots(result, request, str(document_id))
    current = tuple(
        item for item in all_snapshots if item.period.period_end == request.period_end
    )
    income = next(
        (item for item in current if item.statement_type == "income_statement"), None
    )
    balance = next(
        (item for item in current if item.statement_type == "balance_sheet"), None
    )
    cash = next(
        (item for item in current if item.statement_type == "cash_flow_statement"), None
    )
    opening = next(
        (
            item
            for item in all_snapshots
            if item.period.period_end != request.period_end
        ),
        None,
    )
    now = datetime.now(UTC)
    ratios = calculate_ratios(
        income_statement=income,
        ending_balance_sheet=balance,
        opening_balance_sheet=opening,
        calculated_at=now,
    )
    working = calculate_working_capital(
        income_statement=income,
        ending_balance_sheet=balance,
        opening_balance_sheet=opening,
        calculated_at=now,
    )
    flows = (
        calculate_cash_flow(
            cash_flow_statement=cash, income_statement=income, calculated_at=now
        )
        if cash
        else ()
    )
    return all_snapshots, ratios, working, flows, validate_statements(current)


@router.get("/{document_id}")
async def preview(
    document_id: UUID,
    user_id: UserId,
    sheet: str | None = Query(default=None, max_length=255),
):
    url, _, key = _configuration()
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            document, source = await load_source(client, url, key, document_id, user_id)
            saved = await _rows(
                client,
                url,
                key,
                "trial_balance_runs",
                {
                    "select": "settings,updated_at",
                    "document_id": f"eq.{document_id}",
                    "user_id": f"eq.{user_id}",
                    "limit": "1",
                },
            )
        settings = saved[0]["settings"] if saved else None
        parsed = parse_trial_balance(
            source,
            document["original_filename"],
            document["mime_type"],
            sheet or (settings or {}).get("sheet"),
        )
        return JSONResponse(
            encode(
                {
                    "parsed": parsed,
                    "settings": settings,
                    "categories": [
                        {"id": name, "label": spec[2]}
                        for name, spec in CATEGORIES.items()
                    ],
                }
            ),
            headers={"Cache-Control": "private, no-store"},
        )
    except (ValueError, IngestionError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Trial balance is unavailable. Try again.") from exc


@router.post("/{document_id}/{action}")
async def generate(
    document_id: UUID, action: str, payload: TrialBalanceRequest, user_id: UserId
):
    if action not in {"check", "generate", "excel", "explain"}:
        raise HTTPException(404, "Unknown action")
    url, _, key = _configuration()
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            companies = await _rows(
                client,
                url,
                key,
                "companies",
                {
                    "select": "id,name",
                    "id": f"eq.{payload.company_id}",
                    "user_id": f"eq.{user_id}",
                    "limit": "1",
                },
            )
            if not companies:
                raise HTTPException(404, "Company not found")
            document, source = await load_source(client, url, key, document_id, user_id)
            parsed = parse_trial_balance(
                source,
                document["original_filename"],
                document["mime_type"],
                payload.sheet,
            )
            result = compile_trial_balance(parsed, payload)
            if not result["ready"]:
                return JSONResponse(
                    encode(result),
                    status_code=200 if action == "check" else 422,
                    headers={"Cache-Control": "private, no-store"},
                )
            all_snapshots, ratios, working, flows, checks = analysis(
                result, payload, document_id
            )
            if any(check.status == "fail" for check in checks):
                raise ValueError(
                    "Statement reconciliation failed; review the source and mappings"
                )
            result["metrics"] = [asdict(item) for item in (*ratios, *working, *flows)]
            result["checks"] = [asdict(check) for check in checks]
            if action == "generate":
                statements, lines, metrics = [], [], []
                for statement in all_snapshots:
                    is_opening = statement.period.period_end != payload.period_end
                    statements.append(
                        {
                            "id": statement.id,
                            "statement_type": statement.statement_type,
                            "period_type": statement.period.period_type,
                            "period_start": statement.period.period_start,
                            "period_end": statement.period.period_end,
                            "status": "draft" if is_opening else "accepted",
                        }
                    )
                    for value in statement.values:
                        lines.append(
                            {
                                "id": value.source_ref.line_item_id,
                                "statement_id": statement.id,
                                "canonical_name": value.field,
                                "original_label": value.field.replace("_", " ").title(),
                                "original_value": str(value.normalized_value),
                                "normalized_value": value.normalized_value,
                                "source_sheet": parsed.get("sheet"),
                                "source_cell": "Opening TB" if is_opening else "TB",
                                "extraction_method": "trial_balance_derived_v1",
                            }
                        )
                for metric in (*ratios, *working, *flows):
                    if metric.value is not None and metric.period:
                        metrics.append(
                            {
                                "statement_id": metric.source_refs[0].statement_id
                                if metric.source_refs
                                else None,
                                "metric_name": metric.metric_name,
                                "metric_value": metric.value,
                                "formula_version": metric.formula_id,
                                "metadata": {
                                    "unit": metric.unit,
                                    "warnings": [asdict(w) for w in metric.warnings],
                                    "source_refs": [
                                        asdict(ref) for ref in metric.source_refs
                                    ],
                                },
                            }
                        )
                response = await client.post(
                    f"{url}/rest/v1/rpc/save_trial_balance",
                    headers=_service_headers(key),
                    json=encode(
                        {
                            "p_user_id": user_id,
                            "p_document_id": str(document_id),
                            "p_company_id": payload.company_id,
                            "p_settings": payload.model_dump(mode="json"),
                            "p_statements": statements,
                            "p_lines": lines,
                            "p_metrics": metrics,
                            "p_checks": [
                                {
                                    "check_name": "trial_balance_balanced",
                                    "status": "passed",
                                    "severity": "info",
                                    "message": (
                                        "Debits and credits reconcile: "
                                        f"{result['debit']} "
                                        f"{payload.currency}."
                                    ),
                                },
                                {
                                    "check_name": "cash_flow_availability",
                                    "status": "warning"
                                    if result["cash_flow_issues"]
                                    else "passed",
                                    "severity": "warning"
                                    if result["cash_flow_issues"]
                                    else "info",
                                    "message": "; ".join(result["cash_flow_issues"])
                                    or "Cash bridge reconciles.",
                                },
                                *[
                                    {
                                        "check_name": check.check_name,
                                        "status": {
                                            "pass": "passed",
                                            "fail": "failed",
                                            "warning": "warning",
                                            "unavailable": "not_applicable",
                                        }[check.status],
                                        "severity": check.severity,
                                        "message": check.explanation,
                                    }
                                    for check in checks
                                ],
                            ],
                        }
                    ),
                )
                if response.is_error:
                    if "Another accepted statement" in response.text:
                        raise HTTPException(
                            409,
                            "Another accepted statement exists for this company "
                            "and period. Remove the old document or use another "
                            "period before generating.",
                        )
                    raise HTTPException(
                        502,
                        "Results could not be saved. "
                        "Your previous results remain unchanged.",
                    )
                result["saved"] = True
            elif action == "excel":
                output = build_trial_balance_report(
                    companies[0]["name"],
                    result,
                    payload,
                    all_snapshots,
                    ratios,
                    working,
                    flows,
                    checks,
                )
                return Response(
                    output,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={
                        "Content-Disposition": (
                            'attachment; filename="Trial_Balance_'
                            f'{payload.period_end}.xlsx"'
                        ),
                        "Cache-Control": "private, no-store",
                    },
                )
            elif action == "explain":
                facts = build_facts(
                    "overview",
                    ratios=ratios,
                    working=working,
                    cash=flows,
                    checks=checks,
                )
                explanation = await analyze(facts)
                result["explanation"] = asdict(explanation)
            return JSONResponse(
                encode(result), headers={"Cache-Control": "private, no-store"}
            )
    except (ValueError, IngestionError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            502, "Trial-balance service is unavailable. Try again."
        ) from exc
