"""Document values persisted by authorized commands and durable transactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, update

from quirebase.core.persistence import Repository
from quirebase.models import (
    Attachment,
    ExportArtifact,
    FileRevision,
    PdfAnnotation,
    PdfAnnotationReply,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class FileRevisionRepository(Repository[FileRevision]):
    model_type = FileRevision


class AttachmentRepository(Repository[Attachment]):
    model_type = Attachment


class ExportArtifactRepository(Repository[ExportArtifact]):
    model_type = ExportArtifact
    id_attribute = "workflow_id"


class AnnotationRepository(Repository[PdfAnnotation]):
    model_type = PdfAnnotation

    async def current_version(self, workspace_id: UUID, annotation_id: UUID) -> int | None:
        return await self.session.scalar(
            select(PdfAnnotation.version).where(
                PdfAnnotation.workspace_id == workspace_id, PdfAnnotation.id == annotation_id
            )
        )

    async def _update_active(
        self,
        workspace_id: UUID,
        annotation_id: UUID,
        expected_version: int,
        values: dict[str, object],
        changed_at: datetime,
    ) -> int | None:
        return await self.session.scalar(
            update(PdfAnnotation)
            .where(
                PdfAnnotation.workspace_id == workspace_id,
                PdfAnnotation.id == annotation_id,
                PdfAnnotation.version == expected_version,
                PdfAnnotation.deleted_at.is_(None),
            )
            .values(**values, version=PdfAnnotation.version + 1, updated_at=changed_at)
            .returning(PdfAnnotation.version)
        )

    async def replace_content(
        self,
        workspace_id: UUID,
        annotation_id: UUID,
        expected_version: int,
        values: dict[str, object],
        changed_at: datetime,
    ) -> int | None:
        return await self._update_active(
            workspace_id, annotation_id, expected_version, values, changed_at
        )

    async def soft_delete(
        self, workspace_id: UUID, annotation_id: UUID, expected_version: int, changed_at: datetime
    ) -> int | None:
        return await self._update_active(
            workspace_id,
            annotation_id,
            expected_version,
            {"deleted_at": changed_at, "deleted_by_moderation": False},
            changed_at,
        )

    async def restore_deleted(
        self, workspace_id: UUID, annotation_id: UUID, expected_version: int, changed_at: datetime
    ) -> int | None:
        return await self.session.scalar(
            update(PdfAnnotation)
            .where(
                PdfAnnotation.workspace_id == workspace_id,
                PdfAnnotation.id == annotation_id,
                PdfAnnotation.version == expected_version,
                PdfAnnotation.deleted_at.is_not(None),
                PdfAnnotation.deleted_by_moderation.is_(False),
            )
            .values(deleted_at=None, version=PdfAnnotation.version + 1, updated_at=changed_at)
            .returning(PdfAnnotation.version)
        )

    async def apply_moderation(
        self,
        workspace_id: UUID,
        annotation_id: UUID,
        expected_version: int,
        values: dict[str, object],
        changed_at: datetime,
    ) -> int | None:
        return await self._update_active(
            workspace_id, annotation_id, expected_version, values, changed_at
        )


class AnnotationReplyRepository(Repository[PdfAnnotationReply]):
    model_type = PdfAnnotationReply

    async def current_version(self, workspace_id: UUID, reply_id: UUID) -> int | None:
        return await self.session.scalar(
            select(PdfAnnotationReply.version).where(
                PdfAnnotationReply.workspace_id == workspace_id, PdfAnnotationReply.id == reply_id
            )
        )

    async def _update_active(
        self,
        workspace_id: UUID,
        reply_id: UUID,
        expected_version: int,
        values: dict[str, object],
        changed_at: datetime,
    ) -> int | None:
        return await self.session.scalar(
            update(PdfAnnotationReply)
            .where(
                PdfAnnotationReply.workspace_id == workspace_id,
                PdfAnnotationReply.id == reply_id,
                PdfAnnotationReply.version == expected_version,
                PdfAnnotationReply.deleted_at.is_(None),
            )
            .values(**values, version=PdfAnnotationReply.version + 1, updated_at=changed_at)
            .returning(PdfAnnotationReply.version)
        )

    async def replace_body(
        self,
        workspace_id: UUID,
        reply_id: UUID,
        expected_version: int,
        body: str,
        changed_at: datetime,
    ) -> int | None:
        return await self._update_active(
            workspace_id, reply_id, expected_version, {"body": body}, changed_at
        )

    async def soft_delete(
        self, workspace_id: UUID, reply_id: UUID, expected_version: int, changed_at: datetime
    ) -> int | None:
        return await self._update_active(
            workspace_id, reply_id, expected_version, {"deleted_at": changed_at}, changed_at
        )

    async def restore_deleted(
        self, workspace_id: UUID, reply_id: UUID, expected_version: int, changed_at: datetime
    ) -> int | None:
        return await self.session.scalar(
            update(PdfAnnotationReply)
            .where(
                PdfAnnotationReply.workspace_id == workspace_id,
                PdfAnnotationReply.id == reply_id,
                PdfAnnotationReply.version == expected_version,
                PdfAnnotationReply.deleted_at.is_not(None),
            )
            .values(deleted_at=None, version=PdfAnnotationReply.version + 1, updated_at=changed_at)
            .returning(PdfAnnotationReply.version)
        )
