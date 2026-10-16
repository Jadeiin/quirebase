from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from quirebase.access import SystemAction, require_system_action
from quirebase.core.workflows import durable_operations
from quirebase.models import FileRevision, Item, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def check_health() -> dict[str, str]:
    return {"status": "ok"}


async def get_system_metrics(db: AsyncSession, user: User) -> str:
    await require_system_action(
        db, user, SystemAction.system_metrics_read, message="administrator role required"
    )
    workflow_counts = await durable_operations().state_counts()
    lines = [
        f'quirebase_workflows{{state="{state}"}} {count}'
        for state, count in sorted(workflow_counts.items())
    ]
    lines.extend([
        f"quirebase_items {await db.scalar(select(func.count()).select_from(Item)) or 0}",
        f"quirebase_file_revisions {await db.scalar(select(func.count()).select_from(FileRevision)) or 0}",
    ])
    return "\n".join(lines) + "\n"
