from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import] - Pydantic resolves it
from typing import Literal

from pydantic import BaseModel, Field

from quirebase.web.api.session_schemas import LoginSessionView, SessionUserView


class InvitationAcceptRequest(BaseModel):
    password: str = Field(min_length=1)


class ApiTokenCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    days: int = Field(default=30, ge=1, le=365)


class ApiTokenView(BaseModel):
    id: str
    name: str
    status: Literal["active", "expired", "revoked"]
    expires_at: datetime
    created_at: datetime


class ApiTokenGrantView(BaseModel):
    id: str
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
    username: str
    role: str
    expires_at: datetime
