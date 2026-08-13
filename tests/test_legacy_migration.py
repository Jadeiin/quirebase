import sqlite3

from quirebase.legacy_migration import migrate_legacy
from quirebase.models import Item, ItemTag, Tag, User


def make_legacy_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE items(id integer primary key, title text, primary_title_id integer,
              publication_date text, abstract text, reference_type text);
            CREATE TABLE primary_titles(id integer primary key, primary_title text);
            CREATE TABLE authors(id integer primary key, first_name text, last_name text);
            CREATE TABLE items_authors(item_id integer, author_id integer, position integer);
            CREATE TABLE keywords(id integer primary key, keyword text);
            CREATE TABLE items_keywords(item_id integer, keyword_id integer);
            CREATE TABLE uids(id integer primary key, uid_type text, uid text, item_id integer);
            CREATE TABLE tags(id integer primary key, tag text);
            CREATE TABLE items_tags(item_id integer, tag_id integer);
            INSERT INTO primary_titles VALUES (1, 'Journal');
            INSERT INTO items VALUES (7, 'Legacy paper', 1, '2020', 'Abstract', 'article');
            INSERT INTO authors VALUES (1, 'Ada', 'Example');
            INSERT INTO items_authors VALUES (7, 1, 1);
            INSERT INTO keywords VALUES (1, 'migration');
            INSERT INTO items_keywords VALUES (7, 1);
            INSERT INTO uids VALUES (1, 'doi', '10.1/legacy', 7);
            INSERT INTO tags VALUES (1, 'archive');
            INSERT INTO items_tags VALUES (7, 1);
            """
        )


def test_legacy_import_preflight_commit_and_idempotency(db, tmp_path):
    legacy = tmp_path / "main.sq3"
    make_legacy_database(legacy)
    data = tmp_path / "legacy-data"
    data.mkdir()
    owner = User(username="migration-owner", password_hash="unused")
    db.add(owner)
    db.commit()

    preview = migrate_legacy(db, legacy, data, owner, commit=False)
    assert preview["items"] == 1
    assert db.query(Item).count() == 0

    migrate_legacy(db, legacy, data, owner, commit=True)
    item = db.query(Item).one()
    assert item.title == "Legacy paper"
    assert item.authors == "Example, Ada"
    assert db.query(Tag).one().name == "archive"
    assert db.query(ItemTag).count() == 1

    migrate_legacy(db, legacy, data, owner, commit=True)
    assert db.query(Item).count() == 1
