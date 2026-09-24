"""Compose the versioned HTTP API from capability-owned routers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from quirebase.core.errors import ResourceUnavailable, WorkspaceContextRequired
from quirebase.web.api.account import router as account_router
from quirebase.web.api.admin import router as admin_router
from quirebase.web.api.dependencies import ApiUser
from quirebase.web.api.session import router as session_router
from quirebase.web.api.workspace_routes import router as workspace_api_router
from quirebase.web.api.workspaces import router as workspaces_router
from quirebase.web.api.workspaces import workspace_root_router

if TYPE_CHECKING:
    from fastapi.routing import APIRoute


def generate_operation_id(route: APIRoute) -> str:
    """Generate the API contract ID from its capability module and endpoint name."""
    module = route.endpoint.__module__.rsplit(".", 1)[-1]
    return f"{module}.{route.endpoint.__name__}"


CAPABILITY_ROUTERS = (
    session_router,
    workspaces_router,
    workspace_root_router,
    account_router,
    admin_router,
    workspace_api_router,
)

router = APIRouter(
    prefix="/api/v1",
    generate_unique_id_function=generate_operation_id,
)
for capability_router in CAPABILITY_ROUTERS:
    router.include_router(capability_router)


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
