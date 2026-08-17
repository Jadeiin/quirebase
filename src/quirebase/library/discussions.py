from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from quirebase.access.items import can_read_item
from quirebase.audit import record_event
from quirebase.core.errors import (
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.models import DiscussionMessage, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def add_discussion_message(db: Session, user: User, item_id: str, body: str) -> DiscussionMessage:
    if not can_read_item(db, user, item_id):
        raise ResourceUnavailable("item not found or inaccessible")
    content = body.strip()
    if not content or len(content) > 20_000:
        raise ValidationFailure("message must contain 1 to 20000 characters")
    message = DiscussionMessage(item_id=item_id, author_id=user.id, body=content)
    db.add(message)
    db.flush()
    record_event(db, user.id, "discussion.create", "discussion", message.id)
    db.commit()
    return message


def delete_discussion_message(db: Session, user: User, item_id: str, message_id: str) -> None:
    message = db.get(DiscussionMessage, message_id)
    if (
        message is None
        or message.item_id != item_id
        or (message.author_id != user.id and user.role != "administrator")
    ):
        raise ResourceUnavailable("discussion message not found or cannot be deleted")
    db.delete(message)
    record_event(db, user.id, "discussion.delete", "discussion", message_id)
    db.commit()


def list_discussion_messages(db: Session, user: User, item_id: str) -> list[DiscussionMessage]:
    if not can_read_item(db, user, item_id):
        raise ResourceUnavailable("item not found or inaccessible")
    return list(
        db.scalars(
            select(DiscussionMessage)
            .options(selectinload(DiscussionMessage.author))
            .where(DiscussionMessage.item_id == item_id)
            .order_by(DiscussionMessage.created_at)
        ).all()
    )
