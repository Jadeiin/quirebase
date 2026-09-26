"""Explicit, detached copies between Workspace resource boundaries."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select

from quirebase.access.items import require_readable_item
from quirebase.access.workspaces import Capability, require_workspace_capability
from quirebase.audit import record_event
from quirebase.core.errors import ValidationFailure
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.models import (
    Attachment,
    AttachmentRole,
    FileRevision,
    FileRevisionProcessingState,
    Item,
    ItemAuthor,
    ItemIdentifier,
    User,
    Workspace,
)
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_ITEM_FIELDS = (
    "title",
    "abstract",
    "publication_date",
    "publication_title",
    "volume",
    "issue",
    "pages",
    "affiliation",
    "publisher",
    "place_published",
    "journal_abbreviation",
    "doi",
    "identifiers",
    "reference_type",
    "authors",
    "editors",
    "bibtex_id",
    "bibtex_type",
    "urls",
    "keywords",
    "custom_fields",
)


@dataclass(frozen=True, slots=True)
class _RevisionSnapshot:
    id: str
    object_key: str
    thumbnail_object_key: str | None
    size: int
    mime_type: str
    original_name: str
    page_count: int | None
    full_text: str | None
    page_geometry: str | None
    processing_state: FileRevisionProcessingState


@dataclass(frozen=True, slots=True)
class _AttachmentSnapshot:
    id: str
    object_key: str
    size: int
    mime_type: str
    original_name: str
    role: AttachmentRole | None


def _revision_snapshot(revision: FileRevision) -> _RevisionSnapshot:
    return _RevisionSnapshot(
        id=revision.id,
        object_key=revision.object_key,
        thumbnail_object_key=revision.thumbnail_object_key,
        size=revision.size,
        mime_type=revision.mime_type,
        original_name=revision.original_name,
        page_count=revision.page_count,
        full_text=revision.full_text,
        page_geometry=revision.page_geometry,
        processing_state=revision.processing_state,
    )


def _attachment_snapshot(attachment: Attachment) -> _AttachmentSnapshot:
    return _AttachmentSnapshot(
        id=attachment.id,
        object_key=attachment.object_key,
        size=attachment.size,
        mime_type=attachment.mime_type,
        original_name=attachment.original_name,
        role=attachment.role,
    )


async def _copy_object(source_key: str, suffix: ObjectSuffix) -> tuple[str, int]:
    store = get_object_store()
    response = await store.get(source_key)
    copied = await store.put_object(
        uuid4(),
        suffix,
        response.body,
        max_bytes=response.metadata.size,
    )
    return copied.key, copied.size


async def copy_item_to_workspace(
    db: AsyncSession,
    actor: User,
    source_workspace_id: str,
    target_workspace_id: str,
    item_id: str,
) -> Item:
    """Create a new canonical Item and independent file objects in the target Workspace."""
    if source_workspace_id == target_workspace_id:
        raise ValidationFailure("source and target Workspaces must be different")
    actor_id = actor.id
    await require_workspace_capability(db, actor, source_workspace_id, Capability.workspace_export)
    source = await require_readable_item(db, actor, source_workspace_id, item_id)
    source_version = source.version
    item_fields: dict[str, Any] = {field: getattr(source, field) for field in _ITEM_FIELDS}
    author_links = tuple(
        sorted(
            (
                link.author_id,
                link.position,
                link.role,
                link.is_corresponding,
            )
            for link in source.author_links
        )
    )
    identifier_links = tuple(
        sorted((link.provider, link.value) for link in source.identifier_links)
    )
    revisions = tuple(
        _revision_snapshot(revision)
        for revision in (
            (
                await db.scalars(
                    select(FileRevision)
                    .where(
                        FileRevision.workspace_id == source_workspace_id,
                        FileRevision.item_id == item_id,
                    )
                    .order_by(FileRevision.created_at, FileRevision.id)
                )
            ).all()
        )
    )
    if any(
        revision.processing_state != FileRevisionProcessingState.ready for revision in revisions
    ):
        raise ValidationFailure("all File Revisions must be ready before copying the Item")
    attachments = tuple(
        _attachment_snapshot(attachment)
        for attachment in (
            (
                await db.scalars(
                    select(Attachment)
                    .where(
                        Attachment.workspace_id == source_workspace_id,
                        Attachment.item_id == item_id,
                    )
                    .order_by(Attachment.created_at, Attachment.id)
                )
            ).all()
        )
    )
    await require_workspace_capability(db, actor, target_workspace_id, Capability.items_create)
    if revisions or attachments:
        await require_workspace_capability(db, actor, target_workspace_id, Capability.files_manage)

    # Release every authorization/read lock before object-store GET/PUT. The
    # copied snapshot is revalidated under short-lived locks immediately before
    # target rows are created.
    await db.commit()

    copied_keys: list[str] = []
    try:
        copied_revision_objects: list[tuple[str, int, str | None, int | None]] = []
        for revision in revisions:
            revision_key, revision_size = await _copy_object(revision.object_key, ObjectSuffix.PDF)
            copied_keys.append(revision_key)
            thumbnail_key = None
            thumbnail_size = None
            if revision.thumbnail_object_key:
                thumbnail_key, thumbnail_size = await _copy_object(
                    revision.thumbnail_object_key, ObjectSuffix.PNG
                )
                copied_keys.append(thumbnail_key)
            copied_revision_objects.append((
                revision_key,
                revision_size,
                thumbnail_key,
                thumbnail_size,
            ))

        copied_attachment_objects: list[tuple[str, int]] = []
        for attachment in attachments:
            attachment_key, attachment_size = await _copy_object(
                attachment.object_key, ObjectSuffix.BINARY
            )
            copied_keys.append(attachment_key)
            copied_attachment_objects.append((attachment_key, attachment_size))

        # Account governance locks Users before Workspaces. Use the same order,
        # then freeze both membership paths and the source snapshot only for the
        # final database mutation.
        current_actor = await db.scalar(
            select(User)
            .where(User.id == actor_id, User.active.is_(True))
            .with_for_update(read=True)
        )
        if current_actor is None:
            raise ValidationFailure("copy authorization is no longer available")
        locked_workspace_ids = tuple(
            (
                await db.scalars(
                    select(Workspace.id)
                    .where(Workspace.id.in_((source_workspace_id, target_workspace_id)))
                    .order_by(Workspace.id)
                    .with_for_update(read=True)
                )
            ).all()
        )
        if set(locked_workspace_ids) != {source_workspace_id, target_workspace_id}:
            raise ValidationFailure("source or target Workspace is no longer available")
        source_context = await require_workspace_capability(
            db, current_actor, source_workspace_id, Capability.workspace_export
        )
        target_context = await require_workspace_capability(
            db, current_actor, target_workspace_id, Capability.items_create
        )
        if revisions or attachments:
            await require_workspace_capability(
                db, current_actor, target_workspace_id, Capability.files_manage
            )

        current_source = await db.scalar(
            select(Item)
            .where(Item.id == item_id, Item.workspace_id == source_workspace_id)
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        if (
            current_source is None
            or current_source.version != source_version
            or any(getattr(current_source, field) != value for field, value in item_fields.items())
        ):
            raise ValidationFailure("source Item changed while its files were copied")
        current_revisions = tuple(
            _revision_snapshot(revision)
            for revision in (
                (
                    await db.scalars(
                        select(FileRevision)
                        .where(
                            FileRevision.workspace_id == source_workspace_id,
                            FileRevision.item_id == item_id,
                        )
                        .order_by(FileRevision.created_at, FileRevision.id)
                        .execution_options(populate_existing=True)
                        .with_for_update(read=True)
                    )
                ).all()
            )
        )
        current_attachments = tuple(
            _attachment_snapshot(attachment)
            for attachment in (
                (
                    await db.scalars(
                        select(Attachment)
                        .where(
                            Attachment.workspace_id == source_workspace_id,
                            Attachment.item_id == item_id,
                        )
                        .order_by(Attachment.created_at, Attachment.id)
                        .execution_options(populate_existing=True)
                        .with_for_update(read=True)
                    )
                ).all()
            )
        )
        current_author_links = tuple(
            sorted(
                (link.author_id, link.position, link.role, link.is_corresponding)
                for link in (
                    await db.scalars(select(ItemAuthor).where(ItemAuthor.item_id == item_id))
                ).all()
            )
        )
        current_identifier_links = tuple(
            sorted(
                (link.provider, link.value)
                for link in (
                    await db.scalars(
                        select(ItemIdentifier).where(ItemIdentifier.item_id == item_id)
                    )
                ).all()
            )
        )
        if (
            current_revisions != revisions
            or current_attachments != attachments
            or current_author_links != author_links
            or current_identifier_links != identifier_links
        ):
            raise ValidationFailure("source Item changed while its files were copied")

        target = Item(
            workspace_id=target_workspace_id,
            created_by=current_actor.id,
            **item_fields,
        )
        db.add(target)
        await db.flush()

        db.add_all([
            ItemAuthor(
                item_id=target.id,
                author_id=author_id,
                position=position,
                role=role,
                is_corresponding=is_corresponding,
            )
            for author_id, position, role, is_corresponding in author_links
        ])
        db.add_all([
            ItemIdentifier(item_id=target.id, provider=provider, value=value)
            for provider, value in identifier_links
        ])

        copied_revisions: list[FileRevision] = []
        for revision, copied_object in zip(revisions, copied_revision_objects, strict=True):
            revision_key, revision_size, thumbnail_key, thumbnail_size = copied_object
            copied_revision = FileRevision(
                workspace_id=target_workspace_id,
                item_id=target.id,
                object_key=revision_key,
                size=revision_size,
                mime_type=revision.mime_type,
                original_name=revision.original_name,
                page_count=revision.page_count,
                full_text=revision.full_text,
                page_geometry=revision.page_geometry,
                processing_state=revision.processing_state,
                thumbnail_object_key=thumbnail_key,
                thumbnail_size=thumbnail_size,
                created_by=current_actor.id,
            )
            db.add(copied_revision)
            copied_revisions.append(copied_revision)

        for attachment, copied_attachment_object in zip(
            attachments, copied_attachment_objects, strict=True
        ):
            attachment_key, attachment_size = copied_attachment_object
            db.add(
                Attachment(
                    workspace_id=target_workspace_id,
                    item_id=target.id,
                    object_key=attachment_key,
                    size=attachment_size,
                    mime_type=attachment.mime_type,
                    original_name=attachment.original_name,
                    role=attachment.role,
                    created_by=current_actor.id,
                )
            )

        await db.flush()
        index = search_index(db)
        await index.index_item(db, target.id)
        for copied_revision in copied_revisions:
            await index.index_revision(db, copied_revision.id)
        mapping = {"source_item_id": item_id, "target_item_id": target.id}
        record_event(
            db,
            current_actor.id,
            "workspace.item.copy.export",
            "item",
            item_id,
            detail={**mapping, "target_workspace_id": target_workspace_id},
            workspace_id=source_workspace_id,
            target_ids=[target.id],
            authorization_role=source_context.role.value,
            authorization_capability=Capability.workspace_export.value,
        )
        record_event(
            db,
            current_actor.id,
            "workspace.item.copy.import",
            "item",
            target.id,
            detail={**mapping, "source_workspace_id": source_workspace_id},
            workspace_id=target_workspace_id,
            target_ids=[item_id],
            authorization_role=target_context.role.value,
            authorization_capability=Capability.items_create.value,
        )
        await db.commit()
        return target
    except BaseException:
        await db.rollback()
        store = get_object_store()
        for key in copied_keys:
            with suppress(Exception):
                await store.delete(key)
        raise
