import pytest

from quirebase.models import FileRevision, Item, User
from quirebase.search import reindex_all, search_index


async def add_item(db, user, *, title, abstract=None, full_text=None):
    item = Item(title=title, abstract=abstract, created_by=user.id)
    db.add(item)
    await db.flush()
    if full_text:
        db.add(
            FileRevision(
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
    metadata = await add_item(db, user, title="Graph neural networks", abstract="Molecules")
    extracted = await add_item(db, user, title="Untitled paper", full_text="Quasiparticle dynamics")
    await add_item(db, user, title="Unrelated")

    assert await reindex_all(db) == 3
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
