from __future__ import annotations

from typing import Annotated
from uuid import UUID

from advanced_alchemy.service import OffsetPagination
from fastapi import APIRouter, Query, status
from sqlalchemy import select

from quirebase.access import (
    ResourceAction,
    require_action,
    workspace_decisions,
    workspace_invitation_roles,
    workspace_member_decisions,
    workspace_member_roles,
    workspace_project_participations,
)
from quirebase.core.errors import ResourceNotFound
from quirebase.models import User
from quirebase.operations import dispatch_workspace_reindex
from quirebase.web.api.common import OkView, WriteResult, authorization_view
from quirebase.web.api.dependencies import ApiUser, Database, WorkspaceAccess
from quirebase.web.api.workspace_schemas import (
    WorkspaceCreateRequest,
    WorkspaceCreationAvailabilityView,
    WorkspaceGovernanceMemberView,
    WorkspaceInvitationAcceptanceView,
    WorkspaceInvitationCreatedView,
    WorkspaceInvitationRequest,
    WorkspaceInvitationView,
    WorkspaceMemberDirectoryView,
    WorkspaceRoleRequest,
    WorkspaceUpdateRequest,
    WorkspaceView,
)
from quirebase.workspaces import (
    accept_workspace_invitation_by_token,
    archive_workspace,
    create_workspace,
    invite_workspace_member,
    list_workspace_governance_members,
    list_workspace_invitations,
    list_workspace_members,
    list_workspaces,
    permanently_delete_workspace,
    reactivate_workspace_member,
    restore_workspace,
    revoke_workspace_invitation,
    set_workspace_member_role,
    suspend_workspace_member,
    terminate_workspace_member,
    transfer_workspace_ownership,
    update_workspace,
    workspace_creation_options,
    workspace_owner_ids,
)

router = APIRouter(tags=["Workspaces"])
workspace_root_router = APIRouter(tags=["Workspaces"])
workspace_router = APIRouter(tags=["Workspaces"])


def _workspace_view(workspace, member, *, owner_id: UUID) -> WorkspaceView:
    projection = workspace_decisions(
        member.role,
        workspace.state,
        governance_suspended=workspace.governance_suspended_at is not None,
    )
    return WorkspaceView(
        id=workspace.id,
        name=workspace.name,
        owner_id=owner_id,
        state=workspace.state,
        current_role=member.role,
        governance_suspended=workspace.governance_suspended_at is not None,
        allowed_project_participations=list(
            workspace_project_participations(
                member.role,
                workspace.state,
                governance_suspended=workspace.governance_suspended_at is not None,
            )
        ),
        allowed_invitation_roles=list(
            workspace_invitation_roles(
                member.role,
                workspace.state,
                governance_suspended=workspace.governance_suspended_at is not None,
            )
        ),
        authorization=authorization_view(projection),
    )


async def _usernames(db, user_ids: set[UUID]) -> dict[UUID, str]:
    if not user_ids:
        return {}
    rows = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
    return dict(rows.all())


@router.get("/workspaces", response_model=OffsetPagination[WorkspaceView])
async def get_workspaces(
    user: ApiUser,
    db: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: str = "",
) -> OffsetPagination[WorkspaceView]:
    rows, total = await list_workspaces(db, user, limit=limit, offset=offset, search=search)
    owner_ids = await workspace_owner_ids(db, {workspace.id for workspace, _ in rows})
    items = [
        _workspace_view(workspace, member, owner_id=owner_ids[workspace.id])
        for workspace, member in rows
        if workspace.id in owner_ids
    ]
    return OffsetPagination(items=items, total=total, limit=limit, offset=offset)


@router.get("/workspaces/creation-availability", response_model=WorkspaceCreationAvailabilityView)
async def get_workspace_creation_availability(
    user: ApiUser, db: Database
) -> WorkspaceCreationAvailabilityView:
    options = await workspace_creation_options(db, user)
    return WorkspaceCreationAvailabilityView(
        allowed=options.allowed,
        owner_username_required=options.owner_username_required,
    )


@workspace_root_router.get("/workspaces/{workspace_id}", response_model=WorkspaceView)
async def get_user_workspace(
    workspace_id: UUID, context: WorkspaceAccess, db: Database
) -> WorkspaceView:
    if context.workspace_id != workspace_id:
        raise ResourceNotFound("Workspace not found")
    require_action(context, ResourceAction.workspace_read)
    owner_ids = await workspace_owner_ids(db, {workspace_id})
    owner_id = owner_ids.get(workspace_id)
    if owner_id is None:
        raise ResourceNotFound("Workspace not found")
    return _workspace_view(
        context.workspace,
        context.membership,
        owner_id=owner_id,
    )


@router.post("/workspaces", response_model=WriteResult, status_code=status.HTTP_201_CREATED)
async def create_user_workspace(
    data: WorkspaceCreateRequest, user: ApiUser, db: Database
) -> WriteResult:
    workspace = await create_workspace(db, user, data.name, owner_username=data.owner_username)
    return WriteResult(id=workspace.id)


@workspace_root_router.patch("/workspaces/{workspace_id}", response_model=WriteResult)
async def update_user_workspace(
    workspace_id: UUID, data: WorkspaceUpdateRequest, user: ApiUser, db: Database
) -> WriteResult:
    workspace = await update_workspace(db, user, workspace_id, data.name)
    return WriteResult(id=workspace.id)


