from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import PermissionDenied, ResourceUnavailable
from quirebase.library.tags import (
    TagConflict,
    add_tag_to_item,
    apply_item_tag_selection,
    get_or_create_tag,
    get_tag_matrix_for_item,
    merge_tags,
    remove_tag_from_item,
    rename_tag,
)
from quirebase.models import (
    AuditEvent,
    Item,
    ItemTag,
    ItemTagRecommendation,
    Tag,
    User,
    WorkspaceMember,
    WorkspaceRole,
)


async def _user(db, username: str) -> User:
    user = User(username=username, password_hash="hash")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


@pytest.mark.anyio
async def test_tag_mutations_are_workspace_scoped_and_audited(async_db):
    user = await _user(async_db, "tag-remover")
    workspace_id = fixture_workspace_id(user)
    assert workspace_id is not None
    item = Item(workspace_id=workspace_id, title="Tagged Item", created_by=user.id)
    async_db.add(item)
    await async_db.flush()

    assignment = await add_tag_to_item(async_db, user, workspace_id, item.id, "Temporary")
    await remove_tag_from_item(async_db, user, workspace_id, item.id, assignment.tag_id)

    assert (
        await async_db.scalar(
            select(ItemTag).where(
                ItemTag.workspace_id == workspace_id,
                ItemTag.item_id == item.id,
                ItemTag.tag_id == assignment.tag_id,
            )
        )
        is None
    )
    event = await async_db.scalar(
        select(AuditEvent).where(AuditEvent.action == "tag.remove", AuditEvent.target_id == item.id)
    )
    assert event is not None
    assert event.workspace_id == workspace_id
    assert json.loads(event.detail or "{}") == {"tag_id": assignment.tag_id}


@pytest.mark.anyio
async def test_tag_selection_is_atomic(async_db):
    user = await _user(async_db, "tag-selection-atomic")
    workspace_id = fixture_workspace_id(user)
    assert workspace_id is not None
    item = Item(workspace_id=workspace_id, title="Atomic Tag Selection", created_by=user.id)
    async_db.add(item)
    await async_db.flush()
    assignment = await add_tag_to_item(async_db, user, workspace_id, item.id, "Keep Me")
    item_id = item.id
    tag_id = assignment.tag_id

    with pytest.raises(ResourceUnavailable, match="tag not found"):
        await apply_item_tag_selection(
            async_db,
            user,
            workspace_id,
            item_id,
            remove_tag_ids=[tag_id],
            tag_ids=["missing-tag"],
        )
    assert (
        await async_db.scalar(
            select(ItemTag).where(
                ItemTag.workspace_id == workspace_id,
                ItemTag.item_id == item_id,
                ItemTag.tag_id == tag_id,
            )
        )
        is not None
    )


@pytest.mark.anyio
async def test_tag_matrix_and_normalized_names_are_workspace_scoped(async_db):
    user = await _user(async_db, "tag-matrix-user")
    foreign = await _user(async_db, "tag-matrix-foreign")
    workspace_id = fixture_workspace_id(user)
    foreign_workspace_id = fixture_workspace_id(foreign)
    assert workspace_id is not None and foreign_workspace_id is not None
    tags = [
        Tag(workspace_id=workspace_id, name=name, created_by=user.id)
        for name in ("Algorithms", "Bioinformatics", "Compiler")
    ]
    tags.append(Tag(workspace_id=foreign_workspace_id, name="Foreign", created_by=foreign.id))
    item = Item(
        workspace_id=workspace_id,
        title="Compiler Optimization Algorithms",
        abstract="Efficient algorithms for compiler backend.",
        keywords="Compiler; New Optimizer",
        created_by=user.id,
    )
    async_db.add_all([*tags, item])
    await async_db.flush()
    async_db.add(
        ItemTagRecommendation(
            workspace_id=workspace_id,
            item_id=item.id,
            generation_token=1,
            single_words=json.dumps(["Algorithms", "Compiler"]),
            phrases=json.dumps(["New Optimizer"]),
            generated_at=datetime.now(UTC),
        )
    )
    await add_tag_to_item(async_db, user, workspace_id, item.id, "Algorithms")
    matrix = await get_tag_matrix_for_item(async_db, user, workspace_id, item.id)
    names = {tag.name for group in matrix["groups"] for tag in group["tags"]}
    assert names == {"Algorithms", "Bioinformatics", "Compiler"}
    assert tags[0].id in matrix["assigned_ids"]
    assert tags[2].id in matrix["recommended_ids"]


@pytest.mark.anyio
async def test_tag_normalized_key_allows_full_casefold_expansion(async_db):
    user = await _user(async_db, "tag-casefold-expansion")
    workspace_id = fixture_workspace_id(user)

    tag = await get_or_create_tag(async_db, user, workspace_id, "ß" * 120)
    assert tag.normalized_name == "ss" * 120
    assert Tag.__table__.c.normalized_name.type.length == 360

    renamed = await rename_tag(async_db, user, workspace_id, tag.id, "ﬃ" * 120)
    assert renamed.normalized_name == "ffi" * 120


@pytest.mark.anyio
async def test_tag_merge_requires_workspace_capability_not_creator_ownership(async_db):
    owner = await _user(async_db, "tag-owner")
    editor = await _user(async_db, "tag-editor")
    workspace_id = fixture_workspace_id(owner)
    assert workspace_id is not None
    async_db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=editor.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        )
    )
    source = Tag(workspace_id=workspace_id, name="ML", created_by=owner.id)
    target = Tag(workspace_id=workspace_id, name="Machine Learning", created_by=editor.id)
    async_db.add_all([source, target])
    await async_db.commit()

    with pytest.raises(PermissionDenied, match=r"tags\.manage"):
        await merge_tags(async_db, editor, workspace_id, source.id, target.id)
    merged = await merge_tags(async_db, owner, workspace_id, source.id, target.id)
    assert merged.id == target.id
    with pytest.raises(TagConflict, match="different"):
        await merge_tags(async_db, owner, workspace_id, target.id, target.id)
