from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import case, delete, select

from quirebase.core.errors import DomainError
from quirebase.core.persistence import conflict_insert
from quirebase.models import LoginThrottle

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

THROTTLE_WINDOW = timedelta(minutes=15)
THROTTLE_LIMIT = 5


class LoginThrottled(DomainError):
    status_code: int = 429

    def __init__(self, message: str = "too many login attempts; try again later"):
        super().__init__(message)
        self.detail = message


async def check_login_throttle(db: AsyncSession, identity: str) -> None:
    row = await db.scalar(
        select(LoginThrottle)
        .where(LoginThrottle.identity_hash == identity)
        .execution_options(populate_existing=True)
    )
    if row is None:
        return
    cutoff = datetime.now(UTC) - THROTTLE_WINDOW
    if row.window_started_at <= cutoff:
        await db.execute(
            delete(LoginThrottle).where(
                LoginThrottle.identity_hash == identity, LoginThrottle.window_started_at <= cutoff
            )
        )
        await db.commit()
    elif row.failures >= THROTTLE_LIMIT:
        raise LoginThrottled("too many login attempts; try again later")


async def record_login_failure(db: AsyncSession, identity: str) -> None:
    now = datetime.now(UTC)
    cutoff = now - THROTTLE_WINDOW
    expired = LoginThrottle.window_started_at <= cutoff
    statement = conflict_insert(db, LoginThrottle).values(
        identity_hash=identity, failures=1, window_started_at=now
    )
    await db.scalar(
        statement
        .on_conflict_do_update(
            index_elements=[LoginThrottle.identity_hash],
            set_={
                "failures": case((expired, 1), else_=LoginThrottle.failures + 1),
                "window_started_at": case((expired, now), else_=LoginThrottle.window_started_at),
            },
        )
        .returning(LoginThrottle)
        .execution_options(populate_existing=True)
    )
    await db.commit()


async def clear_login_failures(db: AsyncSession, identity: str) -> None:
    cleared = await db.scalar(
        delete(LoginThrottle)
        .where(LoginThrottle.identity_hash == identity)
        .returning(LoginThrottle.identity_hash)
    )
    if cleared is not None:
        await db.commit()
