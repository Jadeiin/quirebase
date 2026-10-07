from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from quirebase.models import SystemRole, WorkspaceInvitationRole
from quirebase.web.api.session_schemas import LoginSessionView, SessionUserView


class InvitationAcceptRequest(BaseModel):
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1)


class ApiTokenCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    days: int = Field(default=30, ge=1, le=365)


class ApiTokenView(BaseModel):
    id: UUID = Field(validation_alias="token_id")
    name: str
    status: Literal["active", "expired", "revoked"]
    expires_at: datetime
    created_at: datetime


class ApiTokenGrantView(BaseModel):
    id: UUID
    token: str
    expires_at: datetime


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class AccountSummaryView(BaseModel):
    user: SessionUserView
    sessions: list[LoginSessionView]
    api_tokens: list[ApiTokenView]


class InvitationDetailsView(BaseModel):
    kind: Literal["account"] = "account"
    username: str
    role: SystemRole
    expires_at: datetime


class WorkspaceInvitationDetailsView(BaseModel):
    kind: Literal["workspace"] = "workspace"
    username: str
    role: WorkspaceInvitationRole
    workspace_name: str
    expires_at: datetime


PublicInvitationDetailsView = Annotated[
    InvitationDetailsView | WorkspaceInvitationDetailsView, Field(discriminator="kind")
]
