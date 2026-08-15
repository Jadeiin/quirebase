from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.access.items import can_read_item
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import Attachment, FileRevision, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def require_revision(db: Session, user: User, revision_id: str) -> FileRevision:
    revision = db.get(FileRevision, revision_id)
    if revision is None or not can_read_item(db, user, revision.item_id):
        raise ResourceUnavailable("PDF revision not found")
    return revision


def can_read_attachment(db: Session, user: User, attachment: Attachment) -> bool:
    return can_read_item(db, user, attachment.item_id)


def require_attachment(db: Session, user: User, item_id: str, attachment_id: str) -> Attachment:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.item_id != item_id or not can_read_item(db, user, item_id):
        raise ResourceUnavailable("attachment not found")
    return attachment
