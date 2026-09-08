from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from quirebase.core.errors import DomainError
from quirebase.core.timezones import as_utc
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
    row = await db.get(LoginThrottle, identity)
    if row is None:
        return
    started = as_utc(row.window_started_at)
    if started + THROTTLE_WINDOW <= datetime.now(UTC):
        await db.delete(row)
        await db.commit()
    elif row.failures >= THROTTLE_LIMIT:
        raise LoginThrottled("too many login attempts; try again later")


async def record_login_failure(db: AsyncSession, identity: str) -> None:
    current = datetime.now(UTC)
    statement = (
        pg_insert(LoginThrottle)
        if db.get_bind().dialect.name == "postgresql"
        else sqlite_insert(LoginThrottle)
    )
    statement = statement.values(identity_hash=identity, failures=1, window_started_at=current)
    statement = statement.on_conflict_do_update(
        index_elements=[LoginThrottle.identity_hash],
        set_={
            "failures": case(
                (LoginThrottle.window_started_at <= current - THROTTLE_WINDOW, 1),
                else_=LoginThrottle.failures + 1,
            ),
            "window_started_at": case(
                (LoginThrottle.window_started_at <= current - THROTTLE_WINDOW, current),
                else_=LoginThrottle.window_started_at,
            ),
        },
    )
    await db.execute(statement)
    await db.commit()


async def clear_login_failures(db: AsyncSession, identity: str) -> None:
    row = await db.get(LoginThrottle, identity)
    if row:
        await db.delete(row)
        await db.commit()
