from __future__ import annotations

from fastapi import APIRouter, status

from quirebase.access import ROLE_CAPABILITIES
from quirebase.operations import dispatch_workspace_reindex
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.workspace_schemas import (
    InitialWorkspaceRepairRequest,
    WorkspaceCreateRequest,
    WorkspaceInvitationCreatedView,
    WorkspaceInvitationRequest,
    WorkspaceInvitationView,
    WorkspaceMemberView,
    WorkspaceRoleRequest,
    WorkspaceUpdateRequest,
    WorkspaceView,
)
from quirebase.workspaces import (
    accept_workspace_invitation,
    archive_workspace,
    create_workspace,
    get_workspace,
    invite_workspace_member,
    list_workspace_invitations,
    list_workspace_members,
    list_workspaces,
    permanently_delete_workspace,
    reactivate_workspace_member,
    repair_initial_workspace,
    restore_workspace,
    revoke_workspace_invitation,
    set_workspace_member_role,
    suspend_workspace_member,
    terminate_workspace_member,
    transfer_workspace_ownership,
    update_workspace,
)

router = APIRouter(tags=["Workspaces"])


def _workspace_view(workspace, member) -> WorkspaceView:
    return WorkspaceView(
        id=workspace.id,
        name=workspace.name,
        owner_id=workspace.owner_id,
        state=workspace.state.value,
        role=member.role.value,
        permissions=sorted(capability.value for capability in ROLE_CAPABILITIES[member.role]),
    )


@router.get("/workspaces", response_model=list[WorkspaceView])
async def get_workspaces(user: ApiUser, db: Database) -> list[WorkspaceView]:
    return [
        _workspace_view(workspace, member) for workspace, member in await list_workspaces(db, user)
    ]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceView)
async def get_user_workspace(workspace_id: str, user: ApiUser, db: Database) -> WorkspaceView:
    workspace, member = await get_workspace(db, user, workspace_id)
    return _workspace_view(workspace, member)


@router.post("/workspaces", response_model=WriteResult, status_code=status.HTTP_201_CREATED)
async def create_user_workspace(
    data: WorkspaceCreateRequest, user: ApiUser, db: Database
) -> WriteResult:
    workspace = await create_workspace(db, user, data.name, owner_id=data.owner_id)
    return WriteResult(id=workspace.id)


@router.patch("/workspaces/{workspace_id}", response_model=WriteResult)
async def update_user_workspace(
    workspace_id: str, data: WorkspaceUpdateRequest, user: ApiUser, db: Database
) -> WriteResult:
    workspace = await update_workspace(db, user, workspace_id, data.name)
    return WriteResult(id=workspace.id)


@router.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberView])
async def get_workspace_members(
    workspace_id: str, user: ApiUser, db: Database
) -> list[WorkspaceMemberView]:
    return [
        WorkspaceMemberView(
            id=member.id,
            user_id=member.user_id,
            role=member.role.value,
            state=member.state.value,
            created_at=member.created_at,
        )
        for member in await list_workspace_members(db, user, workspace_id)
    ]


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=WorkspaceInvitationCreatedView,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_invitation(
    workspace_id: str,
    data: WorkspaceInvitationRequest,
    user: ApiUser,
    db: Database,
) -> WorkspaceInvitationCreatedView:
    invitation, raw = await invite_workspace_member(db, user, workspace_id, data.user_id, data.role)
    return WorkspaceInvitationCreatedView(
        id=invitation.id,
        user_id=invitation.user_id,
        role=invitation.role.value,
        expires_at=invitation.expires_at,
        token=raw,
    )


@router.get(
    "/workspaces/{workspace_id}/invitations",
    response_model=list[WorkspaceInvitationView],
)
async def get_workspace_invitations(
    workspace_id: str, user: ApiUser, db: Database
) -> list[WorkspaceInvitationView]:
    return [
        WorkspaceInvitationView(
            id=invitation.id,
            user_id=invitation.user_id,
            role=invitation.role.value,
            invited_by=invitation.invited_by,
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
        )
        for invitation in await list_workspace_invitations(db, user, workspace_id)
    ]


