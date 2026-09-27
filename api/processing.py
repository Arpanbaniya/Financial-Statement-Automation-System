"""Owner-scoped, synchronous processing of a private statement upload."""

import hashlib
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from api.documents import (
    BUCKET,
    MAX_BYTES,
    UserId,
    _configuration,
    _documents,
    _service_headers,
    _upstream,
)
from finance import calculate_cash_flow, calculate_ratios, calculate_working_capital
from finance.detection import detect_statements
from ingestion import IngestionError, ingest_document
from normalization import SourceLocation, map_label, normalize_amount, normalize_period
from validation import (
    SourceRef,
    StatementSnapshot,
    ValidationValue,
    validate_statements,
)

router = APIRouter(prefix="/api/documents", tags=["processing"])
job_router = APIRouter(prefix="/api/processing-jobs", tags=["processing"])


class ProcessRequest(BaseModel):
    company_id: UUID
    period_start: date | None = None
    period_end: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    unit_scale: Literal["ones", "thousands", "millions", "billions"]
    value_column: str = Field(pattern=r"^[A-Z]{1,2}$")

    @field_validator("period_end")
    @classmethod
    def reasonable_end(cls, value: date) -> date:
        if not 1900 <= value.year <= 2200:
            raise ValueError("Reporting year is out of range")
        return value

    @model_validator(mode="after")
    def valid_range(self) -> "ProcessRequest":
        if self.period_start and self.period_start > self.period_end:
            raise ValueError("Start date is after end date")
        return self


def _records(
    source: bytes, filename: str, mime: str, payload: ProcessRequest
) -> tuple[list[dict[str, Any]], bool]:
    """Prepare source-linked statement rows without database side effects."""
    document = ingest_document(source, filename=filename, mime_type=mime)
    detected = detect_statements(document)
    prepared: list[dict[str, Any]] = []
    unresolved = document.extraction_status != "extracted"
    for detection in detected:
        if detection.statement_type == "unknown":
            unresolved = True
            continue
        period = normalize_period(
            detection.statement_type,
            start=payload.period_start
            if detection.statement_type != "balance_sheet"
            else None,
            end=payload.period_end,
        )
        if period.status != "normalized":
            unresolved = True
            continue
        tables = [
            table
            for table in document.tables
            if (
                (
                    detection.source_page is not None
                    and table.page_number == detection.source_page
                )
                or (
                    detection.source_sheet is not None
                    and table.source == detection.source_sheet
                    and (
                        detection.source_table is None
                        or detection.source_table == table.name
                        or detection.source_table.endswith(f"+ {table.name}")
                    )
                )
                or (
                    document.file_type == "csv" and table.name == detection.source_table
                )
            )
        ]
        lines: list[dict[str, Any]] = []
        for table in tables:
            for row in table.rows:
                label_cell = next(
                    (
                        cell
                        for cell in row.cells
                        if isinstance(cell.value, str) and cell.value.strip()
                    ),
                    None,
                )
                amount_cell = next(
                    (
                        cell
                        for cell in row.cells
                        if re.match(r"[A-Z]+", cell.coordinate).group()
                        == payload.value_column
                    ),
                    None,
                )
                if (
                    label_cell is None
                    or amount_cell is None
                    or label_cell == amount_cell
                ):
                    continue
                if amount_cell.value is None or str(amount_cell.value).strip() == "":
                    continue
                location = SourceLocation(
                    page=table.page_number,
                    sheet=table.source
                    if table.page_number is None and table.source != "CSV"
                    else None,
                    cell=amount_cell.coordinate,
                    table=table.name,
                    row=row.number,
                    line=row.source_line,
                )
                mapping = map_label(
                    label_cell.value, detection.statement_type, source_location=location
                )
                amount = normalize_amount(
                    amount_cell.value,
                    unit=payload.unit_scale,
                    currency=payload.currency,
                    source_location=location,
                )
                if mapping.canonical_field is None and row.number == 1:
                    continue  # Column headings are not financial values.
                accepted = (
                    mapping.canonical_field is not None
                    and amount.status == "normalized"
                )
                unresolved |= not accepted
                lines.append(
                    {
                        "canonical_name": mapping.canonical_field,
                        "original_label": label_cell.value,
                        "original_value": str(amount_cell.value),
                        "normalized_value": str(amount.normalized_value)
                        if amount.normalized_value is not None
                        else None,
                        "original_unit": payload.unit_scale,
                        "currency": amount.currency,
                        "source_page": location.page,
                        "source_sheet": location.sheet,
                        "source_cell": location.cell,
                        "extraction_method": document.extraction_method,
                        "mapping_confidence": mapping.confidence,
                        "review_status": "accepted" if accepted else "needs_review",
                        "mapping_method": mapping.method,
                    }
                )
        if not lines:
            unresolved = True
            continue
        accepted_count = sum(line["review_status"] == "accepted" for line in lines)
        status = (
            "accepted"
            if accepted_count >= 2
            and accepted_count == len(lines)
            and detection.confidence >= 0.5
            and not detection.warnings
            else "needs_review"
        )
        if status != "accepted":
            unresolved = True
        prepared.append(
            {
                "statement_type": detection.statement_type,
                "period_type": period.period_type,
                "period_start": period.period_start.isoformat()
                if period.period_start
                else None,
                "period_end": period.period_end.isoformat(),
                "fiscal_year": period.fiscal_year,
                "fiscal_quarter": period.fiscal_quarter,
                "currency": payload.currency,
                "unit_scale": payload.unit_scale,
                "status": status,
                "detection_confidence": detection.confidence,
                "lines": lines,
            }
        )
    return prepared, unresolved or not prepared


