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
    if await _check_login_throttle(db, identity):
        await db.commit()


async def _check_login_throttle(db: AsyncSession, identity: str) -> bool:
    """Check the limit and retire an expired window in the caller's transaction."""
    row = await db.scalar(
        select(LoginThrottle)
        .where(LoginThrottle.identity_hash == identity)
        .execution_options(populate_existing=True)
    )
    if row is None:
        return False
    cutoff = datetime.now(UTC) - THROTTLE_WINDOW
    if row.window_started_at <= cutoff:
        await db.execute(
            delete(LoginThrottle).where(
                LoginThrottle.identity_hash == identity, LoginThrottle.window_started_at <= cutoff
            )
        )
        return True
    if row.failures >= THROTTLE_LIMIT:
        raise LoginThrottled("too many login attempts; try again later")
    return False


async def record_login_failure(db: AsyncSession, identity: str) -> None:
    await _record_login_failure(db, identity)
    await db.commit()


async def _record_login_failure(db: AsyncSession, identity: str) -> None:
    """Update the failure counter without completing the caller's transaction."""
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


async def clear_login_failures(db: AsyncSession, identity: str) -> None:
    if await _clear_login_failures(db, identity):
        await db.commit()


async def _clear_login_failures(db: AsyncSession, identity: str) -> bool:
    cleared = await db.scalar(
        delete(LoginThrottle)
        .where(LoginThrottle.identity_hash == identity)
        .returning(LoginThrottle.identity_hash)
    )
    return cleared is not None
