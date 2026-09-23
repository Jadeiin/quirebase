import pytest
from sqlalchemy import select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.models import FileRevision, Item, User
from quirebase.search import reindex_all, search_index


async def add_item(db, user, *, title, abstract=None, full_text=None):
    if fixture_workspace_id(user) is None:
        await provision_initial_workspace(db, user)
        await db.flush()
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title=title,
        abstract=abstract,
        created_by=user.id,
    )
    db.add(item)
    await db.flush()
    if full_text:
        db.add(
            FileRevision(
                workspace_id=fixture_workspace_id(user),
                item_id=item.id,
                object_key=f"objects/{item.id}",
                size=1,
                original_name="paper.pdf",
                full_text=full_text,
                processing_state="ready",
                created_by=user.id,
            )
        )
        await db.flush()
    return item


@pytest.mark.anyio
async def test_sqlite_search_indexes_metadata_and_pdf_text(async_db):
    db = async_db
    user = User(username="searcher", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    metadata = await add_item(db, user, title="Graph neural networks", abstract="Molecules")
    extracted = await add_item(db, user, title="Untitled paper", full_text="Quasiparticle dynamics")
    await add_item(db, user, title="Unrelated")

    assert await reindex_all(db) == 4
    index = search_index(db)

    assert await index.search(db, "neural") == [metadata.id]
    assert await index.search(db, "quasiparticle") == [extracted.id]
    assert await index.search(db, '" OR *') == []


@pytest.mark.anyio
async def test_reindex_replaces_stale_content(async_db):
    db = async_db
    user = User(username="editor", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    item = await add_item(db, user, title="Old terminology")
    index = search_index(db)
    await index.index_item(db, item.id)
    item.title = "New vocabulary"
    await index.index_item(db, item.id)

    assert await index.search(db, "old") == []
    assert await index.search(db, "vocabulary") == [item.id]


@pytest.mark.anyio
async def test_metadata_reindex_preserves_revision_projection(async_db):
    user = User(username="search-revision-editor", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    await provision_initial_workspace(async_db, user)
    item = await add_item(
        async_db, user, title="Original title", full_text="Distinctive PDF phrase"
    )
    index = search_index(async_db)
    revision = await async_db.scalar(select(FileRevision).where(FileRevision.item_id == item.id))
    await index.index_revision(async_db, revision.id)
    item.title = "Updated title"
    await index.index_item(async_db, item.id)

    assert await index.search(async_db, "phrase") == [item.id]
