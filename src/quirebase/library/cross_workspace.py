"""Explicit, detached copies between Workspace resource boundaries."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from quirebase.access import ResourceAction, require_workspace_action
from quirebase.access.items import require_readable_item
from quirebase.audit import record_event
from quirebase.core.errors import ValidationFailure
from quirebase.documents import prepare_item_document_copy
from quirebase.models import (
    Item,
    ItemAuthor,
    ItemIdentifier,
    User,
    Workspace,
)
from quirebase.search import search_index

if TYPE_CHECKING:
    from uuid import UUID

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


async def copy_item_to_workspace(
    db: AsyncSession,
    actor: User,
    source_workspace_id: UUID,
    target_workspace_id: UUID,
    item_id: UUID,
) -> Item:
    """Create a new canonical Item and independent file objects in the target Workspace."""
    if source_workspace_id == target_workspace_id:
        raise ValidationFailure("source and target Workspaces must be different")
    actor_id = actor.id
    await require_workspace_action(db, actor, source_workspace_id, ResourceAction.workspace_export)
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
    documents = await prepare_item_document_copy(db, source_workspace_id, item_id)
    await require_workspace_action(db, actor, target_workspace_id, ResourceAction.item_create)

    # Release every authorization/read lock before object-store GET/PUT. The
    # copied snapshot is revalidated under short-lived locks immediately before
    # target rows are created.
    await db.commit()

    try:
        await documents.copy_objects()

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
        source_context = await require_workspace_action(
            db, current_actor, source_workspace_id, ResourceAction.workspace_export
        )
        target_context = await require_workspace_action(
            db, current_actor, target_workspace_id, ResourceAction.item_create
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
        if current_author_links != author_links or current_identifier_links != identifier_links:
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

        await documents.install(db, current_actor.id, target_workspace_id, target.id)
        await search_index(db).index_item(db, target.id)
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
            authorization_resource_action=ResourceAction.workspace_export.value,
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
            authorization_resource_action=ResourceAction.item_create.value,
        )
        await db.commit()
        return target
    except BaseException:
        await db.rollback()
        # A commit can succeed on the database server while its acknowledgement
        # is lost locally. Recheck durable references before deleting copied
        # objects so an ambiguous commit cannot leave committed rows dangling.
        with suppress(Exception):
            await documents.discard(db)
        raise
