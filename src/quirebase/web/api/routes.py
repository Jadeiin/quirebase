"""Compose the versioned HTTP API from capability-owned routers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from quirebase.core.errors import ResourceUnavailable, WorkspaceContextRequired
from quirebase.web.api.account import router as account_router
from quirebase.web.api.admin import router as admin_router
from quirebase.web.api.annotations import router as annotations_router
from quirebase.web.api.citations import router as citations_router
from quirebase.web.api.dashboard import router as dashboard_router
from quirebase.web.api.dependencies import ApiUser, current_api_workspace
from quirebase.web.api.discovery import router as discovery_router
from quirebase.web.api.documents import router as documents_router
from quirebase.web.api.exports import router as exports_router
from quirebase.web.api.imports import router as imports_router
from quirebase.web.api.items import router as items_router
from quirebase.web.api.library import router as library_router
from quirebase.web.api.library_exports import router as library_exports_router
from quirebase.web.api.projects import router as projects_router
from quirebase.web.api.session import router as session_router
from quirebase.web.api.tools import router as tools_router
from quirebase.web.api.workflows import router as workflows_router
from quirebase.web.api.workspaces import router as workspaces_router

if TYPE_CHECKING:
    from fastapi.routing import APIRoute


def generate_operation_id(route: APIRoute) -> str:
    """Generate the API contract ID from its capability module and endpoint name."""
    module = route.endpoint.__module__.rsplit(".", 1)[-1]
    return f"{module}.{route.endpoint.__name__}"


CAPABILITY_ROUTERS = (
    session_router,
    workspaces_router,
    dashboard_router,
    library_router,
    library_exports_router,
    imports_router,
    projects_router,
    annotations_router,
    discovery_router,
    workflows_router,
    account_router,
    admin_router,
    citations_router,
    documents_router,
    exports_router,
    items_router,
    tools_router,
)

WORKSPACE_ROUTERS = (
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
    prefix="/api/v1",
    generate_unique_id_function=generate_operation_id,
)
for capability_router in CAPABILITY_ROUTERS:
    dependencies = (
        [Depends(current_api_workspace)] if capability_router in WORKSPACE_ROUTERS else None
    )
    router.include_router(capability_router, dependencies=dependencies)


_WORKSPACE_RESOURCE_ROOTS = frozenset({
    "annotation-exports",
    "authors",
    "bibliography",
    "citation-key-preview",
    "citation-styles",
    "dashboard",
    "discovery",
    "duplicates",
    "exports",
    "imports",
    "items",
    "projects",
    "tags",
    "workflows",
})


@router.api_route(
    "/{unscoped_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
def reject_missing_workspace_context(unscoped_path: str, user: ApiUser) -> None:
    """Give authenticated callers a typed error for formerly unscoped resource paths."""
    del user
    root = unscoped_path.partition("/")[0]
    if root in _WORKSPACE_RESOURCE_ROOTS:
        raise WorkspaceContextRequired("explicit workspace_id path context is required")
    raise ResourceUnavailable("not found")
