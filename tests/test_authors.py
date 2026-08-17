from __future__ import annotations

from unittest.mock import Mock

from quirebase.library.authors import (
    find_or_create_author,
    get_item_authors,
    parse_author_name,
    search_authors_typeahead,
    set_item_authors,
    set_item_authors_from_string,
)
from quirebase.library.items import ItemMetadataUpdate, create_item, update_item
from quirebase.models import Item, User


def test_parse_author_name():
    assert parse_author_name("Smith, Alice") == ("Smith", "Alice")
    assert parse_author_name("Alice Smith") == ("Smith", "Alice")
    assert parse_author_name("Einstein") == ("Einstein", None)
    assert parse_author_name("  Turing,  Alan M. ") == ("Turing", "Alan M.")


def test_set_and_get_item_authors(db):
    user = User(username="author_test_user", password_hash="hash")
    db.add(user)
    db.flush()

    item = Item(title="Information Theory", created_by=user.id)
    db.add(item)
    db.flush()

    authors_data = [
        {"last_name": "Shannon", "first_name": "Claude", "is_corresponding": True},
        {"last_name": "Weaver", "first_name": "Warren", "is_corresponding": False},
    ]
    set_item_authors(db, user, item.id, authors_data, role="author")
    db.commit()

    links = get_item_authors(db, item.id, role="author")
    assert len(links) == 2
    assert links[0].author.last_name == "Shannon"
    assert links[0].position == 1
    assert links[0].is_corresponding
    assert links[1].author.last_name == "Weaver"
    assert links[1].position == 2
    assert not links[1].is_corresponding

    # Check cache string on Item
    loaded_item = db.get(Item, item.id)
    assert loaded_item.authors == "Shannon, Claude; Weaver, Warren"


def test_set_item_authors_from_string(db):
    user = User(username="string_author_user", password_hash="hash")
    db.add(user)
    db.flush()
    item = Item(title="Computing Machinery", authors="Turing, Alan", created_by=user.id)
    db.add(item)
    db.flush()

    set_item_authors_from_string(db, user, item)

    assert item.authors == "Turing, Alan"
    assert [link.author.last_name for link in get_item_authors(db, item.id)] == ["Turing"]


def test_update_item_skips_unchanged_author_string(db, monkeypatch):
    user = User(username="unchanged_author_user", password_hash="hash")
    db.add(user)
    db.flush()
    item = create_item(db, user, title="Computing Machinery", authors="Turing, Alan")
    sync_authors = Mock()
    monkeypatch.setattr("quirebase.library.items.set_item_authors_from_string", sync_authors)

    update_item(db, user, item_id=item.id, data=ItemMetadataUpdate.from_item(item))

    sync_authors.assert_not_called()


def test_search_authors_typeahead(db):
    find_or_create_author(db, last_name="Shannon", first_name="Claude")
    find_or_create_author(db, last_name="Shaw", first_name="George")
    find_or_create_author(db, last_name="Turing", first_name="Alan")
    db.commit()

    results = search_authors_typeahead(db, "Sha")
    assert len(results) == 2
    assert any(r["last_name"] == "Shannon" for r in results)
    assert any(r["last_name"] == "Shaw" for r in results)
