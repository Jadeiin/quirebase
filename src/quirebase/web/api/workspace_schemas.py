from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import] - Pydantic resolves it
from typing import Literal

from pydantic import BaseModel, Field


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    owner_id: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=240)


class WorkspaceView(BaseModel):
    id: str
    name: str
    owner_id: str
    state: str
    role: str
    permissions: list[str]


class WorkspaceMemberView(BaseModel):
    id: str
    user_id: str
    role: str
    state: str
    created_at: datetime


class WorkspaceRoleRequest(BaseModel):
    role: Literal["admin", "editor", "reviewer", "viewer"]


class WorkspaceInvitationRequest(BaseModel):
    user_id: str
    role: Literal["editor", "reviewer", "viewer"] = "viewer"


class WorkspaceInvitationCreatedView(BaseModel):
    id: str
    user_id: str
    role: str
    expires_at: datetime
    token: str


class WorkspaceInvitationView(BaseModel):
    id: str
    user_id: str
    role: str
    invited_by: str
    expires_at: datetime
    created_at: datetime


class InitialWorkspaceRepairRequest(BaseModel):
    user_id: str | None = None
