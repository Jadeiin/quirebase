from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select

from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.models import (
    Project,
    ProjectItem,
    ProjectMember,
    ProjectState,
    ProjectVisibility,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ProjectAdminSummary:
    project: Project
    creator: User
    member_count: int
    item_count: int


async def list_projects_for_admin(
    db: AsyncSession,
    admin: User,
    *,
    search: str = "",
    state: str = "",
    visibility: str = "",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ProjectAdminSummary], int]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")

    filters = []
    cleaned_search = search.strip()
    if cleaned_search:
        term = f"%{cleaned_search}%"
        filters.append(
            or_(Project.name.ilike(term), Project.id == cleaned_search, User.username.ilike(term))
        )
    try:
        if state:
            filters.append(Project.state == ProjectState(state))
        if visibility:
            filters.append(Project.visibility == ProjectVisibility(visibility))
    except ValueError as error:
        raise ValidationFailure("invalid project filter") from error

    member_count = (
        select(func.count(ProjectMember.user_id))
        .where(ProjectMember.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )
    item_count = (
        select(func.count(ProjectItem.item_id))
        .where(ProjectItem.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )
    base = select(Project, User, member_count, item_count).join(User, User.id == Project.created_by)
    count_query = (
        select(func.count(Project.id))
        .select_from(Project)
        .join(User, User.id == Project.created_by)
    )
    if filters:
        base = base.where(*filters)
        count_query = count_query.where(*filters)
    total = await db.scalar(count_query) or 0
    offset = max(0, (page - 1) * page_size)
    rows = (
        await db.execute(
            base.order_by(Project.updated_at.desc(), Project.name).offset(offset).limit(page_size)
        )
    ).all()
    return [
        ProjectAdminSummary(
            project=row[0],
            creator=row[1],
            member_count=row[2],
            item_count=row[3],
        )
        for row in rows
    ], total
