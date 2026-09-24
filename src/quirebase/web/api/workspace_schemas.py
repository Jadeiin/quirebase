from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import] - Pydantic resolves it
from typing import Literal

from pydantic import BaseModel, Field


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
    state: str
    current_role: str
    governance_suspended: bool
    effective_capabilities: list[str]


class WorkspaceMemberDirectoryView(BaseModel):
    user_id: str
    username: str
    role: str


class WorkspaceGovernanceMemberView(BaseModel):
    membership_id: str
    user_id: str
    username: str
    role: str
    state: str
    joined_at: datetime


class WorkspaceRoleRequest(BaseModel):
    role: Literal["admin", "editor", "reviewer", "viewer"]


class WorkspaceInvitationRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    role: Literal["editor", "reviewer", "viewer"] = "viewer"
    expires_at: datetime


class WorkspaceInvitationCreatedView(BaseModel):
    id: str
    user_id: str
    username: str
    role: str
    expires_at: datetime
    token: str


class WorkspaceInvitationView(BaseModel):
    id: str
    user_id: str
    username: str
    role: str
    invited_by: str
    expires_at: datetime
    created_at: datetime


class WorkspaceInvitationDetailsView(BaseModel):
    username: str
    role: str
    workspace_name: str
    expires_at: datetime


class WorkspaceInvitationAcceptanceView(BaseModel):
    workspace_id: str
