from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import and_, delete, func, select
from sqlalchemy.exc import IntegrityError

from quirebase.access.items import (
    can_read_item,
    require_editable_item,
    visible_items_query,
)
from quirebase.audit import record_event
from quirebase.core.errors import (
    DomainError,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.library.item_lifecycle import (
    require_item_lifecycle_gate,
)
from quirebase.library.tag_recommendations import decoded_candidates
from quirebase.library.workflows import (
    item_tag_recommendation_status,
    request_item_tag_recommendation,
)
from quirebase.models import Item, ItemTag, ItemTagRecommendation, Tag, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class TagConflict(DomainError):
    pass


async def regenerate_item_tag_recommendation(db: AsyncSession, user: User, item_id: str) -> str:
    await require_editable_item(db, user, item_id)
    recommendation = await request_item_tag_recommendation(
        db, item_id, owner_id=user.id, force=True
    )
    await db.commit()
    return cast("str", recommendation.workflow_id)


def normalize_tag_name(name: str) -> str:
    normalized = " ".join(name.split())
    if not normalized or len(normalized) > 120:
        raise ValidationFailure("tag must contain 1 to 120 characters")
    return normalized


async def _lock_tag_write_gates(
    db: AsyncSession, tag_ids: list[str] | tuple[str, ...]
) -> dict[str, Tag]:
    """Lock Tag aggregates in stable ID order."""

    ordered_ids = tuple(sorted(set(tag_ids)))
    if not ordered_ids:
        return {}
    tags = (
        await db.scalars(
            select(Tag)
            .where(Tag.id.in_(ordered_ids))
            .order_by(Tag.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    return {tag.id: tag for tag in tags}


async def _tag_item_ids(db: AsyncSession, tag_ids: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if not tag_ids:
        return ()
    return tuple(
        sorted(
            set(
                (
                    await db.scalars(
                        select(ItemTag.item_id).where(ItemTag.tag_id.in_(tuple(set(tag_ids))))
                    )
                ).all()
            )
        )
    )


async def _find_or_create_tag(db: AsyncSession, user: User, normalized: str) -> Tag:
    tag = await db.scalar(select(Tag).where(Tag.name == normalized))
    if tag is None:
        tag = Tag(name=normalized, created_by=user.id)
        try:
            async with db.begin_nested():
                db.add(tag)
                await db.flush()
        except IntegrityError:
            tag = await db.scalar(select(Tag).where(Tag.name == normalized))
            if tag is None:
                raise
    return tag


async def get_or_create_tag(db: AsyncSession, user: User, name: str) -> Tag:
    normalized = normalize_tag_name(name)
    while True:
        candidate = await _find_or_create_tag(db, user, normalized)
        tag = (await _lock_tag_write_gates(db, (candidate.id,))).get(candidate.id)
        if tag is not None and tag.name == normalized:
            return tag


async def add_tag_to_item(db: AsyncSession, user: User, item_id: str, name: str) -> ItemTag:
    await require_editable_item(db, user, item_id)
    await require_item_lifecycle_gate(db, item_id)
    tag = await get_or_create_tag(db, user, name)
    assignment = await db.get(ItemTag, (item_id, tag.id), populate_existing=True)
    if assignment is None:
        created = False
        assignment = ItemTag(item_id=item_id, tag_id=tag.id)
        try:
            async with db.begin_nested():
                db.add(assignment)
                await db.flush()
                created = True
        except IntegrityError:
            assignment = await db.get(ItemTag, (item_id, tag.id), populate_existing=True)
            if assignment is None:
                raise
        if created:
            record_event(db, user.id, "tag.add", "item", item_id)
    await db.commit()
    return assignment


async def remove_tag_from_item(db: AsyncSession, user: User, item_id: str, tag_id: str) -> None:
    await require_editable_item(db, user, item_id)
    await require_item_lifecycle_gate(db, item_id)
    if tag_id not in await _lock_tag_write_gates(db, (tag_id,)):
        return
    assignment = await db.get(ItemTag, (item_id, tag_id), populate_existing=True)
    if assignment:
        await db.delete(assignment)
        await db.flush()
        record_event(
            db,
            user.id,
            "tag.remove",
            "item",
            item_id,
            detail={"tag_id": tag_id},
        )
        await db.commit()


async def rename_tag(db: AsyncSession, user: User, tag_id: str, name: str) -> Tag:
    if not await db.scalar(select(User.active).where(User.id == user.id)):
        raise ResourceUnavailable("tag not found or cannot be managed")
    tag = (await _lock_tag_write_gates(db, (tag_id,))).get(tag_id)
    if tag is None or (tag.created_by != user.id and user.role != "administrator"):
        raise ResourceUnavailable("tag not found or cannot be managed")
    normalized = normalize_tag_name(name)
    if await db.scalar(select(Tag.id).where(Tag.name == normalized, Tag.id != tag.id)):
        raise TagConflict("tag name already exists")
    tag.name = normalized
    record_event(db, user.id, "tag.rename", "tag", tag.id)
    await db.commit()
    return tag


async def delete_tag(db: AsyncSession, user: User, tag_id: str) -> None:
    if not await db.scalar(select(User.active).where(User.id == user.id)):
        raise ResourceUnavailable("tag not found or cannot be managed")
    candidate = await db.get(Tag, tag_id)
    if candidate is None or (candidate.created_by != user.id and user.role != "administrator"):
        raise ResourceUnavailable("tag not found or cannot be managed")
    tag = (await _lock_tag_write_gates(db, (tag_id,))).get(tag_id)
    if tag is None:
        raise TagConflict("tag changed while it was being deleted")
    await db.delete(tag)
    await db.flush()
    record_event(db, user.id, "tag.delete", "tag", tag_id)
    await db.commit()


async def list_accessible_tags_with_counts(db: AsyncSession, user: User) -> list[tuple[Tag, int]]:
    accessible_ids = visible_items_query(user).with_only_columns(Item.id).subquery()
    rows = (
        await db.execute(
            select(Tag, func.count(ItemTag.item_id))
            .outerjoin(
                ItemTag,
                and_(ItemTag.tag_id == Tag.id, ItemTag.item_id.in_(select(accessible_ids.c.id))),
            )
            .group_by(Tag.id)
            .order_by(Tag.name)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def get_tag_matrix_for_item(db: AsyncSession, user: User, item_id: str) -> dict[str, Any]:
    if not await can_read_item(db, user, item_id):
        raise ResourceUnavailable("item not found")
    all_tags = list((await db.scalars(select(Tag).order_by(Tag.name))).all())
    assigned_ids = set(
        (await db.scalars(select(ItemTag.tag_id).where(ItemTag.item_id == item_id))).all()
    )
    recommendation = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
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
    groups = [
        {
            "letter": letter,
            "tags": groups_dict[letter],
            "names": [t.name for t in groups_dict[letter]],
        }
        for letter in sorted_letters
    ]

    return {
        "groups": groups,
        "assigned_ids": assigned_ids,
        "recommended_ids": recommended_ids,
        "suggested_names": (*suggested_single_words, *suggested_phrases),
        "suggested_single_words": suggested_single_words,
        "suggested_phrases": suggested_phrases,
        "recommendation_state": state,
        "recommendation_error": recommendation_error,
    }


async def add_tags_to_item(
    db: AsyncSession,
    user: User,
    item_id: str,
    tag_ids: list[str],
    new_names: list[str] | None = None,
) -> None:
    """Add selected existing/new Tags without replacing the collection."""

    await require_editable_item(db, user, item_id)
    await require_item_lifecycle_gate(db, item_id)
    selected_ids = list(dict.fromkeys(tag_ids))
    requested_names = sorted({
        normalize_tag_name(raw_name) for raw_name in new_names or [] if raw_name.strip()
    })
    named_tags = [await _find_or_create_tag(db, user, normalized) for normalized in requested_names]
    selected_ids.extend(tag.id for tag in named_tags if tag.id not in selected_ids)
    locked_tags = await _lock_tag_write_gates(db, selected_ids)
    if any(
        locked_tags.get(tag.id) is None or tag.name != name
        for tag, name in zip(named_tags, requested_names, strict=True)
    ):
        raise TagConflict("tag changed while the collection was being saved")

    existing_ids = set(
        (await db.scalars(select(ItemTag.tag_id).where(ItemTag.item_id == item_id))).all()
    )
    changed = False
    for tag_id in selected_ids:
        if tag_id in locked_tags and tag_id not in existing_ids:
            try:
                async with db.begin_nested():
                    db.add(ItemTag(item_id=item_id, tag_id=tag_id))
                    await db.flush()
                    changed = True
            except IntegrityError:
                # Concurrent additive requests converge on the unique link.
                continue
    if changed:
        record_event(db, user.id, "tag.add_many", "item", item_id)
    await db.commit()


async def merge_tags(db: AsyncSession, user: User, source_tag_id: str, target_tag_id: str) -> Tag:
    if not await db.scalar(select(User.active).where(User.id == user.id)):
        raise ResourceUnavailable("tags not found")
    candidates = {
        tag.id: tag
        for tag in (
            await db.scalars(select(Tag).where(Tag.id.in_((source_tag_id, target_tag_id))))
        ).all()
    }
    source_candidate = candidates.get(source_tag_id)
    target_candidate = candidates.get(target_tag_id)
    if source_candidate is None or target_candidate is None:
        raise ResourceUnavailable("tags not found")
    if source_candidate.id == target_candidate.id:
        raise TagConflict("source and target tags must be different")
    if user.role != "administrator" and source_candidate.created_by != user.id:
        raise ResourceUnavailable("not authorized to merge these tags")
    tags = await _lock_tag_write_gates(db, (source_tag_id, target_tag_id))
    source_tag = tags.get(source_tag_id)
    target_tag = tags.get(target_tag_id)
    if source_tag is None or target_tag is None:
        raise ResourceUnavailable("tags not found")
    source_item_ids = set(
        (await db.scalars(select(ItemTag.item_id).where(ItemTag.tag_id == source_tag.id))).all()
    )
    target_item_ids = set(
        (await db.scalars(select(ItemTag.item_id).where(ItemTag.tag_id == target_tag.id))).all()
    )
    for item_id in sorted(source_item_ids - target_item_ids):
        db.add(ItemTag(item_id=item_id, tag_id=target_tag.id))
    await db.execute(delete(ItemTag).where(ItemTag.tag_id == source_tag.id))
    await db.delete(source_tag)
    await db.flush()

    record_event(
        db,
        user.id,
        "tag.merge",
        "tag",
        target_tag.id,
        detail={"merged_from": source_tag.name},
    )
    await db.commit()
    return target_tag
