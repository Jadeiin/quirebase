from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import update

from quirebase.core.errors import ResourceUnavailable
from quirebase.models import Project, ProjectState, ProjectVisibility

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def require_project_write_gate(
    db: AsyncSession,
    project_id: str,
    *,
    state: ProjectState | None = None,
    visibility: ProjectVisibility | None = None,
    message: str = "project not found",
) -> Project:
    """Serialize a Project mutation and refresh any cached Project state."""
    predicates = [Project.id == project_id]
    if state is not None:
        predicates.append(Project.state == state)
    if visibility is not None:
        predicates.append(Project.visibility == visibility)
    gated_id = await db.scalar(
        update(Project)
        .where(*predicates)
        .values(updated_at=Project.updated_at)
        .returning(Project.id)
        .execution_options(synchronize_session=False)
    )
    if gated_id is None:
        raise ResourceUnavailable(message)
    project = await db.get(Project, gated_id, populate_existing=True)
    if project is None:
        raise ResourceUnavailable(message)
    return project