async def _write(
    client: httpx.AsyncClient,
    url: str,
    key: str,
    table: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    response = await client.post(
        f"{url}/rest/v1/{table}",
        headers=_service_headers(key, return_rows=True),
        json=rows,
    )
    result = _upstream(response)
    if not isinstance(result, list) or len(result) != len(rows):
        raise HTTPException(
            status_code=502, detail="Processing data could not be saved"
        )
    return result


async def _state(
    client: httpx.AsyncClient,
    url: str,
    key: str,
    document_id: UUID,
    user_id: str,
    status: str,
    *,
    expected: str | None = None,
) -> bool:
    params = {"id": f"eq.{document_id}", "user_id": f"eq.{user_id}", "select": "id"}
    if expected:
        params["status"] = f"eq.{expected}"
    response = await client.patch(
        f"{url}/rest/v1/documents",
        params=params,
        headers=_service_headers(key, return_rows=True),
        json={"status": status},
    )
    return bool(_upstream(response))


async def _job_stage(
    client: httpx.AsyncClient,
    url: str,
    key: str,
    job_id: str,
    user_id: str,
    stage: str,
    progress: int,
) -> None:
    response = await client.patch(
        f"{url}/rest/v1/processing_jobs",
        params={"id": f"eq.{job_id}", "user_id": f"eq.{user_id}"},
        headers=_service_headers(key),
        json={"stage": stage, "progress": progress},
    )
    _upstream(response)


@job_router.get("/{job_id}")
async def processing_job(job_id: UUID, user_id: UserId) -> dict[str, Any]:
    url, _, key = _configuration()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{url}/rest/v1/processing_jobs",
                params={
                    "select": (
                        "id,document_id,status,stage,progress,started_at,"
                        "finished_at,error_code,error_message"
                    ),
                    "id": f"eq.{job_id}",
                    "user_id": f"eq.{user_id}",
                    "limit": "1",
                },
                headers=_service_headers(key),
            )
            rows = _upstream(response)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="Processing status is unavailable"
        ) from exc
    if not rows:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return {
        "job_id": rows[0]["id"],
        **{name: value for name, value in rows[0].items() if name != "id"},
    }


