from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status

from quirebase.library import (
    commit_import_batch,
    discard_import_batch,
    get_import_batch_preview,
    retry_pdf_import_batch,
    stage_identifier_import_batch,
    stage_import_batch,
    stage_pdf_import_batch,
)
from quirebase.operations.settings import get_effective_settings_model
from quirebase.web.api.common import OkView
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.import_schemas import (
    IdentifierImportRequest,
    ImportBatchRetryView,
    ImportBatchView,
)
from quirebase.web.uploads import upload_chunks

router = APIRouter(tags=["Imports"])


def _import_batch_view(batch, records: list[dict], errors: list[dict]) -> dict:
    return {
        "id": batch.id,
        "file_format": batch.file_format,
        "status": batch.status,
        "workflow_id": batch.workflow_id,
        "records": records,
        "errors": errors,
        "created_at": batch.created_at,
    }


@router.post(
    "/imports/bibliography",
    response_model=ImportBatchView,
    status_code=status.HTTP_201_CREATED,
)
async def stage_bibliography_import(
    user: ApiUser,
    db: Database,
    bibliography: Annotated[UploadFile, File()],
    file_format: Annotated[str, Form()],
):
    raw = await bibliography.read(5 * 1024 * 1024 + 1)
    return _import_batch_view(*(await stage_import_batch(db, user, raw, file_format)))


@router.post(
    "/imports/identifier",
    response_model=ImportBatchView,
    status_code=status.HTTP_201_CREATED,
)
async def stage_identifier_import(data: IdentifierImportRequest, user: ApiUser, db: Database):
    result = await stage_identifier_import_batch(
        db,
        user,
        data.identifier,
        data.provider,
        settings=await get_effective_settings_model(db),
    )
    return _import_batch_view(*result)


@router.post(
    "/imports/pdfs",
    response_model=ImportBatchView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def stage_pdf_import(user: ApiUser, db: Database, pdfs: Annotated[list[UploadFile], File()]):
    result = await stage_pdf_import_batch(
        db,
        user,
        [(upload_chunks(pdf), pdf.filename or "") for pdf in pdfs],
        settings=await get_effective_settings_model(db),
    )
    return _import_batch_view(*result)


@router.get("/imports/{batch_id}", response_model=ImportBatchView)
async def import_batch(batch_id: str, user: ApiUser, db: Database):
    return _import_batch_view(*(await get_import_batch_preview(db, user, batch_id)))


@router.post("/imports/{batch_id}/retry", response_model=ImportBatchRetryView)
async def retry_import_batch(batch_id: str, user: ApiUser, db: Database):
    batch = await retry_pdf_import_batch(db, user, batch_id)
    return {"id": batch.id, "status": batch.status, "workflow_id": batch.workflow_id}


@router.post("/imports/{batch_id}/commit", response_model=OkView)
async def commit_staged_import(batch_id: str, user: ApiUser, db: Database) -> OkView:
    await commit_import_batch(db, user, batch_id)
    return OkView()


@router.delete("/imports/{batch_id}", response_model=OkView)
async def discard_staged_import(batch_id: str, user: ApiUser, db: Database) -> OkView:
    await discard_import_batch(db, user, batch_id)
    return OkView()
