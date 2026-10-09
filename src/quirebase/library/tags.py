from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sqlalchemy import and_, delete, func, select
from sqlalchemy.exc import IntegrityError

from quirebase.access import (
    ResourceAction,
    WorkspaceContext,
    require_action,
    require_workspace_action,
)
from quirebase.access.items import (
    require_editable_item,
    require_item_action,
    visible_items_query,
)
from quirebase.access.tags import visible_tags_query
from quirebase.audit import record_event
from quirebase.core.errors import (
    DomainError,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.core.persistence import conflict_insert
from quirebase.library.tag_recommendations import decoded_candidates
from quirebase.library.workflows import (
    item_tag_recommendation_status,
    request_item_tag_recommendation,
)
from quirebase.models import Item, ItemTag, ItemTagRecommendation, Tag, User

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class TagConflict(DomainError):
    pass


@dataclass(frozen=True)
class TagGroup:
    letter: str
    tags: tuple[Tag, ...]
    names: tuple[str, ...]


@dataclass(frozen=True)
class TagMatrix:
    groups: tuple[TagGroup, ...]
    assigned_ids: frozenset[UUID]
    recommended_ids: frozenset[UUID]
    suggested_names: tuple[str, ...]
    suggested_single_words: tuple[str, ...]
    suggested_phrases: tuple[str, ...]
    recommendation_state: str
    recommendation_error: str | None


async def regenerate_item_tag_recommendation(
    db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID
) -> str:
    await require_editable_item(db, user, workspace_id, item_id)
    recommendation = await request_item_tag_recommendation(
        db,
        item_id,
        workspace_id=workspace_id,
        actor_id=user.id,
        force=True,
    )
    await db.commit()
    return cast("str", recommendation.workflow_id)


def normalize_tag_name(name: str) -> str:
    normalized = " ".join(name.split())
    if not normalized or len(normalized) > 120:
        raise ValidationFailure("tag must contain 1 to 120 characters")
    return normalized


async def get_or_create_tag(db: AsyncSession, user: User, workspace_id: UUID, name: str) -> Tag:
    await require_workspace_action(db, user, workspace_id, ResourceAction.tag_create)
    normalized = normalize_tag_name(name)
    query = select(Tag).where(
        Tag.workspace_id == workspace_id, Tag.normalized_name == normalized.casefold()
    )
    tag = await db.scalar(query)
    if tag is not None:
        return tag
    tag = Tag(
        workspace_id=workspace_id,
        created_by=user.id,
        name=normalized,
        normalized_name=normalized.casefold(),
    )
    try:
        async with db.begin_nested():
            db.add(tag)
            await db.flush()
    except IntegrityError:
        existing = await db.scalar(query)
        if existing is None:
            raise
        return existing
    return tag


async def add_tag_to_item(
    db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID, name: str
) -> ItemTag:
    await require_item_action(db, user, workspace_id, item_id, ResourceAction.tag_use)
    tag = await get_or_create_tag(db, user, workspace_id, name)
    return await _add_tag_id_to_item(db, user, workspace_id, item_id, tag.id)


async def _add_tag_id_to_item(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    tag_id: UUID,
    *,
    commit: bool = True,
) -> ItemTag:
    created_ids = await _assign_item_tags(db, workspace_id, [item_id], tag_id)
    assignment = await db.scalar(
        select(ItemTag).where(
            ItemTag.workspace_id == workspace_id,
            ItemTag.item_id == item_id,
            ItemTag.tag_id == tag_id,
        )
    )
    if assignment is None:
        raise TagConflict("tag association changed concurrently; retry the action")
    if item_id in created_ids:
        record_event(
            db,
            user.id,
            "tag.add",
            "item",
            item_id,
            workspace_id=workspace_id,
            authorization_resource_action=ResourceAction.tag_use.value,
        )
    if commit:
        await db.commit()
    return assignment


async def add_existing_tag_to_item(
    db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID, tag_id: UUID
) -> ItemTag:
    await require_item_action(db, user, workspace_id, item_id, ResourceAction.tag_use)
    if (
        await db.scalar(select(Tag.id).where(Tag.id == tag_id, Tag.workspace_id == workspace_id))
        is None
    ):
        raise ResourceUnavailable("tag not found")
    try:
        return await _add_tag_id_to_item(db, user, workspace_id, item_id, tag_id)
    except IntegrityError as error:
        raise ResourceUnavailable("tag is no longer available") from error


async def remove_tag_from_item(
    db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID, tag_id: UUID
) -> None:
    await require_item_action(db, user, workspace_id, item_id, ResourceAction.tag_use)
    await _remove_tag_from_item(db, user, workspace_id, item_id, tag_id)


async def _remove_tag_from_item(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    tag_id: UUID,
    *,
    commit: bool = True,
) -> None:
    removed = (
        await db.scalar(
            delete(ItemTag)
            .where(
                ItemTag.workspace_id == workspace_id,
                ItemTag.item_id == item_id,
                ItemTag.tag_id == tag_id,
            )
            .returning(ItemTag.item_id)
        )
        is not None
    )
    if removed:
        record_event(
            db,
            user.id,
            "tag.remove",
            "item",
            item_id,
            detail={"tag_id": tag_id},
            workspace_id=workspace_id,
            authorization_resource_action=ResourceAction.tag_use.value,
        )
    if commit:
        await db.commit()


async def apply_item_tag_selection(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    *,
    remove_tag_ids: list[UUID] | None = None,
    tag_ids: list[UUID] | None = None,
    new_names: list[str] | None = None,
) -> None:
    """Apply a mixed Tag selection atomically.

    The individual association commands remain useful for single mutations and retain their
    historical commit-by-default behaviour. Batch callers use this operation so all removals,
    existing Tag additions and new Tag additions share one transaction.
    """
    await require_item_action(db, user, workspace_id, item_id, ResourceAction.tag_use)
    try:
        remove_ids = set(remove_tag_ids or [])
        add_ids = set(tag_ids or [])
        for name in new_names or []:
            tag = await get_or_create_tag(db, user, workspace_id, name)
            add_ids.add(tag.id)

        # Validate all requested existing Tags before changing any ItemTag rows. The association
        # mutations themselves then follow one deterministic key order across concurrent calls.
        for tag_id in sorted(add_ids):
            if (
                await db.scalar(
                    select(Tag.id).where(Tag.id == tag_id, Tag.workspace_id == workspace_id)
                )
                is None
            ):
                raise ResourceUnavailable("tag not found")

        for tag_id in sorted(remove_ids | add_ids):
            if tag_id in remove_ids:
                await _remove_tag_from_item(db, user, workspace_id, item_id, tag_id, commit=False)
            if tag_id in add_ids:
                try:
                    await _add_tag_id_to_item(db, user, workspace_id, item_id, tag_id, commit=False)
                except IntegrityError as error:
                    raise ResourceUnavailable("tag is no longer available") from error
        await db.commit()
    except BaseException:
        await db.rollback()
        raise


async def rename_tag(
    db: AsyncSession, user: User, workspace_id: UUID, tag_id: UUID, name: str
) -> Tag:
    await require_workspace_action(db, user, workspace_id, ResourceAction.tag_manage)
    tag = await db.scalar(
        select(Tag).where(Tag.workspace_id == workspace_id, Tag.id == tag_id).with_for_update()
    )
    if tag is None:
        raise ResourceUnavailable("tag not found")
    normalized = normalize_tag_name(name)
    normalized_key = normalized.casefold()
    if (
        await db.scalar(
            select(Tag.id).where(
                Tag.workspace_id == workspace_id,
                Tag.id != tag.id,
                Tag.normalized_name == normalized_key,
            )
        )
        is not None
    ):
        raise TagConflict("tag name already exists")
    try:
        tag.name = normalized
        tag.normalized_name = normalized_key
        await db.flush()
        record_event(
            db,
            user.id,
            "tag.rename",
            "tag",
            tag.id,
            workspace_id=workspace_id,
            authorization_resource_action=ResourceAction.tag_manage.value,
        )
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise TagConflict("tag name already exists") from error
    return tag


async def delete_tag(db: AsyncSession, user: User, workspace_id: UUID, tag_id: UUID) -> None:
    await require_workspace_action(db, user, workspace_id, ResourceAction.tag_manage)
    # Deleting a taxonomy root must block FK association inserts until commit.
    tag = await db.scalar(
        select(Tag).where(Tag.workspace_id == workspace_id, Tag.id == tag_id).with_for_update()
    )
    if tag is None:
        raise ResourceUnavailable("tag not found")
    await db.delete(tag)
    await db.flush()
    record_event(
        db,
        user.id,
        "tag.delete",
        "tag",
        tag_id,
        workspace_id=workspace_id,
        authorization_resource_action=ResourceAction.tag_manage.value,
    )
    await db.commit()


async def list_accessible_tags_with_counts(
    db: AsyncSession, context: WorkspaceContext
) -> list[tuple[Tag, int]]:
    require_action(context, ResourceAction.workspace_read)
    workspace_id = context.workspace_id
    accessible_ids = visible_items_query(workspace_id).with_only_columns(Item.id).subquery()
    rows = (
        await db.execute(
            select(Tag, func.count(ItemTag.item_id))
            .outerjoin(
                ItemTag,
                and_(
                    ItemTag.workspace_id == workspace_id,
                    ItemTag.tag_id == Tag.id,
                    ItemTag.item_id.in_(select(accessible_ids.c.id)),
                ),
            )
            .where(
                Tag.workspace_id == workspace_id,
                Tag.id.in_(visible_tags_query(workspace_id).with_only_columns(Tag.id)),
            )
            .group_by(Tag.id)
            .order_by(Tag.name)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def get_tag_matrix_for_item(db: AsyncSession, item: Item) -> TagMatrix:
    """Build the Tag matrix for an Item already loaded through its authorized section."""
    workspace_id, item_id = item.workspace_id, item.id
    all_tags = list(await db.scalars(visible_tags_query(workspace_id).order_by(Tag.name, Tag.id)))
    assigned_ids = set(
        (
            await db.scalars(
                select(ItemTag.tag_id).where(
                    ItemTag.workspace_id == workspace_id,
                    ItemTag.item_id == item_id,
                )
            )
        ).all()
    )
    recommendation = await db.scalar(
        select(ItemTagRecommendation).where(
            ItemTagRecommendation.workspace_id == workspace_id,
            ItemTagRecommendation.item_id == item_id,
        )
    )
    single_words, phrases = decoded_candidates(recommendation)
    candidate_names = {*single_words, *phrases}
    folded_candidates = {name.casefold() for name in candidate_names}
    recommended_ids = {tag.id for tag in all_tags if tag.name.casefold() in folded_candidates}
    existing_names = {tag.name.casefold() for tag in all_tags}
    suggested_single_words = tuple(
        name for name in single_words if name.casefold() not in existing_names
    )
    suggested_phrases = tuple(name for name in phrases if name.casefold() not in existing_names)
    state, recommendation_error = await item_tag_recommendation_status(recommendation)

    # Group by first letter A-Z or '#'
    groups_dict: dict[str, list[Tag]] = {}
    for tag in all_tags:
        first_char = tag.name[0].upper() if tag.name else "#"
        if not ("A" <= first_char <= "Z"):
            first_char = "#"
        groups_dict.setdefault(first_char, []).append(tag)

    sorted_letters = sorted(groups_dict.keys(), key=lambda k: (k == "#", k))
    groups = tuple(
        TagGroup(
            letter=str(letter),
            tags=tuple(groups_dict[letter]),
            names=tuple(tag.name for tag in groups_dict[letter]),
        )
        for letter in sorted_letters
    )

    return TagMatrix(
        groups=groups,
        assigned_ids=frozenset(assigned_ids),
        recommended_ids=frozenset(recommended_ids),
        suggested_names=(*suggested_single_words, *suggested_phrases),
        suggested_single_words=suggested_single_words,
        suggested_phrases=suggested_phrases,
        recommendation_state=str(state),
        recommendation_error=(str(recommendation_error) if recommendation_error else None),
    )


async def merge_tags(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    source_tag_id: UUID,
    target_tag_id: UUID,
) -> Tag:
    if source_tag_id == target_tag_id:
        raise TagConflict("source and target tags must be different")
    await require_workspace_action(db, user, workspace_id, ResourceAction.tag_manage)
    locked_tags: dict[UUID, Tag | None] = {}
    for tag_id in sorted((source_tag_id, target_tag_id)):
        query = select(Tag).where(Tag.id == tag_id, Tag.workspace_id == workspace_id)
        if tag_id == source_tag_id:
            query = query.with_for_update()
        else:
            query = query.with_for_update(key_share=True)
        locked_tags[tag_id] = await db.scalar(query)
    source_tag = locked_tags[source_tag_id]
    target_tag = locked_tags[target_tag_id]
    if source_tag is None or target_tag is None:
        raise ResourceUnavailable("tags not found")
    if source_tag.workspace_id != target_tag.workspace_id:
        raise ResourceUnavailable("Tags not found")

    item_ids = list(
        await db.scalars(
            select(ItemTag.item_id).where(
                ItemTag.workspace_id == workspace_id, ItemTag.tag_id == source_tag.id
            )
        )
    )
    await _assign_item_tags(db, workspace_id, item_ids, target_tag.id)
    await db.execute(
        delete(ItemTag).where(ItemTag.workspace_id == workspace_id, ItemTag.tag_id == source_tag.id)
    )
    await db.delete(source_tag)
    await db.flush()

    record_event(
        db,
        user.id,
        "tag.merge",
        "tag",
        target_tag.id,
        detail={"merged_from": source_tag.name},
        workspace_id=workspace_id,
        authorization_resource_action=ResourceAction.tag_manage.value,
    )
    await db.commit()
    return target_tag


async def _assign_item_tags(
    db: AsyncSession, workspace_id: UUID, item_ids: Sequence[UUID], tag_id: UUID
) -> set[UUID]:
    """Add links for authorized roots; report only this call's new links."""
    ordered = sorted(set(item_ids))
    created_ids: set[UUID] = set()
    if not ordered:
        return created_ids
    # Roll back every chunk if a non-identity constraint fails. The caller
    # still owns the surrounding transaction and any authorized root locks.
    async with db.begin_nested():
        for offset in range(0, len(ordered), 500):
            created_ids.update(
                await db.scalars(
                    conflict_insert(db, ItemTag)
                    .values([
                        {"workspace_id": workspace_id, "item_id": item_id, "tag_id": tag_id}
                        for item_id in ordered[offset : offset + 500]
                    ])
                    .on_conflict_do_nothing(index_elements=[ItemTag.item_id, ItemTag.tag_id])
                    .returning(ItemTag.item_id)
                )
            )
    return created_ids
