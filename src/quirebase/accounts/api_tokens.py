from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from quirebase.access import require_system_resource_action
from quirebase.audit import record_event
from quirebase.core.crypto import generate_token, token_hash
from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.models import ApiToken, User

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

API_TOKEN_PREFIX = "qb_api_"
MAX_API_TOKEN_DAYS = 365


@dataclass(frozen=True)
class ApiTokenGrant:
    token_id: UUID
    raw_token: str
    expires_at: datetime


@dataclass(frozen=True)
class ApiTokenSummary:
    token_id: UUID
    name: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime

    @property
    def status(self) -> Literal["active", "expired", "revoked"]:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at <= datetime.now(UTC):
            return "expired"
        return "active"


@dataclass(frozen=True)
class VerifiedApiToken:
    token_id: UUID
    user_id: UUID
    expires_at: datetime


async def create_api_token(
    db: AsyncSession,
    user: User,
    name: str,
    *,
    expires_in_days: int,
) -> ApiTokenGrant:
    user = await require_system_resource_action(
        db, user, "api_token", "create", relation="own", lock="shared"
    )
    normalized_name = name.strip()
    if not normalized_name:
        raise ValidationFailure("API Token name is required")
    if len(normalized_name) > 120:
        raise ValidationFailure("API Token name must contain at most 120 characters")
    if not 1 <= expires_in_days <= MAX_API_TOKEN_DAYS:
        raise ValidationFailure(f"API Token lifetime must be 1-{MAX_API_TOKEN_DAYS} days")
    raw_token = f"{API_TOKEN_PREFIX}{generate_token(32)}"
    expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)
    token = ApiToken(
        name=normalized_name,
        token_hash=token_hash(raw_token),
        user_id=user.id,
        expires_at=expires_at,
    )
    db.add(token)
    await db.flush()
    record_event(db, user.id, "auth.api_token.create", "api_token", token.id)
    await db.commit()
    return ApiTokenGrant(token_id=token.id, raw_token=raw_token, expires_at=expires_at)


async def verify_api_token(db: AsyncSession, raw_token: str) -> VerifiedApiToken | None:
    if not raw_token.startswith(API_TOKEN_PREFIX):
        return None
    token = await db.scalar(
        select(ApiToken)
        .options(selectinload(ApiToken.user))
        .where(ApiToken.token_hash == token_hash(raw_token))
    )
    if (
        token is None
        or token.revoked_at is not None
        or token.expires_at <= datetime.now(UTC)
        or not token.user.active
    ):
        return None
    return VerifiedApiToken(
        token_id=token.id,
        user_id=token.user_id,
        expires_at=token.expires_at.astimezone(UTC),
    )


async def list_api_tokens(db: AsyncSession, user: User) -> tuple[ApiTokenSummary, ...]:
    user = await require_system_resource_action(db, user, "api_token", "read", relation="own")
    records = (
        await db.scalars(
            select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())
        )
    ).all()
    return tuple(
        ApiTokenSummary(
            token_id=record.id,
            name=record.name,
            expires_at=record.expires_at,
            revoked_at=record.revoked_at,
            created_at=record.created_at,
        )
        for record in records
    )


async def revoke_api_token(db: AsyncSession, user: User, token_id: UUID) -> None:
    token = await db.get(ApiToken, token_id)
    relation = "own" if token is not None and token.user_id == user.id else "other"
    user = await require_system_resource_action(
        db,
        user,
        "api_token",
        "revoke",
        relation=relation,
        lock="shared",
        message="API Token not found",
    )
    if token is None:
        raise ResourceNotFound("API Token not found")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        record_event(db, user.id, "auth.api_token.revoke", "api_token", token.id)
        await db.commit()
