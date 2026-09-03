from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from quirebase.core.errors import ResourceUnavailable
from quirebase.library.tags import (
    TagConflict,
    add_tag_to_item,
    get_tag_matrix_for_item,
    merge_tags,
    remove_tag_from_item,
    set_item_tags,
)
from quirebase.models import AuditEvent, Item, ItemTag, ItemTagRecommendation, Tag, User


@pytest.mark.anyio
async def test_remove_tag_from_item_records_the_business_change(async_db):
    db = async_db
    user = User(username="tag-remover", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Tagged Item", created_by=user.id)
    db.add(item)
    await db.flush()
    assignment = await add_tag_to_item(db, user, item.id, "Temporary")
    tag_id = assignment.tag_id

    await remove_tag_from_item(db, user, item.id, tag_id)

    assert await db.get(ItemTag, (item.id, tag_id)) is None
    event = await db.scalar(
        select(AuditEvent).where(AuditEvent.action == "tag.remove", AuditEvent.target_id == item.id)
    )
    assert event is not None
    assert json.loads(event.detail) == {"tag_id": tag_id}


@pytest.mark.anyio
async def test_get_tag_matrix_for_item(async_db):
    db = async_db
    user = User(username="tag_matrix_user", password_hash="hash")
    db.add(user)
    await db.flush()

    t1 = Tag(name="Algorithms", created_by=user.id)
    t2 = Tag(name="Bioinformatics", created_by=user.id)
    t3 = Tag(name="Compiler", created_by=user.id)
    db.add_all([t1, t2, t3])
    await db.flush()

    item = Item(
        title="Compiler Optimization Algorithms",
        abstract="Efficient algorithms for compiler backend.",
        keywords="Compiler; Graph Neural Networks; graph neural networks; New Optimizer",
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
async def test_set_item_tags(async_db):
    db = async_db
    user = User(username="batch_tag_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Machine Learning", created_by=user.id)
    db.add(item)
    await db.flush()

    await set_item_tags(db, user, item.id, [], ["AI", "Deep Learning", "Vision"])
    current_tags = list((await db.scalars(select(Tag.name))).all())
    assert "AI" in current_tags
    assert "Deep Learning" in current_tags

    # Test set_item_tags to only AI and Vision
    tag_ai = await db.scalar(select(Tag).where(Tag.name == "AI"))
    tag_vision = await db.scalar(select(Tag).where(Tag.name == "Vision"))
    assert tag_ai is not None and tag_vision is not None
    await set_item_tags(db, user, item.id, [tag_ai.id, tag_vision.id])
    await db.commit()

    assigned_tag_ids = list(
        (await db.scalars(select(ItemTag.tag_id).where(ItemTag.item_id == item.id))).all()
    )
    assert len(assigned_tag_ids) == 2
    assert tag_ai.id in assigned_tag_ids
    assert tag_vision.id in assigned_tag_ids


@pytest.mark.anyio
async def test_set_tags_normalizes_names_and_skips_empty_values(async_db):
    db = async_db
    user = User(username="normalized_tag_user", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Normalization", created_by=user.id)
    db.add(item)
    await db.flush()

    await set_item_tags(db, user, item.id, [], ["  Machine   Learning ", "\t"])
    assigned_names = list(
        (
            await db.scalars(
                select(Tag.name).join(ItemTag).where(ItemTag.item_id == item.id).order_by(Tag.name)
            )
        ).all()
    )
    assert assigned_names == ["Machine Learning"]


@pytest.mark.anyio
async def test_merge_tags_relinks_items_and_rejects_self_merge(async_db):
    db = async_db
    admin = User(username="admin_merge", password_hash="hash", role="administrator")
    db.add(admin)
    await db.flush()
    first = Item(title="First Item", created_by=admin.id)
    second = Item(title="Second Item", created_by=admin.id)
    source = Tag(name="ML", created_by=admin.id)
    target = Tag(name="Machine Learning", created_by=admin.id)
    db.add_all([first, second, source, target])
    await db.flush()
    db.add_all([
        ItemTag(item_id=first.id, tag_id=source.id),
        ItemTag(item_id=second.id, tag_id=source.id),
        ItemTag(item_id=second.id, tag_id=target.id),
    ])
    await db.commit()

    merged = await merge_tags(db, admin, source.id, target.id)

    assert merged.id == target.id
    assert await db.get(Tag, source.id) is None
    assert set(
        (await db.scalars(select(ItemTag.item_id).where(ItemTag.tag_id == target.id))).all()
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
    source = Tag(name="Protected source", created_by=source_owner.id)
    target = Tag(name="Shared target", created_by=other_user.id)
    db.add_all([source, target])
    await db.commit()

    with pytest.raises(ResourceUnavailable, match="not authorized"):
        await merge_tags(db, other_user, source.id, target.id)

    assert await db.get(Tag, source.id) is not None
