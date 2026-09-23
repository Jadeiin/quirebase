"""Explicit, detached copies between Workspace resource boundaries."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from quirebase.access.items import require_readable_item
from quirebase.access.workspaces import Capability, require_workspace_capability
from quirebase.audit import record_event
from quirebase.core.errors import ValidationFailure
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.models import (
    Attachment,
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
    source_context = await require_workspace_capability(
        db, actor, source_workspace_id, Capability.workspace_export
    )
    await require_readable_item(db, actor, source_workspace_id, item_id)
    # Hold both tenancy roots in stable order so membership/lifecycle changes cannot
    # cross the authorization boundary while the detached object snapshot is copied.
    locked_workspace_ids = tuple(
        (
            await db.scalars(
                select(Workspace.id)
                .where(Workspace.id.in_((source_workspace_id, target_workspace_id)))
                .order_by(Workspace.id)
                .with_for_update()
            )
        ).all()
    )
    if set(locked_workspace_ids) != {source_workspace_id, target_workspace_id}:
        raise ValidationFailure("source or target Workspace is no longer available")
    source_context = await require_workspace_capability(
        db, actor, source_workspace_id, Capability.workspace_export
    )
    target_context = await require_workspace_capability(
        db, actor, target_workspace_id, Capability.items_create
    )
    source = await db.scalar(
        select(Item)
        .where(Item.id == item_id, Item.workspace_id == source_workspace_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if source is None:
        raise ValidationFailure("source Item is no longer available")
    revisions = list(
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
    if any(
        revision.processing_state != FileRevisionProcessingState.ready for revision in revisions
    ):
        raise ValidationFailure("all File Revisions must be ready before copying the Item")
    attachments = list(
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
    if revisions or attachments:
        await require_workspace_capability(db, actor, target_workspace_id, Capability.files_manage)

    copied_keys: list[str] = []
    try:
        target = Item(
            workspace_id=target_workspace_id,
            created_by=actor.id,
            **{field: getattr(source, field) for field in _ITEM_FIELDS},
        )
        db.add(target)
        await db.flush()

        author_links = list(
            (
                await db.scalars(
                    select(ItemAuthor)
                    .where(ItemAuthor.item_id == item_id)
                    .order_by(ItemAuthor.role, ItemAuthor.position)
                )
            ).all()
        )
        db.add_all([
            ItemAuthor(
                item_id=target.id,
                author_id=link.author_id,
                position=link.position,
                role=link.role,
                is_corresponding=link.is_corresponding,
            )
            for link in author_links
        ])
        identifier_links = list(
            (
                await db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item_id))
            ).all()
        )
        db.add_all([
            ItemIdentifier(item_id=target.id, provider=link.provider, value=link.value)
            for link in identifier_links
        ])

        copied_revisions: list[FileRevision] = []
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
                created_by=actor.id,
            )
            db.add(copied_revision)
            copied_revisions.append(copied_revision)

        for attachment in attachments:
            attachment_key, attachment_size = await _copy_object(
                attachment.object_key, ObjectSuffix.BINARY
            )
            copied_keys.append(attachment_key)
            db.add(
                Attachment(
                    workspace_id=target_workspace_id,
                    item_id=target.id,
                    object_key=attachment_key,
                    size=attachment_size,
                    mime_type=attachment.mime_type,
                    original_name=attachment.original_name,
                    role=attachment.role,
                    created_by=actor.id,
                )
            )

        await db.flush()
        index = search_index(db)
        await index.index_item(db, target.id)
        for revision in copied_revisions:
            await index.index_revision(db, revision.id)
        mapping = {"source_item_id": source.id, "target_item_id": target.id}
        record_event(
            db,
            actor.id,
            "workspace.item.copy.export",
            "item",
            source.id,
            detail={**mapping, "target_workspace_id": target_workspace_id},
            workspace_id=source_workspace_id,
            target_ids=[target.id],
            authorization_role=source_context.role.value,
            authorization_capability=Capability.workspace_export.value,
        )
        record_event(
            db,
            actor.id,
            "workspace.item.copy.import",
            "item",
            target.id,
            detail={**mapping, "source_workspace_id": source_workspace_id},
            workspace_id=target_workspace_id,
            target_ids=[source.id],
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
