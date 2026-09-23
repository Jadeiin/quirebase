from __future__ import annotations

from fastapi import APIRouter

from quirebase.access import Capability, require_workspace_capability
from quirebase.core.errors import ResourceNotFound
from quirebase.core.workflows import durable_operations
from quirebase.web.api.common import WorkflowStatusView
from quirebase.web.api.dependencies import ApiUser, Database

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Workflows"])


@router.get("/workflows/{workflow_id}", response_model=WorkflowStatusView)
async def workflow_status(workspace_id: str, workflow_id: str, user: ApiUser, db: Database):
    await require_workspace_capability(db, user, workspace_id, Capability.workspace_read)
    workflow = await durable_operations().get(workflow_id)
    attributes = workflow.attributes if workflow else None
    if (
        workflow is None
        or not attributes
        or attributes.get("workspace_id") != workspace_id
        or attributes.get("actor_id") != user.id
    ):
        raise ResourceNotFound("workflow not found")
    return {"id": workflow.id, "state": workflow.state, "error": workflow.error}
