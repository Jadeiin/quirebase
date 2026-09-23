from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from quirebase.core.errors import ResourceUnavailable
from quirebase.library.tags import (
    TagConflict,
    add_tag_to_item,
    apply_item_tag_selection,
    get_tag_matrix_for_item,
    merge_tags,
    remove_tag_from_item,
)
from quirebase.models import (
    AuditEvent,
    Item,
    ItemTagRecommendation,
    PersonalItemTag,
    Tag,
    User,
)


@pytest.mark.anyio
async def test_remove_tag_from_item_records_the_business_change(async_db):
    db = async_db
    user = User(username="tag-remover", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Tagged Item", owner_id=user.id, created_by=user.id)
    db.add(item)
    await db.flush()
    assignment = await add_tag_to_item(db, user, item.id, "Temporary")
    tag_id = assignment.tag_id

    await remove_tag_from_item(db, user, item.id, tag_id)

    assert await db.get(PersonalItemTag, (item.id, tag_id)) is None
    event = await db.scalar(
        select(AuditEvent).where(AuditEvent.action == "tag.remove", AuditEvent.target_id == item.id)
    )
    assert event is not None
    assert json.loads(event.detail) == {"tag_id": tag_id}


@pytest.mark.anyio
async def test_tag_selection_rolls_back_when_a_later_change_is_invalid(async_db):
    db = async_db
    user = User(username="tag-selection-atomic", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Atomic Tag Selection", owner_id=user.id, created_by=user.id)
    db.add(item)
    await db.flush()
    assignment = await add_tag_to_item(db, user, item.id, "Keep Me")
    item_id = item.id
    tag_id = assignment.tag_id

    with pytest.raises(ResourceUnavailable, match="tag not found"):
        await apply_item_tag_selection(
            db,
            user,
            item_id,
            remove_tag_ids=[tag_id],
            tag_ids=["missing-tag"],
        )

    assert await db.get(PersonalItemTag, (item_id, tag_id)) is not None


@pytest.mark.anyio
async def test_get_tag_matrix_for_item(async_db):
    db = async_db
    user = User(username="tag_matrix_user", password_hash="hash")
    db.add(user)
    await db.flush()

    t1 = Tag(user_id=user.id, name="Algorithms", normalized_name="algorithms", created_by=user.id)
    t2 = Tag(
        user_id=user.id, name="Bioinformatics", normalized_name="bioinformatics", created_by=user.id
    )
    t3 = Tag(user_id=user.id, name="Compiler", normalized_name="compiler", created_by=user.id)
    db.add_all([t1, t2, t3])
    await db.flush()

    item = Item(
        title="Compiler Optimization Algorithms",
        abstract="Efficient algorithms for compiler backend.",
        keywords="Compiler; Graph Neural Networks; graph neural networks; New Optimizer",
        owner_id=user.id,
        created_by=user.id,
    )
    db.add(item)
    await db.flush()
    db.add(
        ItemTagRecommendation(
            item_id=item.id,
            generation_token=1,
            single_words=json.dumps(["Algorithms", "Compiler"]),
            phrases=json.dumps(["Graph Neural Networks", "New Optimizer"]),
            generated_at=datetime.now(UTC),
        )
    )
    await add_tag_to_item(db, user, item.id, "Algorithms")
    await db.commit()

    matrix = await get_tag_matrix_for_item(db, user, item.id)
    assert len(matrix["groups"]) >= 3
    assert t1.id in matrix["assigned_ids"]
    assert t2.id not in matrix["assigned_ids"]
    assert t1.id in matrix["recommended_ids"]
    assert t3.id in matrix["recommended_ids"]
    assert matrix["suggested_names"] == ("Graph Neural Networks", "New Optimizer")


@pytest.mark.anyio
async def test_tag_matrix_conceals_foreign_tags_without_accessible_items(async_db):
    db = async_db
    viewer = User(username="matrix_viewer", password_hash="hash")
    author = User(username="matrix_author", password_hash="hash")
    db.add_all([viewer, author])
    await db.flush()
    attached_tag = Tag(
        user_id=author.id,
        name="Attached to visible item",
        normalized_name="attached to visible item",
        created_by=author.id,
    )
    foreign_orphan = Tag(
        user_id=author.id,
        name="Foreign orphan",
        normalized_name="foreign orphan",
        created_by=author.id,
    )
    own_orphan = Tag(
        user_id=viewer.id, name="Own orphan", normalized_name="own orphan", created_by=viewer.id
    )
    db.add_all([attached_tag, foreign_orphan, own_orphan])
    await db.flush()
    item = Item(title="Viewer item", owner_id=viewer.id, created_by=viewer.id)
    db.add(item)
    await db.flush()
    await db.commit()

    matrix = await get_tag_matrix_for_item(db, viewer, item.id)

    names = {tag.name for group in matrix["groups"] for tag in group["tags"]}
    assert "Attached to visible item" not in names
    assert "Own orphan" in names
    assert "Foreign orphan" not in names


@pytest.mark.anyio
async def test_merge_tags_relinks_items_and_rejects_self_merge(async_db):
    db = async_db
    admin = User(username="admin_merge", password_hash="hash", role="administrator")
    db.add(admin)
    await db.flush()
    first = Item(title="First Item", owner_id=admin.id, created_by=admin.id)
    second = Item(title="Second Item", owner_id=admin.id, created_by=admin.id)
    source = Tag(user_id=admin.id, name="ML", normalized_name="ml", created_by=admin.id)
    target = Tag(
        user_id=admin.id,
        name="Machine Learning",
        normalized_name="machine learning",
        created_by=admin.id,
    )
    db.add_all([first, second, source, target])
    await db.flush()
    db.add_all([
        PersonalItemTag(item_id=first.id, tag_id=source.id, owner_id=admin.id),
        PersonalItemTag(item_id=second.id, tag_id=source.id, owner_id=admin.id),
        PersonalItemTag(item_id=second.id, tag_id=target.id, owner_id=admin.id),
    ])
    await db.commit()

    merged = await merge_tags(db, admin, source.id, target.id)

    assert merged.id == target.id
    assert await db.get(Tag, source.id) is None
    assert set(
        (
            await db.scalars(
                select(PersonalItemTag.item_id).where(PersonalItemTag.tag_id == target.id)
            )
        ).all()
    ) == {
        first.id,
        second.id,
    }
    with pytest.raises(TagConflict, match="different"):
        await merge_tags(db, admin, target.id, target.id)


@pytest.mark.anyio
async def test_merge_tags_requires_source_tag_ownership(async_db):
    db = async_db
    source_owner = User(username="source_owner", password_hash="hash")
    other_user = User(username="other_user", password_hash="hash")
    db.add_all([source_owner, other_user])
    await db.flush()
    source = Tag(
        user_id=source_owner.id,
        name="Protected source",
        normalized_name="protected source",
        created_by=source_owner.id,
    )
    target = Tag(
        user_id=source_owner.id,
        name="Shared target",
        normalized_name="shared target",
        created_by=source_owner.id,
    )
    db.add_all([source, target])
    await db.commit()

    with pytest.raises(ResourceUnavailable, match="not authorized"):
        await merge_tags(db, other_user, source.id, target.id)

    assert await db.get(Tag, source.id) is not None
