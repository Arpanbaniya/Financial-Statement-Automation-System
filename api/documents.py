"""Authenticated document reservations and verified upload completion.

The API handles metadata only. File bytes travel from the browser to Storage.
"""

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

router = APIRouter(prefix="/api/documents", tags=["documents"])
BUCKET = "financial-documents"
MAX_BYTES = 10 * 1024 * 1024
MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
}
CSV_BROWSER_MIMES = {"text/csv", "application/csv", "application/vnd.ms-excel"}
RESERVATION_LIFETIME = timedelta(hours=1)


class ReservationRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=120)
    file_size: int = Field(gt=0, le=MAX_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value) or "\x7f" in value:
            raise ValueError("Filename contains control characters")
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("Filename must not contain a path")
        return value

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", value):
            raise ValueError("Invalid MIME type")
        return value


def _configuration() -> tuple[str, str, str]:
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
    publishable_key = os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "")
    service_key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get(
        "SUPABASE_SERVICE_ROLE_KEY", ""
    )
    if not url or not publishable_key or not service_key:
        raise HTTPException(
            status_code=503, detail="Document service is not configured"
        )
    return url, publishable_key, service_key


async def _user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to continue")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    url, public_key, _ = _configuration()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{url}/auth/v1/user",
                headers={"apikey": public_key, "Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail="Authentication is unavailable"
        ) from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again")
    try:
        return str(UUID(response.json()["id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=503, detail="Invalid authentication response"
        ) from exc


UserId = Annotated[str, Depends(_user_id)]


def _service_headers(service_key: str, *, return_rows: bool = False) -> dict[str, str]:
    headers = {"apikey": service_key, "Content-Type": "application/json"}
    if not service_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {service_key}"
    if return_rows:
        headers["Prefer"] = "return=representation"
    return headers


def _upstream(response: httpx.Response) -> Any:
    if response.is_error:
        raise HTTPException(status_code=502, detail="Document storage is unavailable")
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def _safe_filename(filename: str) -> str:
    stem = PurePath(filename).stem
    extension = PurePath(filename).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")[:80]
    return f"{stem or 'document'}{extension}"


def _canonical_mime(filename: str, mime_type: str) -> str:
    extension = PurePath(filename).suffix.lower()
    canonical = MIME_BY_EXTENSION.get(extension)
    if canonical is None:
        raise HTTPException(
            status_code=422, detail="Only PDF, XLSX and CSV files are allowed"
        )
    allowed = CSV_BROWSER_MIMES if extension == ".csv" else {canonical}
    if mime_type not in allowed:
        raise HTTPException(
            status_code=422, detail="File type does not match its extension"
        )
    return canonical


async def _documents(
    client: httpx.AsyncClient, url: str, key: str, params: dict[str, str]
) -> list[dict[str, Any]]:
    response = await client.get(
        f"{url}/rest/v1/documents",
        params=params,
        headers=_service_headers(key),
    )
    result = _upstream(response)
    if not isinstance(result, list):
        raise HTTPException(status_code=502, detail="Invalid database response")
    return result


async def _cleanup_expired(
    client: httpx.AsyncClient, url: str, key: str, user_id: str
) -> None:
    cutoff = (datetime.now(UTC) - RESERVATION_LIFETIME).isoformat()
    stale = await _documents(
        client,
        url,
        key,
        {
            "select": "id,storage_path",
            "user_id": f"eq.{user_id}",
            "status": "eq.reserved",
            "created_at": f"lt.{cutoff}",
            "limit": "20",
        },
    )
    for document in stale:
        row_url = f"{url}/rest/v1/documents"
        match = {
            "id": f"eq.{document['id']}",
            "user_id": f"eq.{user_id}",
            "status": "eq.reserved",
            "created_at": f"lt.{cutoff}",
            "select": "id",
        }
        claim = await client.patch(
            row_url,
            params=match,
            headers=_service_headers(key, return_rows=True),
            json={"status": "deleting"},
        )
        if not _upstream(claim):
            continue
        removal = await client.request(
            "DELETE",
            f"{url}/storage/v1/object/{BUCKET}",
            headers=_service_headers(key),
            json={"prefixes": [document["storage_path"]]},
        )
        if removal.is_error:
            await client.patch(
                row_url,
                params={"id": f"eq.{document['id']}", "user_id": f"eq.{user_id}"},
                headers=_service_headers(key),
                json={"status": "delete_failed"},
            )
            continue
        deletion = await client.delete(
            row_url,
            params={
                "id": f"eq.{document['id']}",
                "user_id": f"eq.{user_id}",
                "status": "eq.deleting",
            },
            headers=_service_headers(key),
        )
        _upstream(deletion)


@router.post("", status_code=201)
async def reserve_document(
    payload: ReservationRequest, user_id: UserId
) -> dict[str, str]:
    canonical_mime = _canonical_mime(payload.filename, payload.mime_type)
    url, _, key = _configuration()
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            await _cleanup_expired(client, url, key, user_id)
            matches = await _documents(
                client,
                url,
                key,
                {
                    "select": "id,storage_path,status,file_size,mime_type",
                    "user_id": f"eq.{user_id}",
                    "sha256": f"eq.{payload.sha256}",
                    "order": "created_at.desc",
                    "limit": "20",
                },
            )
            for match in matches:
                if match["status"] != "reserved":
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "This file is already uploaded",
                            "document_id": match["id"],
                        },
                    )
                if (
                    match["file_size"] == payload.file_size
                    and match["mime_type"] == canonical_mime
                ):
                    return {
                        "document_id": match["id"],
                        "storage_path": match["storage_path"],
                        "status": "reserved",
                    }
            document_id = str(uuid4())
            storage_path = f"{user_id}/{document_id}/{_safe_filename(payload.filename)}"
            response = await client.post(
                f"{url}/rest/v1/documents",
                headers=_service_headers(key, return_rows=True),
                json={
                    "id": document_id,
                    "user_id": user_id,
                    "original_filename": payload.filename,
                    "storage_path": storage_path,
                    "mime_type": canonical_mime,
                    "file_size": payload.file_size,
                    "sha256": payload.sha256,
                    "status": "reserved",
                },
            )
            _upstream(response)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="Document service is unavailable"
        ) from exc
    return {
        "document_id": document_id,
        "storage_path": storage_path,
        "status": "reserved",
    }


