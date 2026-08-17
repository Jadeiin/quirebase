from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.access.items import can_read_item
from quirebase.access.projects import project_member
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import (
    AnnotationScope,
    FileRevision,
    PdfAnnotation,
    ProjectRole,
    SystemRole,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def can_edit_annotation(db: Session, user: User, annotation: PdfAnnotation) -> bool:
    if annotation.author_id == user.id or user.role == SystemRole.administrator.value:
        return True
    if annotation.scope is AnnotationScope.project and annotation.project_id:
        member = project_member(db, user, annotation.project_id)
        return member is not None and member.role == ProjectRole.owner
    return False


def require_editable_annotation(
    db: Session, user: User, item_id: str, annotation_id: str
) -> PdfAnnotation:
    record = db.get(PdfAnnotation, annotation_id)
    record_revision = db.get(FileRevision, record.file_revision_id) if record else None
    if (
        record is None
        or record.deleted_at
        or not can_read_item(db, user, item_id)
        or record_revision is None
        or record_revision.item_id != item_id
        or not can_edit_annotation(db, user, record)
    ):
        raise ResourceUnavailable("annotation not found or cannot be edited")
    return record
