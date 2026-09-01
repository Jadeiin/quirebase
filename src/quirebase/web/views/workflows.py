from __future__ import annotations

from fastapi import Depends

from quirebase.core.errors import ResourceNotFound
from quirebase.core.workflows import durable_operations
from quirebase.models import User
from quirebase.web.deps import current_user, protected_router

router = protected_router()


@router.get("/api/workflows/{workflow_id}")
async def workflow_status(
    workflow_id: str,
    user: User = Depends(current_user),
):
    workflow = await durable_operations().get(workflow_id)
    if workflow is None:
        raise ResourceNotFound("workflow not found")
    owner_id = (workflow.attributes or {}).get("owner_id")
    if user.role != "administrator" and owner_id != user.id:
        raise ResourceNotFound("workflow not found")
    return {"id": workflow.id, "state": workflow.state, "error": workflow.error}
