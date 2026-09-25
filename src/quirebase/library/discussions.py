from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from quirebase.access.items import can_read_item
from quirebase.access.workspaces import (
    Capability,
    require_project_context,
    require_workspace_capability,
)
from quirebase.audit import record_event
from quirebase.core.errors import (
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.models import DiscussionMessage, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def add_discussion_message(
    db: AsyncSession, user: User, workspace_id: str, item_id: str, body: str
) -> DiscussionMessage:
    context = await require_workspace_capability(
        db, user, workspace_id, Capability.discussion_write
    )
    if not await can_read_item(db, user, workspace_id, item_id):
        raise ResourceUnavailable("item not found or inaccessible")
    content = body.strip()
    if not content or len(content) > 20_000:
        raise ValidationFailure("message must contain 1 to 20000 characters")
    message = DiscussionMessage(
        workspace_id=workspace_id, item_id=item_id, author_id=user.id, body=content
    )
    db.add(message)
    await db.flush()
    record_event(
        db,
        user.id,
        "discussion.create",
        "discussion",
        message.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.discussion_write.value,
    )
    await db.commit()
    return message


async def delete_discussion_message(
    db: AsyncSession, user: User, workspace_id: str, item_id: str, message_id: str
) -> None:
    context = await require_workspace_capability(
        db, user, workspace_id, Capability.discussion_write
    )
    if not await can_read_item(db, user, workspace_id, item_id):
        raise ResourceUnavailable("discussion message not found or cannot be deleted")
    message = await db.get(DiscussionMessage, message_id)
    if (
        message is None
        or message.workspace_id != workspace_id
        or message.item_id != item_id
        or message.author_id != user.id
    ):
        raise ResourceUnavailable("discussion message not found or cannot be deleted")
    await db.delete(message)
    record_event(
        db,
        user.id,
        "discussion.delete",
        "discussion",
        message_id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.discussion_write.value,
    )
    await db.commit()


async def moderate_discussion_message(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    message_id: str,
    reason: str,
) -> None:
    context = await require_workspace_capability(
        db, user, workspace_id, Capability.discussion_moderate
    )
    if not await can_read_item(db, user, workspace_id, item_id):
        raise ResourceUnavailable("discussion message not found")
    message = await db.scalar(
        select(DiscussionMessage)
        .where(
            DiscussionMessage.id == message_id,
            DiscussionMessage.workspace_id == workspace_id,
            DiscussionMessage.item_id == item_id,
        )
        .with_for_update()
    )
    if message is None:
        raise ResourceUnavailable("discussion message not found")
    if message.author_id == user.id:
        raise ValidationFailure("authors must use ordinary message deletion")
    explanation = reason.strip()
    if not explanation or len(explanation) > 2000:
        raise ValidationFailure("moderation reason must contain 1 to 2000 characters")
    await db.delete(message)
    record_event(
        db,
        user.id,
        "discussion.moderate.delete",
        "discussion",
        message_id,
        detail={"reason": explanation, "author_id": message.author_id},
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.discussion_moderate.value,
    )
    await db.commit()


async def list_project_discussion_messages(
    db: AsyncSession, user: User, workspace_id: str, project_id: str
) -> list[DiscussionMessage]:
    await require_project_context(db, user, workspace_id, project_id, Capability.workspace_read)
    return list(
        (
            await db.scalars(
                select(DiscussionMessage)
                .options(selectinload(DiscussionMessage.author))
                .where(
                    DiscussionMessage.workspace_id == workspace_id,
                    DiscussionMessage.project_id == project_id,
                )
                .order_by(DiscussionMessage.created_at, DiscussionMessage.id)
            )
        ).all()
    )


async def add_project_discussion_message(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    body: str,
) -> DiscussionMessage:
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.discussion_write
    )
    content = body.strip()
    if not content or len(content) > 20_000:
        raise ValidationFailure("message must contain 1 to 20000 characters")
    message = DiscussionMessage(
        workspace_id=workspace_id,
        project_id=project_id,
        author_id=user.id,
        body=content,
    )
    message.author = user
    db.add(message)
    await db.flush()
    record_event(
        db,
        user.id,
        "project.discussion.create",
        "discussion",
        message.id,
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.workspace.role.value,
        authorization_capability=Capability.discussion_write.value,
    )
    await db.commit()
    return message


async def delete_project_discussion_message(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    message_id: str,
) -> None:
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.discussion_write
    )
    message = await db.scalar(
        select(DiscussionMessage).where(
            DiscussionMessage.id == message_id,
            DiscussionMessage.workspace_id == workspace_id,
            DiscussionMessage.project_id == project_id,
            DiscussionMessage.author_id == user.id,
        )
    )
    if message is None:
        raise ResourceUnavailable("discussion message not found or cannot be deleted")
    await db.delete(message)
    record_event(
        db,
        user.id,
        "project.discussion.delete",
        "discussion",
        message.id,
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.workspace.role.value,
        authorization_capability=Capability.discussion_write.value,
    )
    await db.commit()


async def moderate_project_discussion_message(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    message_id: str,
    reason: str,
) -> None:
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.discussion_moderate
    )
    message = await db.scalar(
        select(DiscussionMessage)
        .where(
            DiscussionMessage.id == message_id,
            DiscussionMessage.workspace_id == workspace_id,
            DiscussionMessage.project_id == project_id,
        )
        .with_for_update()
    )
    if message is None:
        raise ResourceUnavailable("discussion message not found")
    if message.author_id == user.id:
        raise ValidationFailure("authors must use ordinary message deletion")
    explanation = reason.strip()
    if not explanation or len(explanation) > 2000:
        raise ValidationFailure("moderation reason must contain 1 to 2000 characters")
    await db.delete(message)
    record_event(
        db,
        user.id,
        "project.discussion.moderate.delete",
        "discussion",
        message_id,
        detail={"reason": explanation, "author_id": message.author_id},
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.workspace.role.value,
        authorization_capability=Capability.discussion_moderate.value,
    )
    await db.commit()
