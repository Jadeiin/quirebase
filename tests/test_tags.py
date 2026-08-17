from __future__ import annotations

from sqlalchemy import select

from quirebase.library.tags import (
    add_tag_to_item,
    batch_add_tags_to_item,
    get_tag_matrix_for_item,
    merge_tags,
    recommend_tags_for_item,
    set_item_tags,
)
from quirebase.models import Item, ItemTag, Tag, User


def test_recommend_tags_for_item(db):
    user = User(username="tag_rec_user", password_hash="hash")
    db.add(user)
    db.flush()

    # Create library tags
    tag_transformer = Tag(name="Transformer", created_by=user.id)
    tag_quantum = Tag(name="Quantum", created_by=user.id)
    tag_robotics = Tag(name="Robotics", created_by=user.id)
    db.add_all([tag_transformer, tag_quantum, tag_robotics])
    db.flush()

    item = Item(
        title="Attention is all you need for transformer architectures",
        abstract="We propose a new model based entirely on attention mechanisms without recurrence for robotics applications.",
        created_by=user.id,
    )
    db.add(item)
    db.flush()

    recommended = recommend_tags_for_item(db, user, item.id)
    rec_names = {t.name for t in recommended}
    assert "Transformer" in rec_names
    assert "Robotics" in rec_names
    assert "Quantum" not in rec_names


def test_get_tag_matrix_for_item(db):
    user = User(username="tag_matrix_user", password_hash="hash")
    db.add(user)
    db.flush()

    t1 = Tag(name="Algorithms", created_by=user.id)
    t2 = Tag(name="Bioinformatics", created_by=user.id)
    t3 = Tag(name="Compiler", created_by=user.id)
    db.add_all([t1, t2, t3])
    db.flush()

    item = Item(
        title="Compiler Optimization Algorithms",
        abstract="Efficient algorithms for compiler backend.",
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    add_tag_to_item(db, user, item.id, "Algorithms")
    db.commit()

    matrix = get_tag_matrix_for_item(db, user, item.id)
    assert len(matrix["groups"]) >= 3
    assert t1.id in matrix["assigned_ids"]
    assert t2.id not in matrix["assigned_ids"]
    assert t1.id in matrix["recommended_ids"]
    assert t3.id in matrix["recommended_ids"]


def test_batch_add_and_set_item_tags(db):
    user = User(username="batch_tag_user", password_hash="hash")
    db.add(user)
    db.flush()

    item = Item(title="Machine Learning", created_by=user.id)
    db.add(item)
    db.flush()

    created_tags = batch_add_tags_to_item(db, user, item.id, ["AI", "Deep Learning", "Vision"])
    db.commit()

    assert len(created_tags) == 3
    current_tags = list(db.scalars(select(Tag.name)).all())
    assert "AI" in current_tags
    assert "Deep Learning" in current_tags

    # Test set_item_tags to only AI and Vision
    tag_ai = db.scalar(select(Tag).where(Tag.name == "AI"))
    tag_vision = db.scalar(select(Tag).where(Tag.name == "Vision"))
    set_item_tags(db, user, item.id, [tag_ai.id, tag_vision.id])
    db.commit()

    assigned_tag_ids = list(
        db.scalars(select(ItemTag.tag_id).where(ItemTag.item_id == item.id)).all()
    )
    assert len(assigned_tag_ids) == 2
    assert tag_ai.id in assigned_tag_ids
    assert tag_vision.id in assigned_tag_ids


def test_batch_and_set_tags_normalize_names_and_skip_empty_values(db):
    user = User(username="normalized_tag_user", password_hash="hash")
    db.add(user)
    db.flush()
    item = Item(title="Normalization", created_by=user.id)
    db.add(item)
    db.flush()

    created = batch_add_tags_to_item(db, user, item.id, ["  Deep   Learning  ", "  "])
    assert [tag.name for tag in created] == ["Deep Learning"]

    set_item_tags(db, user, item.id, [], ["  Machine   Learning ", "\t"])
    assigned_names = list(
        db.scalars(
            select(Tag.name).join(ItemTag).where(ItemTag.item_id == item.id).order_by(Tag.name)
        ).all()
    )
    assert assigned_names == ["Machine Learning"]


def test_merge_tags(db):
    admin = User(username="admin_merge", password_hash="hash", role="administrator")
    db.add(admin)
    db.flush()

    item1 = Item(title="Item 1", created_by=admin.id)
    item2 = Item(title="Item 2", created_by=admin.id)
    tag_old = Tag(name="ML", created_by=admin.id)
    tag_new = Tag(name="Machine Learning", created_by=admin.id)
    db.add_all([item1, item2, tag_old, tag_new])
    db.flush()

    add_tag_to_item(db, admin, item1.id, "ML")
    add_tag_to_item(db, admin, item2.id, "ML")
    add_tag_to_item(db, admin, item2.id, "Machine Learning")
    db.commit()

    merged_tag = merge_tags(db, admin, source_tag_id=tag_old.id, target_tag_id=tag_new.id)
    db.commit()

    assert merged_tag.id == tag_new.id
    assert db.get(Tag, tag_old.id) is None
    # Verify item1 now has Machine Learning
    item1_tag_ids = list(
        db.scalars(select(ItemTag.tag_id).where(ItemTag.item_id == item1.id)).all()
    )
    assert tag_new.id in item1_tag_ids
