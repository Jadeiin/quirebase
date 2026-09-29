from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import] - Pydantic resolves it
from typing import Literal

from pydantic import BaseModel, Field

from quirebase.web.api.common import AuthorizationView


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1)


class LoginSessionView(BaseModel):
    id: str
    current: bool = False
    expires_at: datetime
    created_at: datetime


class SessionUserView(BaseModel):
    id: str
    username: str
    role: Literal["administrator", "member"]
    authorization: AuthorizationView


class SessionView(BaseModel):
    authenticated: bool
    user: SessionUserView | None = None
