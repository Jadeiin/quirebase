from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

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
from quirebase.library import admin_delete_item, get_storage_metrics, list_global_items
from quirebase.models import User
from quirebase.operations import (
    dispatch_maintenance_workflow,
    get_backup_artifact,
    get_runtime_settings,
    update_runtime_settings,
)
from quirebase.projects import list_projects_for_admin
from quirebase.web.api.admin_schemas import (
    AdminAuditView,
    AdminInvitationCreatedView,
    AdminItemsView,
    AdminMaintenanceView,
    AdminOverviewView,
    AdminProjectsView,
    AdminSettingsView,
    AdminUserCreateRequest,
    AdminUsersView,
    AdminUserView,
    AdminWorkflowsView,
    InvitationCreateRequest,
    PasswordResetRequest,
    RuntimeSettingsRequest,
    UserRoleRequest,
    UserStatusRequest,
    WorkflowSummaryView,
)
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.library_schemas import item_search_view
from quirebase.web.api.serialization import enum_value


def require_api_admin(user: ApiUser) -> User:
    if user.role != "administrator":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    return user


AdminUser = Annotated[User, Depends(require_api_admin)]
router = APIRouter(
    prefix="/api/v1/admin",
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
        "recent_events": [
            {
                "id": event.id,
                "actor_id": event.actor_id,
                "action": event.action,
                "target_type": event.target_type,
                "target_id": event.target_id,
                "detail": event.detail,
                "created_at": event.created_at,
            }
            for event in events
        ],
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


@router.get("/projects", response_model=AdminProjectsView)
async def admin_projects(
    user: AdminUser,
    db: Database,
    search: str = "",
    state: str = "",
    visibility: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
):
    projects, total = await list_projects_for_admin(
        db,
        user,
        search=search,
        state=state,
        visibility=visibility,
        page=page,
        page_size=20,
    )
    return {
        "projects": [
            {
                "id": row.project.id,
                "name": row.project.name,
                "description": row.project.description,
                "state": enum_value(row.project.state),
                "visibility": enum_value(row.project.visibility),
                "creator": {"id": row.creator.id, "username": row.creator.username},
                "member_count": row.member_count,
                "item_count": row.item_count,
            }
            for row in projects
        ],
        "total": total,
        "page": page,
        "per_page": 20,
    }


@router.get("/items", response_model=AdminItemsView)
async def admin_items(
    user: AdminUser,
    db: Database,
    search: str = "",
    has_pdf: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
):
    items, total = await list_global_items(
        db, user, search=search, has_pdf=has_pdf, page=page, page_size=20
    )
    return {
        "items": [item_search_view(item) for item in items],
        "total": total,
        "page": page,
        "per_page": 20,
        "storage": await get_storage_metrics(db, user),
    }


@router.delete("/items/{item_id}", response_model=OkView)
async def admin_remove_item(item_id: str, user: AdminUser, db: Database) -> OkView:
    await admin_delete_item(db, user, item_id)
    return OkView()


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
        "events": [
            {
                "id": event.id,
                "actor_id": event.actor_id,
                "action": event.action,
                "target_type": event.target_type,
                "target_id": event.target_id,
                "detail": event.detail,
                "created_at": event.created_at,
            }
            for event in events
        ],
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


@router.post("/maintenance/{operation}", response_model=WriteResult)
async def run_maintenance(
    operation: Literal["reindex_all", "check_objects", "backup", "recommend_tags_all"],
    user: AdminUser,
    db: Database,
) -> WriteResult:
    return WriteResult(id=await dispatch_maintenance_workflow(db, user, operation))


@router.get(
    "/maintenance/backups/{workflow_id}/content",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def download_backup(workflow_id: str, user: AdminUser, db: Database) -> FileResponse:
    path, filename = await get_backup_artifact(db, user, workflow_id)
    return FileResponse(str(path), media_type="application/zip", filename=filename)


@router.get("/workflows/{workflow_id}", response_model=WorkflowSummaryView)
async def workflow_status(workflow_id: str, user: AdminUser):
    del user
    workflow = await durable_operations().get(workflow_id)
    if workflow is None:
        raise ResourceNotFound("workflow not found")
    return _workflow_view(workflow)