@router.delete(
    "/workspaces/{workspace_id}/invitations/{invitation_id}",
    response_model=OkView,
)
async def revoke_workspace_invitation_api(
    workspace_id: str, invitation_id: str, user: ApiUser, db: Database
) -> OkView:
    await revoke_workspace_invitation(db, user, workspace_id, invitation_id)
    return OkView()


@router.post(
    "/workspaces/{workspace_id}/invitations/{token}/accept",
    response_model=WriteResult,
)
async def accept_workspace_invitation_api(
    workspace_id: str, token: str, user: ApiUser, db: Database
) -> WriteResult:
    member = await accept_workspace_invitation(db, user, workspace_id, token)
    return WriteResult(id=member.id)


@router.put("/workspaces/{workspace_id}/members/{membership_id}/role", response_model=OkView)
async def change_workspace_member_role(
    workspace_id: str,
    membership_id: str,
    data: WorkspaceRoleRequest,
    user: ApiUser,
    db: Database,
) -> OkView:
    await set_workspace_member_role(db, user, workspace_id, membership_id, data.role)
    return OkView()


@router.post("/workspaces/{workspace_id}/members/{membership_id}/suspend", response_model=OkView)
async def suspend_member(
    workspace_id: str, membership_id: str, user: ApiUser, db: Database
) -> OkView:
    await suspend_workspace_member(db, user, workspace_id, membership_id)
    return OkView()


@router.post("/workspaces/{workspace_id}/members/{membership_id}/reactivate", response_model=OkView)
async def reactivate_member(
    workspace_id: str, membership_id: str, user: ApiUser, db: Database
) -> OkView:
    await reactivate_workspace_member(db, user, workspace_id, membership_id)
    return OkView()


@router.delete("/workspaces/{workspace_id}/members/{membership_id}", response_model=OkView)
async def terminate_member(
    workspace_id: str, membership_id: str, user: ApiUser, db: Database
) -> OkView:
    await terminate_workspace_member(db, user, workspace_id, membership_id)
    return OkView()


@router.post("/workspaces/{workspace_id}/ownership/{membership_id}", response_model=OkView)
async def transfer_ownership(
    workspace_id: str, membership_id: str, user: ApiUser, db: Database
) -> OkView:
    await transfer_workspace_ownership(db, user, workspace_id, membership_id)
    return OkView()


@router.post("/workspaces/{workspace_id}/archive", response_model=OkView)
async def archive_user_workspace(workspace_id: str, user: ApiUser, db: Database) -> OkView:
    await archive_workspace(db, user, workspace_id)
    return OkView()


@router.post("/workspaces/{workspace_id}/restore", response_model=OkView)
async def restore_user_workspace(workspace_id: str, user: ApiUser, db: Database) -> OkView:
    await restore_workspace(db, user, workspace_id)
    return OkView()


@router.delete("/workspaces/{workspace_id}", response_model=OkView)
async def delete_user_workspace(workspace_id: str, user: ApiUser, db: Database) -> OkView:
    await permanently_delete_workspace(db, user, workspace_id)
    return OkView()


@router.post("/workspaces/{workspace_id}/maintenance/reindex", response_model=WriteResult)
async def reindex_workspace(workspace_id: str, user: ApiUser, db: Database) -> WriteResult:
    return WriteResult(id=await dispatch_workspace_reindex(db, user, workspace_id))


@router.post("/account/initial-workspace/repair", response_model=WriteResult)
async def repair_user_initial_workspace(
    data: InitialWorkspaceRepairRequest, user: ApiUser, db: Database
) -> WriteResult:
    workspace = await repair_initial_workspace(db, user, data.user_id)
    return WriteResult(id=workspace.id)
