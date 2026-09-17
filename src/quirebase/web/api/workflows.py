from __future__ import annotations

from fastapi import APIRouter

from quirebase.core.errors import ResourceNotFound
from quirebase.core.workflows import durable_operations
from quirebase.web.api.common import WorkflowStatusView
from quirebase.web.api.dependencies import ApiUser

router = APIRouter(prefix="/api/v1", tags=["Workflows"])


@router.get("/workflows/{workflow_id}", response_model=WorkflowStatusView)
async def workflow_status(workflow_id: str, user: ApiUser):
    workflow = await durable_operations().get(workflow_id)
    if workflow is None or (
        user.role != "administrator" and (workflow.attributes or {}).get("owner_id") != user.id
    ):
        raise ResourceNotFound("workflow not found")
    return {"id": workflow.id, "state": workflow.state, "error": workflow.error}
