from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from quirebase.core.errors import DomainError

from ._persistence import LoginThrottleRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

THROTTLE_WINDOW = timedelta(minutes=15)
THROTTLE_LIMIT = 5


class LoginThrottled(DomainError):
    status_code: int = 429

    def __init__(self, message: str = "too many login attempts; try again later"):
        super().__init__(message)
        self.detail = message


class LoginThrottleConflict(DomainError):
    status_code: int = 409


async def check_login_throttle(db: AsyncSession, identity: str) -> None:
    repository = LoginThrottleRepository(session=db)
    row = await repository.current(identity)
    if row is None:
        return
    cutoff = datetime.now(UTC) - THROTTLE_WINDOW
    if row.window_started_at <= cutoff:
        await repository.delete_expired(identity, cutoff)
        await db.commit()
    elif row.failures >= THROTTLE_LIMIT:
        raise LoginThrottled("too many login attempts; try again later")


async def record_login_failure(db: AsyncSession, identity: str) -> None:
    now = datetime.now(UTC)
    try:
        await LoginThrottleRepository(session=db).record_failure(
            identity, now, now - THROTTLE_WINDOW
        )
    except IntegrityError as error:
        raise LoginThrottleConflict(
            "login failure counter changed concurrently; try again"
        ) from error
    await db.commit()


async def clear_login_failures(db: AsyncSession, identity: str) -> None:
    if await LoginThrottleRepository(session=db).clear(identity):
        await db.commit()
