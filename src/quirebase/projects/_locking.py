from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sqlalchemy import select

from quirebase.access.project_scope import project_visibility_predicate, require_project_visibility
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import Project, ProjectParticipation, ProjectState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.access.context import WorkspaceContext


async def lock_project_root(
    db: AsyncSession,
    context: WorkspaceContext,
    project_id: str,
    *,
    lock: Literal["shared", "update"] = "update",
    state: ProjectState | None = None,
    participation: ProjectParticipation | None = None,
    message: str = "Project not found",
) -> Project:
    """Lock a visible Project, then recheck discovery after any lock wait.

    Project aggregate changes use an exclusive lock; association commands use
    a shared guard. The Workspace root must already be held by the command.
    """
    predicates = [Project.id == project_id, project_visibility_predicate(context)]
    if state is not None:
        predicates.append(Project.state == state)
    if participation is not None:
        predicates.append(Project.participation == participation)
    project = await db.scalar(
        select(Project)
        .where(*predicates)
        .execution_options(populate_existing=True)
        .with_for_update(read=lock == "shared")
    )
    if project is None:
        raise ResourceUnavailable(message)
    await require_project_visibility(db, context, project)
    return project
