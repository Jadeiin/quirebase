from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from quirebase.core.errors import ResourceUnavailable
from quirebase.models import FileRevision, Item, Job, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def check_health() -> dict[str, str]:
    return {"status": "ok"}


def get_system_metrics(db: Session, user: User) -> str:
    if user.role != "administrator":
        raise ResourceUnavailable("administrator role required")
    lines = []
    for state, count in db.execute(
        select(Job.state, func.count()).group_by(Job.state).order_by(Job.state)
    ):
        lines.append(f'quirebase_jobs{{state="{state}"}} {count}')
    lines.append(f"quirebase_items {db.scalar(select(func.count()).select_from(Item)) or 0}")
    lines.append(
        f"quirebase_file_revisions {db.scalar(select(func.count()).select_from(FileRevision)) or 0}"
    )
    return "\n".join(lines) + "\n"
