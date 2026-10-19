from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from quirebase.models import (
    ProjectParticipation,
    WorkspaceInvitationRole,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.web.api.common import WorkspaceAuthorizationView


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    owner_username: str | None = Field(default=None, min_length=1, max_length=120)


class WorkspaceCreationAvailabilityView(BaseModel):
    allowed: bool
    owner_username_required: bool


class WorkspaceUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)


class WorkspaceView(BaseModel):
    id: UUID
    name: str
    owner_id: UUID
    state: WorkspaceState
    current_role: WorkspaceRole
    current_membership_id: UUID
    governance_frozen: bool
    allowed_project_participations: list[ProjectParticipation]
    allowed_invitation_roles: list[WorkspaceInvitationRole] = Field(default_factory=list)
    authorization: WorkspaceAuthorizationView


class WorkspaceLeaveRequest(BaseModel):
    membership_id: UUID


class WorkspaceMemberDirectoryView(BaseModel):
    user_id: UUID
    username: str
    role: WorkspaceRole


class WorkspaceGovernanceMemberView(BaseModel):
    membership_id: UUID
    user_id: UUID
    username: str
    role: WorkspaceRole
    state: WorkspaceMemberState
    joined_at: datetime
    allowed_roles: list[WorkspaceInvitationRole]
    authorization: WorkspaceAuthorizationView


class WorkspaceRoleRequest(BaseModel):
    role: Literal["admin", "editor", "reviewer", "viewer"]


class WorkspaceInvitationRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    role: WorkspaceInvitationRole = WorkspaceInvitationRole.viewer
    expires_at: datetime | None = None


class WorkspaceInvitationCreatedView(BaseModel):
    id: UUID
    user_id: UUID
    username: str
    role: WorkspaceInvitationRole
    expires_at: datetime
    token: str


class WorkspaceInvitationView(BaseModel):
    id: UUID
    user_id: UUID
    username: str
    role: WorkspaceInvitationRole
    invited_by: UUID
    expires_at: datetime
    created_at: datetime


class WorkspaceInvitationAcceptanceView(BaseModel):
    workspace_id: UUID


class ReceivedWorkspaceInvitationView(BaseModel):
    id: UUID
    workspace_id: UUID
    workspace_name: str
    inviter_username: str
    role: WorkspaceInvitationRole
    created_at: datetime
    expires_at: datetime
    state: Literal["pending", "accepted", "revoked", "expired"]
    can_accept: bool
    can_open: bool
    unavailable_reason: Literal["workspace_read_only", "current_member"] | None
