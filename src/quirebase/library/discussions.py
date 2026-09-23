from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.access.projects import require_project_member
from quirebase.audit import record_event
from quirebase.core.errors import (
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.models import DiscussionMessage, ProjectItem, ProjectMember, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def add_discussion_message(
    db: AsyncSession, user: User, project_item_id: str, body: str
) -> DiscussionMessage:
    project_item = await db.get(ProjectItem, project_item_id)
    if project_item is None:
        raise ResourceUnavailable("project item not found or inaccessible")
    await require_project_member(db, user, project_item.project_id)
    content = body.strip()
    if not content or len(content) > 20_000:
        raise ValidationFailure("message must contain 1 to 20000 characters")
    message = DiscussionMessage(project_item_id=project_item_id, author_id=user.id, body=content)
    db.add(message)
    await db.flush()
    record_event(db, user.id, "discussion.create", "discussion", message.id)
    await db.commit()
    return message


async def project_item_for_user(
    db: AsyncSession, user: User, item_id: str, project_id: str | None = None
) -> ProjectItem:
    query = (
        select(ProjectItem)
        .join(ProjectMember, ProjectMember.project_id == ProjectItem.project_id)
        .where(ProjectItem.item_id == item_id, ProjectMember.user_id == user.id)
        .order_by(ProjectItem.project_id)
    )
    if project_id:
        query = query.where(ProjectItem.project_id == project_id)
    project_item = await db.scalar(query.limit(1))
    if project_item is None:
        raise ResourceUnavailable("project item not found or inaccessible")
    return project_item


async def delete_discussion_message(
    db: AsyncSession, user: User, project_item_id: str, message_id: str
) -> None:
    message = await db.get(DiscussionMessage, message_id)
    project_item = await db.get(ProjectItem, project_item_id)
    if (
        message is None
        or project_item is None
        or message.project_item_id != project_item_id
        or (message.author_id != user.id and user.role != "administrator")
    ):
        raise ResourceUnavailable("discussion message not found or cannot be deleted")
    if user.role != "administrator":
        await require_project_member(db, user, project_item.project_id)
    await db.delete(message)
    record_event(db, user.id, "discussion.delete", "discussion", message_id)
    await db.commit()
