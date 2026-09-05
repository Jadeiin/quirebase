from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Response
from fastapi.responses import JSONResponse

from quirebase.core.database import get_db
from quirebase.documents import (
    create_annotation_reply,
    create_document_annotation,
    delete_annotation_reply,
    delete_document_annotation,
    list_document_annotations,
    restore_annotation_reply,
    restore_document_annotation,
    update_annotation_reply,
    update_document_annotation,
)
from quirebase.documents.schemas import (
    AnnotationCreate,
    AnnotationReplyCreate,
    AnnotationReplyUpdate,
    AnnotationUpdate,
)
from quirebase.models import User
from quirebase.web.deps import current_user, protected_router

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = protected_router()


@router.get("/documents/{item_id}/annotations")
async def list_annotations(
    item_id: str,
    revision_id: str,
    project_id: str | None = None,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    annotations = await list_document_annotations(
        db, user, item_id, revision_id, project_id=project_id
    )
    return {"annotations": annotations}


@router.post("/documents/{item_id}/annotations")
async def create_annotation(
    item_id: str,
    data: AnnotationCreate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await create_document_annotation(db, user, item_id, data)
    return JSONResponse(result, status_code=201)


@router.patch("/documents/{item_id}/annotations/{annotation_id}")
async def update_annotation(
    item_id: str,
    annotation_id: str,
    data: AnnotationUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    return await update_document_annotation(db, user, item_id, annotation_id, data)


@router.delete("/documents/{item_id}/annotations/{annotation_id}")
async def delete_annotation(
    item_id: str,
    annotation_id: str,
    version: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_document_annotation(db, user, item_id, annotation_id, version)
    return Response(status_code=204)


@router.post("/documents/{item_id}/annotations/{annotation_id}/restore")
async def restore_annotation(
    item_id: str,
    annotation_id: str,
    version: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    return await restore_document_annotation(db, user, item_id, annotation_id, version)


@router.post("/documents/{item_id}/annotations/{annotation_id}/replies")
async def create_reply(
    item_id: str,
    annotation_id: str,
    data: AnnotationReplyCreate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await create_annotation_reply(db, user, item_id, annotation_id, data)
    return JSONResponse(result, status_code=201)


@router.patch("/documents/{item_id}/annotations/{annotation_id}/replies/{reply_id}")
async def update_reply(
    item_id: str,
    annotation_id: str,
    reply_id: str,
    data: AnnotationReplyUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    return await update_annotation_reply(db, user, item_id, annotation_id, reply_id, data)


@router.delete("/documents/{item_id}/annotations/{annotation_id}/replies/{reply_id}")
async def delete_reply(
    item_id: str,
    annotation_id: str,
    reply_id: str,
    version: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_annotation_reply(db, user, item_id, annotation_id, reply_id, version)
    return Response(status_code=204)


@router.post("/documents/{item_id}/annotations/{annotation_id}/replies/{reply_id}/restore")
async def restore_reply(
    item_id: str,
    annotation_id: str,
    reply_id: str,
    version: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    return await restore_annotation_reply(db, user, item_id, annotation_id, reply_id, version)