@workspace_router.get("/members", response_model=list[WorkspaceMemberDirectoryView])
async def get_workspace_members(
    workspace_id: UUID, context: WorkspaceAccess, db: Database
) -> list[WorkspaceMemberDirectoryView]:
    members = await list_workspace_members(db, context)
    usernames = await _usernames(db, {member.user_id for member in members})
    return [
        WorkspaceMemberDirectoryView(
            user_id=member.user_id,
            username=usernames[member.user_id],
            role=member.role,
        )
        for member in members
    ]


@workspace_router.get("/governance/members", response_model=list[WorkspaceGovernanceMemberView])
async def get_workspace_governance_members(
    workspace_id: UUID, context: WorkspaceAccess, db: Database
) -> list[WorkspaceGovernanceMemberView]:
    members = await list_workspace_governance_members(db, context)
    usernames = await _usernames(db, {member.user_id for member in members})
    return [
        WorkspaceGovernanceMemberView(
            membership_id=member.id,
            user_id=member.user_id,
            username=usernames[member.user_id],
            role=member.role,
            state=member.state,
            joined_at=member.created_at,
            allowed_roles=list(workspace_member_roles(context, member)),
            authorization=authorization_view(workspace_member_decisions(context, member)),
        )
        for member in members
    ]


@workspace_router.post(
    "/invitations",
    response_model=WorkspaceInvitationCreatedView,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_invitation(
    workspace_id: UUID,
    data: WorkspaceInvitationRequest,
    user: ApiUser,
    db: Database,
) -> WorkspaceInvitationCreatedView:
    invitation, raw = await invite_workspace_member(
        db,
        user,
        workspace_id,
        data.username,
        data.role,
        expires_at=data.expires_at,
    )
    return WorkspaceInvitationCreatedView(
        id=invitation.id,
        user_id=invitation.user_id,
        username=data.username.strip(),
        role=invitation.role,
        expires_at=invitation.expires_at,
        token=raw,
    )


@workspace_router.get(
    "/invitations",
    response_model=list[WorkspaceInvitationView],
)
async def get_workspace_invitations(
    workspace_id: UUID, context: WorkspaceAccess, db: Database
) -> list[WorkspaceInvitationView]:
    invitations = await list_workspace_invitations(db, context)
    usernames = await _usernames(db, {invitation.user_id for invitation in invitations})
    return [
        WorkspaceInvitationView(
            id=invitation.id,
            user_id=invitation.user_id,
            username=usernames[invitation.user_id],
            role=invitation.role,
            invited_by=invitation.invited_by,
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
        )
        for invitation in invitations
    ]


@workspace_router.delete(
    "/invitations/{invitation_id}",
    response_model=OkView,
)
async def revoke_workspace_invitation_api(
    workspace_id: UUID, invitation_id: UUID, user: ApiUser, db: Database
) -> OkView:
    await revoke_workspace_invitation(db, user, workspace_id, invitation_id)
    return OkView()


@router.post(
    "/workspace-invitations/{token}/accept",
    response_model=WorkspaceInvitationAcceptanceView,
)
async def accept_workspace_invitation_api(
    token: str, user: ApiUser, db: Database
) -> WorkspaceInvitationAcceptanceView:
    member = await accept_workspace_invitation_by_token(db, user, token)
    return WorkspaceInvitationAcceptanceView(workspace_id=member.workspace_id)


@workspace_router.put("/members/{membership_id}/role", response_model=OkView)
async def change_workspace_member_role(
    workspace_id: UUID,
    membership_id: UUID,
    data: WorkspaceRoleRequest,
    user: ApiUser,
    db: Database,
) -> OkView:
    await set_workspace_member_role(db, user, workspace_id, membership_id, data.role)
    return OkView()


@workspace_router.post("/members/{membership_id}/suspend", response_model=OkView)
async def suspend_member(
    workspace_id: UUID, membership_id: UUID, user: ApiUser, db: Database
) -> OkView:
    await suspend_workspace_member(db, user, workspace_id, membership_id)
    return OkView()


@workspace_router.post("/members/{membership_id}/reactivate", response_model=OkView)
async def reactivate_member(
    workspace_id: UUID, membership_id: UUID, user: ApiUser, db: Database
) -> OkView:
    await reactivate_workspace_member(db, user, workspace_id, membership_id)
    return OkView()


@workspace_router.delete("/members/{membership_id}", response_model=OkView)
async def terminate_member(
    workspace_id: UUID, membership_id: UUID, user: ApiUser, db: Database
) -> OkView:
    await terminate_workspace_member(db, user, workspace_id, membership_id)
    return OkView()


@workspace_router.post("/ownership/{membership_id}", response_model=OkView)
async def transfer_ownership(
    workspace_id: UUID, membership_id: UUID, user: ApiUser, db: Database
) -> OkView:
    await transfer_workspace_ownership(db, user, workspace_id, membership_id)
    return OkView()


@workspace_router.post("/archive", response_model=OkView)
async def archive_user_workspace(workspace_id: UUID, user: ApiUser, db: Database) -> OkView:
    await archive_workspace(db, user, workspace_id)
    return OkView()


@workspace_router.post("/restore", response_model=OkView)
async def restore_user_workspace(workspace_id: UUID, user: ApiUser, db: Database) -> OkView:
    await restore_workspace(db, user, workspace_id)
    return OkView()


@workspace_root_router.delete("/workspaces/{workspace_id}", response_model=OkView)
async def delete_user_workspace(workspace_id: UUID, user: ApiUser, db: Database) -> OkView:
    await permanently_delete_workspace(db, user, workspace_id)
    return OkView()


@workspace_router.post("/maintenance/reindex", response_model=WriteResult)
async def reindex_workspace(workspace_id: UUID, user: ApiUser, db: Database) -> WriteResult:
    return WriteResult(id=await dispatch_workspace_reindex(db, user, workspace_id))
