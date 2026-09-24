"""Aggregate all Workspace-scoped HTTP capabilities behind one context boundary."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from quirebase.web.api.annotations import router as annotations_router
from quirebase.web.api.citations import router as citations_router
from quirebase.web.api.dashboard import router as dashboard_router
from quirebase.web.api.dependencies import current_api_workspace
from quirebase.web.api.discovery import router as discovery_router
from quirebase.web.api.documents import router as documents_router
from quirebase.web.api.exports import router as exports_router
from quirebase.web.api.imports import router as imports_router
from quirebase.web.api.items import router as items_router
from quirebase.web.api.library import router as library_router
from quirebase.web.api.library_exports import router as library_exports_router
from quirebase.web.api.projects import router as projects_router
from quirebase.web.api.tools import router as tools_router
from quirebase.web.api.workflows import router as workflows_router
from quirebase.web.api.workspaces import workspace_router as workspace_governance_router

WORKSPACE_ROUTERS = (
    workspace_governance_router,
    dashboard_router,
    library_router,
    library_exports_router,
    imports_router,
    projects_router,
    annotations_router,
    discovery_router,
    workflows_router,
    citations_router,
    documents_router,
    exports_router,
    items_router,
    tools_router,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}",
    dependencies=[Depends(current_api_workspace)],
)
for workspace_router in WORKSPACE_ROUTERS:
    router.include_router(workspace_router)
