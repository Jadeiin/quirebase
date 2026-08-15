from quirebase.models import FileRevision, Item, User
from quirebase.operations import reindex_all, search_index


def add_item(db, user, *, title, abstract=None, full_text=None):
    item = Item(title=title, abstract=abstract, created_by=user.id)
    db.add(item)
    db.flush()
    if full_text:
        db.add(
            FileRevision(
                item_id=item.id,
                object_key=f"objects/{item.id}",
                sha256=item.id.replace("-", "").ljust(64, "0")[:64],
                size=1,
                original_name="paper.pdf",
                full_text=full_text,
                processing_state="ready",
                created_by=user.id,
            )
        )
        db.flush()
    return item


def test_sqlite_search_indexes_metadata_and_pdf_text(db):
    user = User(username="searcher", password_hash="unused")
    db.add(user)
    db.flush()
    metadata = add_item(db, user, title="Graph neural networks", abstract="Molecules")
    extracted = add_item(db, user, title="Untitled paper", full_text="Quasiparticle dynamics")
    add_item(db, user, title="Unrelated")

    assert reindex_all(db) == 3
    index = search_index(db)

    assert index.search(db, "neural") == [metadata.id]
    assert index.search(db, "quasiparticle") == [extracted.id]
    assert index.search(db, '" OR *') == []


def test_reindex_replaces_stale_content(db):
    user = User(username="editor", password_hash="unused")
    db.add(user)
    db.flush()
    item = add_item(db, user, title="Old terminology")
    index = search_index(db)
    index.index_item(db, item.id)
    item.title = "New vocabulary"
    index.index_item(db, item.id)

    assert index.search(db, "old") == []
    assert index.search(db, "vocabulary") == [item.id]
