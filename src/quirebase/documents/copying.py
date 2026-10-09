"""Document-owned snapshots, object copying and transactional installation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from advanced_alchemy.types import FileObject
from sqlalchemy import select

from quirebase.core.errors import ValidationFailure
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.documents.objects import delete_unreferenced_objects
from quirebase.models import Attachment, AttachmentRole, FileRevision, FileRevisionProcessingState
from quirebase.search import search_index

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class _RevisionSnapshot:
    id: UUID
    file: dict[str, Any]
    thumbnail: dict[str, Any] | None
    page_count: int | None
    full_text: str | None
    page_geometry: list[list[float]] | None
    processing_state: FileRevisionProcessingState


@dataclass(frozen=True, slots=True)
class _AttachmentSnapshot:
    id: UUID
    file: dict[str, Any]
    role: AttachmentRole | None


async def _snapshot_documents(
    db: AsyncSession, workspace_id: UUID, item_id: UUID, *, lock: bool = False
) -> tuple[tuple[_RevisionSnapshot, ...], tuple[_AttachmentSnapshot, ...]]:
    revision_query = (
        select(FileRevision)
        .where(FileRevision.workspace_id == workspace_id, FileRevision.item_id == item_id)
        .order_by(FileRevision.created_at, FileRevision.id)
        .execution_options(populate_existing=True)
    )
    attachment_query = (
        select(Attachment)
        .where(Attachment.workspace_id == workspace_id, Attachment.item_id == item_id)
        .order_by(Attachment.created_at, Attachment.id)
        .execution_options(populate_existing=True)
    )
    if lock:
        revision_query = revision_query.with_for_update(read=True)
        attachment_query = attachment_query.with_for_update(read=True)
    revisions = tuple(
        _RevisionSnapshot(
            id=revision.id,
            file=deepcopy(revision.file.to_dict()),
            thumbnail=deepcopy(revision.thumbnail.to_dict()) if revision.thumbnail else None,
            page_count=revision.page_count,
            full_text=revision.full_text,
            page_geometry=deepcopy(revision.page_geometry),
            processing_state=revision.processing_state,
        )
        for revision in await db.scalars(revision_query)
    )
    attachments = tuple(
        _AttachmentSnapshot(attachment.id, deepcopy(attachment.file.to_dict()), attachment.role)
        for attachment in await db.scalars(attachment_query)
    )
    if any(revision.file.get("size") is None for revision in revisions):
        raise ValueError("persisted File Revision requires a file size")
    if any(attachment.file.get("size") is None for attachment in attachments):
        raise ValueError("persisted Attachment requires a file size")
    return revisions, attachments


class ItemDocumentCopy:
    """One detached copy, whose descriptors and cleanup receipts remain Documents-owned.

    The caller authorizes both Workspaces, snapshots the Item, and ends its read
    transaction before copy_objects. Installation requires current authorization
    and the source Item's shared root lock; it retains Document locks and writes
    through the caller's Session without completing its transaction. On failure,
    the caller rolls back before discard so an ambiguous commit remains protected.
    """

    def __init__(
        self,
        workspace_id: UUID,
        item_id: UUID,
        revisions: tuple[_RevisionSnapshot, ...],
        attachments: tuple[_AttachmentSnapshot, ...],
    ) -> None:
        self._workspace_id = workspace_id
        self._item_id = item_id
        self._revisions = revisions
        self._attachments = attachments
        self._object_keys: list[str] = []
        self._revision_objects: list[tuple[str, int, str | None, int | None]] = []
        self._attachment_objects: list[tuple[str, int]] = []
        self._copied = False

    async def _copy_object(self, source_key: str, suffix: ObjectSuffix) -> tuple[str, int]:
        store = get_object_store()
        response = await store.get(source_key)
        copied = await store.put_object(
            uuid4(), suffix, response.body, max_bytes=response.metadata.size
        )
        self._object_keys.append(copied.key)
        return copied.key, copied.size

    async def copy_objects(self) -> None:
        """Copy independent UUID objects outside the caller's database transaction."""
        for revision in self._revisions:
            key, size = await self._copy_object(revision.file["filename"], ObjectSuffix.PDF)
            thumbnail_key, thumbnail_size = (
                await self._copy_object(revision.thumbnail["filename"], ObjectSuffix.PNG)
                if revision.thumbnail is not None
                else (None, None)
            )
            self._revision_objects.append((key, size, thumbnail_key, thumbnail_size))
        for attachment in self._attachments:
            self._attachment_objects.append(
                await self._copy_object(attachment.file["filename"], ObjectSuffix.BINARY)
            )
        self._copied = True

    async def install(
        self, db: AsyncSession, actor_id: UUID, workspace_id: UUID, item_id: UUID
    ) -> None:
        """Recheck source descriptors, then install and index the copied Documents."""
        if not self._copied:
            raise ValueError("copy Document objects before installation")
        current = await _snapshot_documents(db, self._workspace_id, self._item_id, lock=True)
        if current != (self._revisions, self._attachments):
            raise ValidationFailure("source Item changed while its files were copied")
        revisions: list[FileRevision] = []
        for source, copied in zip(self._revisions, self._revision_objects, strict=True):
            key, size, thumbnail_key, thumbnail_size = copied
            revision = FileRevision(
                workspace_id=workspace_id,
                item_id=item_id,
                page_count=source.page_count,
                full_text=source.full_text,
                page_geometry=source.page_geometry,
                processing_state=source.processing_state,
                created_by=actor_id,
                file=FileObject(**(source.file | {"filename": key, "size": size})),
                thumbnail=FileObject(
                    **(source.thumbnail | {"filename": thumbnail_key, "size": thumbnail_size})
                )
                if source.thumbnail is not None
                else None,
            )
            db.add(revision)
            revisions.append(revision)
        for source_attachment, copied_attachment in zip(
            self._attachments, self._attachment_objects, strict=True
        ):
            key, size = copied_attachment
            db.add(
                Attachment(
                    workspace_id=workspace_id,
                    item_id=item_id,
                    file=FileObject(**(source_attachment.file | {"filename": key, "size": size})),
                    role=source_attachment.role,
                    created_by=actor_id,
                )
            )
        await db.flush()
        index = search_index(db)
        for revision in revisions:
            await index.index_revision(db, revision.id)

    async def discard(self, db: AsyncSession) -> None:
        """After caller rollback, release only objects without committed references."""
        await delete_unreferenced_objects(db, self._object_keys)


async def prepare_item_document_copy(
    db: AsyncSession, workspace_id: UUID, item_id: UUID
) -> ItemDocumentCopy:
    """Snapshot authorized source Documents without taking ownership of the transaction."""
    revisions, attachments = await _snapshot_documents(db, workspace_id, item_id)
    if any(
        revision.processing_state is not FileRevisionProcessingState.ready for revision in revisions
    ):
        raise ValidationFailure("all File Revisions must be ready before copying the Item")
    return ItemDocumentCopy(workspace_id, item_id, revisions, attachments)
