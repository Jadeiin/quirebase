from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from quirebase.documents import (
    create_export_job,
    get_export_file,
    get_export_status,
)
from quirebase.documents.schemas import ExportCreate
from quirebase.library import (
    list_custom_citation_styles,
    preview_citation_key,
    select_builtin_citation_styles,
)
from quirebase.web.api.common import WorkflowStatusView
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.export_schemas import (
    AnnotationExportCreatedView,
    CitationKeyPreviewView,
)
from quirebase.web.api.library_schemas import CitationStylesResponseView

router = APIRouter(prefix="/api/v1", tags=["HTTP API"])


@router.get("/citation-key-preview", response_model=CitationKeyPreviewView)
async def citation_key_preview(
    formula: str,
    _user: ApiUser,
    force_ascii: bool = False,
):
    return {"key": preview_citation_key(formula, force_ascii=force_ascii)}


@router.get("/citation-styles", response_model=CitationStylesResponseView)
async def citation_styles(
    user: ApiUser,
    db: Database,
    query: str = "",
    limit: int = 50,
    include: str = "",
):
    normalized = query.strip().casefold()
    builtin_selection = select_builtin_citation_styles(query, limit=limit, include=include)
    owned_custom_styles = await list_custom_citation_styles(db, user)
    custom = [
        {"key": style.id, "name": style.name, "scope": "custom"}
        for style in owned_custom_styles
        if style.id != include and (not normalized or normalized in style.name.casefold())
    ]
    exact_custom = next(
        (
            {"key": style.id, "name": style.name, "scope": "custom"}
            for style in owned_custom_styles
            if include and style.id == include
        ),
        None,
    )
    included = []
    if builtin_selection.included is not None:
        included.append({
            "key": builtin_selection.included.key,
            "name": builtin_selection.included.name,
            "scope": "builtin",
        })
    if exact_custom is not None:
        included.append(exact_custom)
    styles = [
        {"key": style.key, "name": style.name, "scope": "builtin"}
        for style in builtin_selection.matches
    ][:limit] + custom[:limit]
    included = [
        style for style in included if not any(style["key"] == item["key"] for item in styles)
    ]
    return {
        "styles": styles + included,
    }


@router.post(
    "/items/{item_id}/annotation-exports",
    response_model=AnnotationExportCreatedView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_export(
    item_id: str,
    data: ExportCreate,
    user: ApiUser,
    db: Database,
):
    workflow_id = await create_export_job(db, user, item_id, data)
    return {
        "id": workflow_id,
        "state": "pending",
        "status_url": f"/api/v1/annotation-exports/{workflow_id}",
    }


@router.get("/annotation-exports/{workflow_id}", response_model=WorkflowStatusView)
async def export_status(workflow_id: str, user: ApiUser, db: Database):
    return await get_export_status(db, user, workflow_id)


@router.get(
    "/annotation-exports/{workflow_id}/content",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
async def export_content(workflow_id: str, user: ApiUser, db: Database):
    response = await get_export_file(db, user, workflow_id)
    return StreamingResponse(
        response.body,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="annotated.pdf"'},
    )
