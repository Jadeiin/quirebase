import pytest
from sqlalchemy import select

from quirebase.models import FileRevision, Item, ItemFileRevision, User
from quirebase.search import reindex_all, search_index


async def add_item(db, user, *, title, abstract=None, full_text=None):
    item = Item(title=title, abstract=abstract, owner_id=user.id, created_by=user.id)
    db.add(item)
    await db.flush()
    if full_text:
        revision = FileRevision(
            object_key=f"objects/{item.id}",
            size=1,
            original_name="paper.pdf",
            full_text=full_text,
            processing_state="ready",
            created_by=user.id,
        )
        db.add(revision)
        await db.flush()
        db.add(ItemFileRevision(item_id=item.id, file_revision_id=revision.id))
    return item


@pytest.mark.anyio
async def test_sqlite_search_indexes_metadata_and_pdf_text(async_db):
    db = async_db
    user = User(username="searcher", password_hash="unused")
    db.add(user)
    await db.flush()
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
    item = await add_item(
        async_db, user, title="Original title", full_text="Distinctive PDF phrase"
    )
    index = search_index(async_db)
    revision = await async_db.scalar(
        select(FileRevision)
        .join(ItemFileRevision, ItemFileRevision.file_revision_id == FileRevision.id)
        .where(ItemFileRevision.item_id == item.id)
    )
    await index.index_revision(async_db, revision.id)
    item.title = "Updated title"
    await index.index_item(async_db, item.id)

    assert await index.search(async_db, "phrase") == [item.id]
