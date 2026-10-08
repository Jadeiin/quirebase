"""Project persistence; participation and authorization stay in commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from quirebase.core.persistence import Repository, Service, conflict_insert
from quirebase.models import Project, ProjectItem, ProjectParticipant

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID


class ProjectRepository(Repository[Project]):
    model_type = Project


class ProjectService(Service[Project]):
    repository_type = ProjectRepository


class ProjectParticipantRepository(Repository[ProjectParticipant]):
    model_type = ProjectParticipant

    async def ensure_selection(
        self, workspace_id: UUID, project_id: UUID, membership_id: UUID, user_id: UUID
    ) -> tuple[ProjectParticipant, bool]:
        try:
            async with self.session.begin_nested():
                participant = await self.add(
                    ProjectParticipant(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        workspace_member_id=membership_id,
                        user_id=user_id,
                    )
                )
        except IntegrityError:
            existing = await self.session.scalar(
                select(ProjectParticipant)
                .where(
                    ProjectParticipant.workspace_id == workspace_id,
                    ProjectParticipant.project_id == project_id,
                    ProjectParticipant.workspace_member_id == membership_id,
                    ProjectParticipant.user_id == user_id,
                )
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if existing is not None:
                return existing, False
            # Leave may have removed the conflicting selection before this read.
            # Let the command report a conflict rather than recreate the selection.
            raise
        return participant, True

    async def remove_membership_selection(
        self, workspace_id: UUID, project_id: UUID, membership_id: UUID
    ) -> UUID | None:
        return await self.session.scalar(
            delete(ProjectParticipant)
            .where(
                ProjectParticipant.workspace_id == workspace_id,
                ProjectParticipant.project_id == project_id,
                ProjectParticipant.workspace_member_id == membership_id,
            )
            .returning(ProjectParticipant.id)
        )

    async def remove_user_selection(
        self, workspace_id: UUID, project_id: UUID, user_id: UUID
    ) -> UUID | None:
        return await self.session.scalar(
            delete(ProjectParticipant)
            .where(
                ProjectParticipant.workspace_id == workspace_id,
                ProjectParticipant.project_id == project_id,
                ProjectParticipant.user_id == user_id,
            )
            .returning(ProjectParticipant.id)
        )


class ProjectItemRepository(Repository[ProjectItem]):
    model_type = ProjectItem

    async def add_missing(
        self, workspace_id: UUID, project_id: UUID, item_ids: Sequence[UUID], actor_id: UUID
    ) -> int:
        """Add authorized Item links under the command's Project root guard."""
        ordered = sorted(set(item_ids))
        if not ordered:
            return 0
        inserted = 0
        async with self.session.begin_nested():
            for offset in range(0, len(ordered), 500):
                added = await self.session.scalars(
                    conflict_insert(self.session, ProjectItem)
                    .values([
                        {
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "item_id": item_id,
                            "added_by": actor_id,
                        }
                        for item_id in ordered[offset : offset + 500]
                    ])
                    .on_conflict_do_nothing(
                        index_elements=[
                            ProjectItem.workspace_id,
                            ProjectItem.project_id,
                            ProjectItem.item_id,
                        ]
                    )
                    .returning(ProjectItem.item_id)
                )
                inserted += len(added.all())
        return inserted
