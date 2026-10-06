from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import exists, select

from quirebase.models import Project, ProjectMember, ProjectParticipation, WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def check_project_integrity(db: AsyncSession) -> list[str]:
    """Diagnose participation drift caused by writes outside Project commands."""
    implicit_projects = await db.scalars(
        select(Project.id)
        .where(
            Project.participation == ProjectParticipation.workspace,
            exists().where(ProjectMember.project_id == Project.id),
        )
        .order_by(Project.id)
    )
    orphan_participants = await db.scalars(
        select(ProjectMember.id)
        .where(
            ~exists().where(
                WorkspaceMember.workspace_id == ProjectMember.workspace_id,
                WorkspaceMember.user_id == ProjectMember.user_id,
                WorkspaceMember.terminated_at.is_(None),
            )
        )
        .order_by(ProjectMember.id)
    )
    # Suspension retains explicit participation for reactivation; only termination
    # removes it. Account activity therefore does not enter this invariant.
    return [
        *(
            f"Workspace-mode Project {project_id} has explicit participants"
            for project_id in implicit_projects
        ),
        *(
            f"Project participant {member_id} has no current Workspace membership"
            for member_id in orphan_participants
        ),
    ]
