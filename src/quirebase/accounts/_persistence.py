"""Account persistence on the existing account transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import case, delete, select, update
from sqlalchemy.exc import IntegrityError

from quirebase.core.persistence import Repository, Service
from quirebase.models import Invitation, LoginThrottle, User

if TYPE_CHECKING:
    from datetime import datetime


class UserRepository(Repository[User]):
    model_type = User


class UserService(Service[User]):
    repository_type = UserRepository


class InvitationRepository(Repository[Invitation]):
    model_type = Invitation


class LoginThrottleRepository(Repository[LoginThrottle]):
    model_type = LoginThrottle
    id_attribute = "identity_hash"

    async def current(self, identity: str) -> LoginThrottle | None:
        return await self.session.scalar(
            select(LoginThrottle)
            .where(LoginThrottle.identity_hash == identity)
            .execution_options(populate_existing=True)
        )

    async def record_failure(self, identity: str, now: datetime, cutoff: datetime) -> None:
        expired = LoginThrottle.window_started_at <= cutoff
        statement = (
            update(LoginThrottle)
            .where(LoginThrottle.identity_hash == identity)
            .values(
                failures=case((expired, 1), else_=LoginThrottle.failures + 1),
                window_started_at=case((expired, now), else_=LoginThrottle.window_started_at),
            )
            .returning(LoginThrottle)
            .execution_options(populate_existing=True)
        )
        if await self.session.scalar(statement) is not None:
            return
        try:
            async with self.session.begin_nested():
                await self.add(
                    LoginThrottle(identity_hash=identity, failures=1, window_started_at=now)
                )
        except IntegrityError:
            # Recover a competing first insert once. If a successful login
            # already cleared it, let the command report the conflict.
            if await self.session.scalar(statement) is None:
                raise

    async def delete_expired(self, identity: str, cutoff: datetime) -> bool:
        return (
            await self.session.scalar(
                delete(LoginThrottle)
                .where(
                    LoginThrottle.identity_hash == identity,
                    LoginThrottle.window_started_at <= cutoff,
                )
                .returning(LoginThrottle.identity_hash)
            )
            is not None
        )

    async def clear(self, identity: str) -> bool:
        return (
            await self.session.scalar(
                delete(LoginThrottle)
                .where(LoginThrottle.identity_hash == identity)
                .returning(LoginThrottle.identity_hash)
            )
            is not None
        )