@router.get("")
async def list_documents(user_id: UserId) -> list[dict[str, Any]]:
    url, _, key = _configuration()
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            await _cleanup_expired(client, url, key, user_id)
            return await _documents(
                client,
                url,
                key,
                {
                    "select": (
                        "id,original_filename,mime_type,file_size,status,created_at"
                    ),
                    "user_id": f"eq.{user_id}",
                    "status": "neq.deleting",
                    "order": "created_at.desc",
                    "limit": "50",
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="Document service is unavailable"
        ) from exc


@router.post("/{document_id}/complete")
async def complete_document(document_id: UUID, user_id: UserId) -> dict[str, str]:
    url, _, key = _configuration()
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            documents = await _documents(
                client,
                url,
                key,
                {
                    "select": "id,storage_path,mime_type,file_size,status,created_at",
                    "id": f"eq.{document_id}",
                    "user_id": f"eq.{user_id}",
                    "limit": "1",
                },
            )
            if not documents:
                raise HTTPException(status_code=404, detail="Document not found")
            document = documents[0]
            if document["status"] == "uploaded":
                return {"document_id": str(document_id), "status": "uploaded"}
            if document["status"] != "reserved":
                raise HTTPException(
                    status_code=409, detail="Document is not awaiting upload"
                )
            created_at = datetime.fromisoformat(
                document["created_at"].replace("Z", "+00:00")
            )
            if datetime.now(UTC) - created_at >= RESERVATION_LIFETIME:
                raise HTTPException(
                    status_code=410, detail="Upload reservation expired. Start again"
                )
            path = document["storage_path"]
            if not path.startswith(f"{user_id}/{document_id}/"):
                raise HTTPException(
                    status_code=409, detail="Invalid document storage path"
                )
            info = await client.get(
                f"{url}/storage/v1/object/info/{BUCKET}/{quote(path, safe='/')}",
                headers=_service_headers(key),
            )
            if info.status_code == 404:
                raise HTTPException(status_code=409, detail="Upload has not finished")
            object_info = _upstream(info)
            metadata = object_info.get("metadata") or {}
            size = object_info.get("size", metadata.get("size"))
            mime = object_info.get("content_type", metadata.get("mimetype"))
            if str(size) != str(document["file_size"]) or mime != document["mime_type"]:
                raise HTTPException(
                    status_code=409,
                    detail="Uploaded file does not match the reservation",
                )
            update = await client.patch(
                f"{url}/rest/v1/documents",
                params={
                    "id": f"eq.{document_id}",
                    "user_id": f"eq.{user_id}",
                    "status": "eq.reserved",
                    "select": "id",
                },
                headers=_service_headers(key, return_rows=True),
                json={"status": "uploaded"},
            )
            if not _upstream(update):
                raise HTTPException(
                    status_code=409, detail="Document state changed. Refresh the page"
                )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="Document service is unavailable"
        ) from exc
    return {"document_id": str(document_id), "status": "uploaded"}
