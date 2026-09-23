from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from quirebase.accounts import (
    change_user_role,
    create_invitation,
    create_user_admin,
    list_invitations,
    list_users,
    list_users_paginated,
    reset_user_password,
    revoke_user_sessions,
    update_user_status,
)
from quirebase.audit import query_events
from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.core.workflows import durable_operations
from quirebase.library import get_storage_metrics
from quirebase.models import User
from quirebase.operations import (
    dispatch_maintenance_workflow,
    get_runtime_settings,
    update_runtime_settings,
)
from quirebase.web.api.admin_schemas import (
    AdminAuditView,
    AdminInvitationCreatedView,
    AdminMaintenanceView,
    AdminOverviewView,
    AdminSettingsView,
    AdminUserCreateRequest,
    AdminUsersView,
    AdminUserView,
    AdminWorkflowsView,
    AdminWorkspaceView,
    BreakGlassReadRequest,
    InvitationCreateRequest,
    PasswordResetRequest,
    RuntimeSettingsRequest,
    UserRoleRequest,
    UserStatusRequest,
    WorkflowSummaryView,
)
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.library_schemas import ItemSearchView, item_search_view
from quirebase.web.errors import ApiHTTPException
from quirebase.workspaces import (
    list_workspaces_for_governance,
    read_workspace_items_break_glass,
    recover_workspace_governance,
    suspend_workspace_governance,
)


def require_api_admin(user: ApiUser) -> User:
    if user.role != "administrator":
        raise ApiHTTPException(
            status.HTTP_404_NOT_FOUND,
            "not_found",
            "resource not found",
        )
    return user


AdminUser = Annotated[User, Depends(require_api_admin)]
router = APIRouter(
    prefix="/admin",
    tags=["HTTP API administration"],
)


def _user_view(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "active": user.active,
        "created_at": user.created_at,
    }


def _workflow_view(workflow) -> dict:
    return asdict(workflow)


def _audit_view(event) -> dict:
    target_ids = None
    if event.target_ids:
        try:
            parsed = json.loads(event.target_ids)
            if isinstance(parsed, list) and all(isinstance(value, str) for value in parsed):
                target_ids = parsed
        except (TypeError, ValueError):
            # Audit metadata is intentionally best-effort JSON.  Preserve the
            # event itself even if an old/internal writer stored malformed text.
            target_ids = None
    detail = event.detail
    if detail:
        with suppress(TypeError, ValueError):
            detail = json.loads(detail)
    return {
        "id": event.id,
        "actor_id": event.actor_id,
        "workspace_id": event.workspace_id,
        "project_id": event.project_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "target_ids": target_ids,
        "authorization_role": event.authorization_role,
        "authorization_capability": event.authorization_capability,
        "result": event.result,
        "source": event.source,
        "detail": detail,
        "created_at": event.created_at,
    }


@router.get("/overview", response_model=AdminOverviewView)
async def admin_overview(user: AdminUser, db: Database):
    users = await list_users(db, user)
    invitations = await list_invitations(db, user)
    failed = await durable_operations().list(status="failed", limit=100)
    events, _ = await query_events(db, user, page=1, page_size=10)
    return {
        "user_count": len(users),
        "pending_invitation_count": sum(
            invitation.accepted_at is None for invitation in invitations
        ),
        "failed_workflows": [_workflow_view(workflow) for workflow in failed],
        "storage": await get_storage_metrics(db, user),
        "recent_events": [_audit_view(event) for event in events],
    }


@router.get("/users", response_model=AdminUsersView)
async def admin_users(
    user: AdminUser,
    db: Database,
    search: str = "",
    role: str = "",
    active: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
):
    users, total = await list_users_paginated(
        db, user, search=search, role=role, active=active, page=page, page_size=20
    )
    invitations = await list_invitations(db, user)
    return {
        "users": [_user_view(row) for row in users],
        "total": total,
        "page": page,
        "per_page": 20,
        "invitations": [
            {
                "id": invitation.id,
                "username": invitation.username,
                "role": invitation.role,
                "expires_at": invitation.expires_at,
                "accepted_at": invitation.accepted_at,
            }
            for invitation in invitations
        ],
    }


@router.post("/users", response_model=AdminUserView, status_code=status.HTTP_201_CREATED)
async def admin_create_user(data: AdminUserCreateRequest, user: AdminUser, db: Database):
    return _user_view(await create_user_admin(db, user, data.username, data.password, data.role))


@router.put("/users/{user_id}/status", response_model=AdminUserView)
async def admin_update_user_status(
    user_id: str, data: UserStatusRequest, user: AdminUser, db: Database
):
    return _user_view(await update_user_status(db, user, user_id, data.active))


@router.put("/users/{user_id}/role", response_model=AdminUserView)
async def admin_update_user_role(
    user_id: str, data: UserRoleRequest, user: AdminUser, db: Database
):
    return _user_view(await change_user_role(db, user, user_id, data.role))


