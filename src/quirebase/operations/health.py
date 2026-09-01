from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from quirebase.core.errors import ResourceUnavailable
from quirebase.models import FileRevision, Item, Job, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def check_health() -> dict[str, str]:
    return {"status": "ok"}


async def get_system_metrics(db: AsyncSession, user: User) -> str:
    if user.role != "administrator":
        raise ResourceUnavailable("administrator role required")
    lines = [
        f'quirebase_jobs{{state="{state}"}} {count}'
        for state, count in (
            await db.execute(
                select(Job.state, func.count()).group_by(Job.state).order_by(Job.state)
            )
        )
    ]
    lines.extend([
        f"quirebase_items {await db.scalar(select(func.count()).select_from(Item)) or 0}",
        f"quirebase_file_revisions {await db.scalar(select(func.count()).select_from(FileRevision)) or 0}",
    ])
    return "\n".join(lines) + "\n"
