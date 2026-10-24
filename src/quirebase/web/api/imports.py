from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from advanced_alchemy.service import OffsetPagination
from fastapi import APIRouter, File, Form, Query, UploadFile, status

from quirebase.library import (
    ImportBatchPreview,
    ImportBatchSummary,
    commit_import_batch,
    delete_import_batch,
    get_import_batch_preview,
    list_import_batches,
    retry_pdf_import_batch,
    stage_identifiers_import_batch,
    stage_import_batch,
    stage_pdf_import_batch,
)
from quirebase.operations.settings import get_effective_settings_model
from quirebase.web.api.common import OkView
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.import_schemas import IdentifiersImportRequest, ImportCommitRequest
from quirebase.web.uploads import upload_chunks

router = APIRouter(tags=["Imports"])


@router.get("/imports", response_model=OffsetPagination[ImportBatchSummary])
async def import_batches(
    workspace_id: UUID,
    user: ApiUser,
    db: Database,
    view: Literal["pending", "completed"] = "pending",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = await list_import_batches(
        db, user, workspace_id, view=view, limit=limit, offset=offset
    )
    return OffsetPagination(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/imports/bibliography",
    response_model=ImportBatchPreview,
    status_code=status.HTTP_201_CREATED,
)
async def stage_bibliography_import(
    workspace_id: UUID,
    user: ApiUser,
    db: Database,
    bibliography: Annotated[UploadFile, File()],
    file_format: Annotated[str, Form()] = "auto",
):
    raw = await bibliography.read(5 * 1024 * 1024 + 1)
    return await stage_import_batch(db, user, workspace_id, raw, file_format)


@router.post(
    "/imports/identifiers",
    response_model=ImportBatchPreview,
    status_code=status.HTTP_201_CREATED,
)
async def stage_identifiers_import(
    workspace_id: UUID, data: IdentifiersImportRequest, user: ApiUser, db: Database
):
    return await stage_identifiers_import_batch(
        db,
        user,
        workspace_id,
        data.identifiers,
        data.provider,
        settings=await get_effective_settings_model(db),
    )


@router.post(
    "/imports/pdfs",
    response_model=ImportBatchPreview,
    status_code=status.HTTP_202_ACCEPTED,
)
async def stage_pdf_import(
    workspace_id: UUID,
    user: ApiUser,
    db: Database,
    pdfs: Annotated[list[UploadFile], File()],
):
    return await stage_pdf_import_batch(
        db,
        user,
        workspace_id,
        [(upload_chunks(pdf), pdf.filename or "") for pdf in pdfs],
        settings=await get_effective_settings_model(db),
    )


@router.get("/imports/{batch_id}", response_model=ImportBatchPreview)
async def import_batch(workspace_id: UUID, batch_id: UUID, user: ApiUser, db: Database):
    return await get_import_batch_preview(db, user, workspace_id, batch_id)


@router.post("/imports/{batch_id}/retry", response_model=ImportBatchPreview)
async def retry_import_batch(workspace_id: UUID, batch_id: UUID, user: ApiUser, db: Database):
    return await retry_pdf_import_batch(db, user, workspace_id, batch_id)


@router.post("/imports/{batch_id}/commit", response_model=ImportBatchPreview)
async def commit_staged_import(
    workspace_id: UUID,
    batch_id: UUID,
    user: ApiUser,
    db: Database,
    data: ImportCommitRequest | None = None,
) -> ImportBatchPreview:
    return await commit_import_batch(
        db,
        user,
        workspace_id,
        batch_id,
        basic_source_ids=data.basic_source_ids if data else (),
        expected_preview_version=data.expected_preview_version if data else None,
    )


@router.delete("/imports/{batch_id}", response_model=OkView)
async def delete_import(workspace_id: UUID, batch_id: UUID, user: ApiUser, db: Database) -> OkView:
    await delete_import_batch(db, user, workspace_id, batch_id)
    return OkView()