@router.put("/users/{user_id}/password", response_model=OkView)
async def admin_reset_password(
    user_id: str, data: PasswordResetRequest, user: AdminUser, db: Database
) -> OkView:
    await reset_user_password(db, user, user_id, data.password)
    return OkView()


@router.delete("/users/{user_id}/sessions", response_model=OkView)
async def admin_revoke_sessions(user_id: str, user: AdminUser, db: Database) -> OkView:
    await revoke_user_sessions(db, user, user_id)
    return OkView()


@router.post(
    "/invitations", response_model=AdminInvitationCreatedView, status_code=status.HTTP_201_CREATED
)
async def admin_create_invitation(data: InvitationCreateRequest, user: AdminUser, db: Database):

    invitation, token = await create_invitation(db, user, data.username, data.role)
    return {
        "id": invitation.id,
        "username": invitation.username,
        "role": invitation.role,
        "expires_at": invitation.expires_at,
        "token": token,
        "accept_path": f"/invitation/{token}",
    }


@router.get("/audit", response_model=AdminAuditView)
async def admin_audit(
    user: AdminUser,
    db: Database,
    search: str = "",
    actor_id: str = "",
    action: str = "",
    target_type: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
):
    events, total = await query_events(
        db,
        user,
        actor_id=actor_id.strip() or None,
        action=action.strip() or None,
        target_type=target_type.strip() or None,
        search=search,
        page=page,
        page_size=50,
    )
    return {
        "events": [_audit_view(event) for event in events],
        "total": total,
        "page": page,
        "per_page": 50,
    }


@router.get("/workflows", response_model=AdminWorkflowsView)
async def admin_workflows(user: AdminUser, state: str = ""):
    del user
    normalized = state.strip().casefold()
    if normalized not in {"", "pending", "running", "succeeded", "failed", "cancelled"}:
        raise ValidationFailure(f"unknown workflow state: {state}")
    return {
        "workflows": [
            _workflow_view(row)
            for row in await durable_operations().list(status=normalized, limit=100)
        ]
    }


@router.get("/settings", response_model=AdminSettingsView)
async def admin_settings(user: AdminUser, db: Database):
    del user
    return await get_runtime_settings(db)


@router.put("/settings", response_model=OkView)
async def admin_update_settings(
    data: RuntimeSettingsRequest, user: AdminUser, db: Database
) -> OkView:
    await update_runtime_settings(db, user, data.model_dump())
    return OkView()


@router.get("/maintenance", response_model=AdminMaintenanceView)
async def admin_maintenance(user: AdminUser, db: Database):
    workflows = await durable_operations().list(limit=100)
    return {
        "storage": await get_storage_metrics(db, user),
        "workflows": [
            _workflow_view(workflow)
            for workflow in workflows
            if (workflow.attributes or {}).get("capability") == "operations"
        ][:20],
    }


@router.get("/workspaces", response_model=list[AdminWorkspaceView])
async def admin_workspaces(user: AdminUser, db: Database) -> list[AdminWorkspaceView]:
    return [
        AdminWorkspaceView(
            id=workspace.id,
            name=workspace.name,
            owner_id=workspace.owner_id,
            state=workspace.state.value,
            governance_suspended_at=workspace.governance_suspended_at,
            governance_suspended_by=workspace.governance_suspended_by,
        )
        for workspace in await list_workspaces_for_governance(db, user)
    ]


@router.post("/workspaces/{workspace_id}/suspend", response_model=OkView)
async def admin_suspend_workspace(workspace_id: str, user: AdminUser, db: Database) -> OkView:
    await suspend_workspace_governance(db, user, workspace_id)
    return OkView()


@router.post("/workspaces/{workspace_id}/recover", response_model=OkView)
async def admin_recover_workspace(workspace_id: str, user: AdminUser, db: Database) -> OkView:
    await recover_workspace_governance(db, user, workspace_id)
    return OkView()


@router.post(
    "/workspaces/{workspace_id}/break-glass/items",
    response_model=list[ItemSearchView],
)
async def admin_break_glass_items(
    workspace_id: str,
    data: BreakGlassReadRequest,
    user: AdminUser,
    db: Database,
) -> list[ItemSearchView]:
    return [
        item_search_view(item)
        for item in await read_workspace_items_break_glass(db, user, workspace_id, data.reason)
    ]


@router.post("/maintenance/{operation}", response_model=WriteResult)
async def run_maintenance(
    operation: Literal["check_objects"],
    user: AdminUser,
    db: Database,
) -> WriteResult:
    return WriteResult(id=await dispatch_maintenance_workflow(db, user, operation))


@router.get("/workflows/{workflow_id}", response_model=WorkflowSummaryView)
async def workflow_status(workflow_id: str, user: AdminUser):
    del user
    workflow = await durable_operations().get(workflow_id)
    if workflow is None:
        raise ResourceNotFound("workflow not found")
    return _workflow_view(workflow)
