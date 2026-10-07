"""Characterize pinned dependency behavior, independently of application safety."""

from __future__ import annotations

import pytest
from advanced_alchemy.exceptions import NotFoundError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.types import FileObject
from sqlalchemy import select
from workspace_helpers import provision_initial_workspace

from quirebase.models import Item, User

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


class ProbeItemRepository(SQLAlchemyAsyncRepository[Item]):
    model_type = Item


@pytest.mark.parametrize("operation", ["update_many", "delete_many"])
async def test_repository_select_scope_does_not_constrain_generic_bulk_dml(
    persistence_sessions, operation
):
    async with persistence_sessions() as db:
        actor = User(username="scope-probe", password_hash="unused")
        other = User(username="scope-probe-other", password_hash="unused")
        db.add_all([actor, other])
        await db.flush()
        workspace = await provision_initial_workspace(db, actor)
        foreign_workspace = await provision_initial_workspace(db, other)
        foreign = Item(workspace_id=foreign_workspace.id, created_by=other.id, title="Original")
        db.add(foreign)
        await db.commit()
        foreign_id, workspace_id = foreign.id, workspace.id
        repository = ProbeItemRepository(
            session=db,
            statement=select(Item).where(Item.workspace_id == workspace_id),
            auto_commit=False,
            auto_refresh=False,
            auto_expunge=False,
            wrap_exceptions=False,
        )

        with pytest.raises(NotFoundError):
            await repository.get(foreign_id)
        if operation == "update_many":
            await repository.update_many([{"id": foreign_id, "title": "Outside SELECT scope"}])
            assert await db.scalar(select(Item.title).where(Item.id == foreign_id)) == (
                "Outside SELECT scope"
            )
        else:
            await repository.delete_many([foreign_id])
            assert await db.scalar(select(Item.id).where(Item.id == foreign_id)) is None

        await db.rollback()
        async with persistence_sessions() as observer:
            restored = await observer.get(Item, foreign_id)
            assert restored is not None and restored.title == "Original"


def test_file_object_equality_omits_persisted_descriptor_metadata(
    persistence_sessions, anyio_backend
):
    original = FileObject(
        backend="documents",
        filename="aa/bb/descriptor.pdf",
        size=10,
        metadata={"original_name": "original.pdf"},
    )
    changed = FileObject(
        backend="documents",
        filename="aa/bb/descriptor.pdf",
        size=10,
        metadata={"original_name": "renamed.pdf"},
    )
    assert original == changed
    assert original.to_dict() != changed.to_dict()