@router.post("/{document_id}/process")
async def process_document(
    document_id: UUID, payload: ProcessRequest, user_id: UserId
) -> dict[str, Any]:
    url, _, key = _configuration()
    async with httpx.AsyncClient(timeout=25) as client:
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
            raise HTTPException(status_code=404, detail="Document not found")
        document = documents[0]
        if document["status"] not in {"uploaded", "failed"}:
            raise HTTPException(
                status_code=409, detail="Document is not ready to process"
            )
        company = await client.get(
            f"{url}/rest/v1/companies",
            params={
                "select": "id",
                "id": f"eq.{payload.company_id}",
                "user_id": f"eq.{user_id}",
                "limit": "1",
            },
            headers=_service_headers(key),
        )
        if not _upstream(company):
            raise HTTPException(status_code=404, detail="Company not found")
        if not await _state(
            client,
            url,
            key,
            document_id,
            user_id,
            "processing",
            expected=document["status"],
        ):
            raise HTTPException(
                status_code=409, detail="Document state changed. Refresh the page"
            )
        job_id = str(uuid4())
        try:
            await _write(
                client,
                url,
                key,
                "processing_jobs",
                [
                    {
                        "id": job_id,
                        "user_id": user_id,
                        "document_id": str(document_id),
                        "status": "processing",
                        "stage": "downloading",
                        "progress": 10,
                        "started_at": datetime.now(UTC).isoformat(),
                    }
                ],
            )
            path = document["storage_path"]
            if (
                not path.startswith(f"{user_id}/{document_id}/")
                or document["file_size"] > MAX_BYTES
            ):
                raise ValueError("Invalid source metadata")
            source = await client.get(
                f"{url}/storage/v1/object/{BUCKET}/{quote(path, safe='/')}",
                headers=_service_headers(key),
            )
            if source.is_error or len(source.content) != document["file_size"]:
                raise ValueError("Source file could not be verified")
            if (
                document.get("sha256")
                and hashlib.sha256(source.content).hexdigest() != document["sha256"]
            ):
                raise ValueError("Source file fingerprint does not match")
            await _job_stage(client, url, key, job_id, user_id, "extracting", 30)
            prepared, unresolved = _records(
                source.content,
                document["original_filename"],
                document["mime_type"],
                payload,
            )
            await _job_stage(client, url, key, job_id, user_id, "normalizing", 60)
            count = 0
            snapshots: list[StatementSnapshot] = []
            accepted_ids: set[str] = set()
            for statement in prepared:
                lines = statement.pop("lines")
                statement_id = str(uuid4())
                if statement["status"] == "accepted":
                    accepted_ids.add(statement_id)
                await _write(
                    client,
                    url,
                    key,
                    "financial_statements",
                    [
                        {
                            **statement,
                            "id": statement_id,
                            "user_id": user_id,
                            "company_id": str(payload.company_id),
                            "document_id": str(document_id),
                        }
                    ],
                )
                line_rows = []
                mappings = []
                reviews = []
                for line in lines:
                    line_id = str(uuid4())
                    method = line.pop("mapping_method")
                    line_rows.append(
                        {
                            **line,
                            "id": line_id,
                            "user_id": user_id,
                            "statement_id": statement_id,
                        }
                    )
                    mappings.append(
                        {
                            "user_id": user_id,
                            "line_item_id": line_id,
                            "suggested_mapping": line["canonical_name"],
                            "selected_mapping": line["canonical_name"]
                            if line["review_status"] == "accepted"
                            else None,
                            "mapping_method": method,
                            "confidence": line["mapping_confidence"],
                            "status": "accepted"
                            if line["review_status"] == "accepted"
                            else "needs_review",
                        }
                    )
                    if line["review_status"] != "accepted":
                        reviews.append(
                            {
                                "user_id": user_id,
                                "line_item_id": line_id,
                                "suggested_mapping": line["canonical_name"],
                                "status": "open",
                            }
                        )
                if line_rows:
                    await _write(client, url, key, "financial_line_items", line_rows)
                    await _write(client, url, key, "line_item_mappings", mappings)
                if reviews:
                    await _write(client, url, key, "manual_reviews", reviews)
                count += len(lines)
                period = normalize_period(
                    statement["statement_type"],
                    start=statement["period_start"],
                    end=statement["period_end"],
                )
                values = tuple(
                    ValidationValue(
                        field=line["canonical_name"],
                        normalized_value=Decimal(line["normalized_value"]),
                        original_value=line["original_value"],
                        source_ref=SourceRef(
                            statement_id,
                            line["id"],
                            SourceLocation(
                                page=line["source_page"],
                                sheet=line["source_sheet"],
                                cell=line["source_cell"],
                            ),
                        ),
                        currency=line["currency"],
                        unit_scale="ones",
                        status="accepted",
                    )
                    for line in line_rows
                    if line["review_status"] == "accepted"
                    and line["canonical_name"]
                    and line["normalized_value"] is not None
                )
                snapshots.append(
                    StatementSnapshot(
                        id=statement_id,
                        company_id=str(payload.company_id),
                        document_id=str(document_id),
                        statement_type=statement["statement_type"],
                        period=period,
                        values=values,
                        currency=payload.currency,
                        unit_scale=payload.unit_scale,
                    )
                )
            if snapshots:
                await _job_stage(client, url, key, job_id, user_id, "validating", 78)
                checks = validate_statements(tuple(snapshots))
                failed_ids = {
                    check.statement_id for check in checks if check.status == "fail"
                }
                if None in failed_ids:
                    failed_ids.update(accepted_ids)
                for failed_id in accepted_ids & failed_ids:
                    response = await client.patch(
                        f"{url}/rest/v1/financial_statements",
                        params={"id": f"eq.{failed_id}", "user_id": f"eq.{user_id}"},
                        headers=_service_headers(key),
                        json={"status": "needs_review"},
                    )
                    _upstream(response)
                accepted_ids.difference_update(failed_ids)
                unresolved |= bool(failed_ids)
                if checks:
                    await _write(
                        client,
                        url,
                        key,
                        "validation_results",
                        [
                            {
                                "user_id": user_id,
                                "document_id": str(document_id),
                                "statement_id": check.statement_id,
                                "check_name": check.check_name,
                                "status": {
                                    "pass": "passed",
                                    "fail": "failed",
                                    "warning": "warning",
                                    "unavailable": "not_applicable",
                                }[check.status],
                                "severity": check.severity,
                                "expected_value": str(check.expected_value)
                                if check.expected_value is not None
                                else None,
                                "actual_value": str(check.actual_value)
                                if check.actual_value is not None
                                else None,
                                "difference": str(check.difference)
                                if check.difference is not None
                                else None,
                                "message": check.explanation,
                            }
                            for check in checks
                        ],
                    )
                income = next(
                    (
                        item
                        for item in snapshots
                        if item.id in accepted_ids
                        and item.statement_type == "income_statement"
                    ),
                    None,
                )
                balance = next(
                    (
                        item
                        for item in snapshots
                        if item.id in accepted_ids
                        and item.statement_type == "balance_sheet"
                    ),
                    None,
                )
                cash = next(
                    (
                        item
                        for item in snapshots
                        if item.id in accepted_ids
                        and item.statement_type == "cash_flow_statement"
                    ),
                    None,
                )
                now = datetime.now(UTC)
                await _job_stage(client, url, key, job_id, user_id, "calculating", 88)
                metrics = (
                    *calculate_ratios(
                        income_statement=income,
                        ending_balance_sheet=balance,
                        calculated_at=now,
                    ),
                    *calculate_working_capital(
                        income_statement=income,
                        ending_balance_sheet=balance,
                        calculated_at=now,
                    ),
                    *(
                        calculate_cash_flow(
                            cash_flow_statement=cash,
                            income_statement=income,
                            calculated_at=now,
                        )
                        if cash
                        else ()
                    ),
                )
                calculated = [
                    item
                    for item in metrics
                    if item.value is not None and item.period and item.period.period_end
                ]
                if calculated:
                    await _write(
                        client,
                        url,
                        key,
                        "financial_metrics",
                        [
                            {
                                "user_id": user_id,
                                "company_id": str(payload.company_id),
                                "statement_id": item.source_refs[0].statement_id
                                if item.source_refs
                                else None,
                                "period_end": item.period.period_end.isoformat(),
                                "metric_name": item.metric_name,
                                "metric_value": str(item.value),
                                "formula_version": item.formula_id,
                                "metadata": {
                                    "source_refs": [
                                        {
                                            "statement_id": ref.statement_id,
                                            "line_item_id": ref.line_item_id,
                                        }
                                        for ref in item.source_refs
                                        if ref.line_item_id
                                    ]
                                },
                            }
                            for item in calculated
                        ],
                    )
            final = "needs_review" if unresolved else "ready"
            update = await client.patch(
                f"{url}/rest/v1/documents",
                params={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
                headers=_service_headers(key),
                json={"status": final, "company_id": str(payload.company_id)},
            )
            _upstream(update)
            job = await client.patch(
                f"{url}/rest/v1/processing_jobs",
                params={"id": f"eq.{job_id}", "user_id": f"eq.{user_id}"},
                headers=_service_headers(key),
                json={
                    "status": "ready",
                    "stage": "ready",
                    "progress": 100,
                    "finished_at": datetime.now(UTC).isoformat(),
                },
            )
            _upstream(job)
            return {
                "job_id": job_id,
                "document_id": str(document_id),
                "status": final,
                "stage": "ready",
                "statements": len(prepared),
                "lines": count,
            }
        except Exception as exc:
            # Remove derived rows together. Retain the upload for a retry.
            await client.delete(
                f"{url}/rest/v1/validation_results",
                params={"document_id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
                headers=_service_headers(key),
            )
            await client.delete(
                f"{url}/rest/v1/financial_statements",
                params={"document_id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
                headers=_service_headers(key),
            )
            await _state(client, url, key, document_id, user_id, "failed")
            await client.patch(
                f"{url}/rest/v1/processing_jobs",
                params={"id": f"eq.{job_id}", "user_id": f"eq.{user_id}"},
                headers=_service_headers(key),
                json={
                    "status": "failed",
                    "stage": "failed",
                    "error_code": "PROCESSING_FAILED",
                    "error_message": "Processing failed. Check the file and try again.",
                    "finished_at": datetime.now(UTC).isoformat(),
                },
            )
            raise HTTPException(
                status_code=422
                if isinstance(exc, (ValueError, IngestionError))
                else 502,
                detail="Processing failed. Check the file and try again.",
            ) from exc
