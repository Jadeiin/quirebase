"""Account persistence on the existing account transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import case, delete, select

from quirebase.core.persistence import Repository, Service, conflict_insert
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
        statement = conflict_insert(self.session, LoginThrottle).values(
            identity_hash=identity, failures=1, window_started_at=now
        )
        await self.session.scalar(
            statement
            .on_conflict_do_update(
                index_elements=[LoginThrottle.identity_hash],
                set_={
                    "failures": case((expired, 1), else_=LoginThrottle.failures + 1),
                    "window_started_at": case(
                        (expired, now), else_=LoginThrottle.window_started_at
                    ),
                },
            )
            .returning(LoginThrottle)
            .execution_options(populate_existing=True)
        )

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
