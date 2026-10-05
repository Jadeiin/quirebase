from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import] - Pydantic resolves it
from typing import Literal

from pydantic import BaseModel, Field

from quirebase.models import (
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
    id: str
    name: str
    owner_id: str
    state: WorkspaceState
    current_role: WorkspaceRole
    governance_suspended: bool
    allowed_invitation_roles: list[WorkspaceInvitationRole] = Field(default_factory=list)
    authorization: WorkspaceAuthorizationView


class WorkspaceMemberDirectoryView(BaseModel):
    user_id: str
    username: str
    role: WorkspaceRole


class WorkspaceGovernanceMemberView(BaseModel):
    membership_id: str
    user_id: str
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
    id: str
    user_id: str
    username: str
    role: WorkspaceInvitationRole
    expires_at: datetime
    token: str


class WorkspaceInvitationView(BaseModel):
    id: str
    user_id: str
    username: str
    role: WorkspaceInvitationRole
    invited_by: str
    expires_at: datetime
    created_at: datetime


class WorkspaceInvitationAcceptanceView(BaseModel):
    workspace_id: str
