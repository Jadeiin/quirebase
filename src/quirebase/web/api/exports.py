from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from quirebase.documents import (
    create_export_job,
    get_export_file,
    get_export_status,
)
from quirebase.documents.schemas import ExportCreate
from quirebase.web.api.common import WorkflowStatusView
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.export_schemas import AnnotationExportCreatedView

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Document exports"])


@router.post(
    "/items/{item_id}/annotation-exports",
    response_model=AnnotationExportCreatedView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_export(
    workspace_id: str,
    item_id: str,
    data: ExportCreate,
    user: ApiUser,
    db: Database,
):
    workflow_id = await create_export_job(db, user, workspace_id, item_id, data)
    return {
        "id": workflow_id,
        "state": "pending",
        "status_url": f"/api/v1/workspaces/{workspace_id}/annotation-exports/{workflow_id}",
    }


@router.get("/annotation-exports/{workflow_id}", response_model=WorkflowStatusView)
async def export_status(workspace_id: str, workflow_id: str, user: ApiUser, db: Database):
    return await get_export_status(db, user, workspace_id, workflow_id)


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
async def export_content(workspace_id: str, workflow_id: str, user: ApiUser, db: Database):
    response = await get_export_file(db, user, workspace_id, workflow_id)
    return StreamingResponse(
        response.body,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="annotated.pdf"',
            "Cache-Control": "private, no-store",
        },
    )
