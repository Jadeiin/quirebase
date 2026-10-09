from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from quirebase.web.api.common import SystemAuthorizationView


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1)


class LoginSessionView(BaseModel):
    id: UUID
    current: bool = False
    expires_at: datetime
    created_at: datetime


class SessionUserView(BaseModel):
    id: UUID
    username: str
    role: Literal["administrator", "member"]
    authorization: SystemAuthorizationView


class SessionView(BaseModel):
    authenticated: bool
    user: SessionUserView | None = None
