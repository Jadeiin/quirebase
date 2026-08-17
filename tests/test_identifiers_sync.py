from __future__ import annotations

import json
from unittest.mock import patch

from quirebase.library.identifiers import (
    generate_bibtex_key,
    get_item_identifiers,
    rescan_pdf_doi,
    set_item_identifiers,
    sync_metadata_from_upstream,
)
from quirebase.models import FileRevision, Item, User


def test_set_and_get_item_identifiers(db):
    user = User(username="ident_test_user", password_hash="hash")
    db.add(user)
    db.flush()

    item = Item(title="Information Theory", created_by=user.id)
    db.add(item)
    db.flush()

    id_pairs = [
        ("doi", "10.1002/j.1538-7305.1948.tb01338.x"),
        ("arxiv", "2401.00001"),
        ("pmid", "12345678"),
    ]
    set_item_identifiers(db, user, item.id, id_pairs)
    db.commit()

    loaded_ids = get_item_identifiers(db, item.id)
    assert len(loaded_ids) == 3
    providers = {link.provider: link.value for link in loaded_ids}
    assert providers["doi"] == "10.1002/j.1538-7305.1948.tb01338.x"
    assert providers["arxiv"] == "2401.00001"

    # Check cache on Item
    loaded_item = db.get(Item, item.id)
    assert loaded_item.doi == "10.1002/j.1538-7305.1948.tb01338.x"
    idents_dict = json.loads(loaded_item.identifiers)
    assert idents_dict["doi"] == "10.1002/j.1538-7305.1948.tb01338.x"
    assert idents_dict["arxiv"] == "2401.00001"


def test_generate_bibtex_key(db):
    user = User(username="key_user", password_hash="hash")
    db.add(user)
    db.flush()

    item = Item(
        title="A Mathematical Theory of Communication",
        authors="Shannon, Claude; Weaver, Warren",
        publication_date="1948-07-01",
        created_by=user.id,
    )
    db.add(item)
    db.flush()

    key = generate_bibtex_key(item)
    assert key.startswith("Shannon1948Mathematical")


def test_generate_bibtex_key_parses_first_last_author_name(db):
    user = User(username="first_last_key_user", password_hash="hash")
    db.add(user)
    db.flush()
    item = Item(
        title="Computing Machinery and Intelligence",
        authors="Alan Turing",
        publication_date="1950",
        created_by=user.id,
    )

    assert generate_bibtex_key(item).startswith("Turing1950Computing")


def test_rescan_pdf_doi(db):
    user = User(username="pdf_doi_user", password_hash="hash")
    db.add(user)
    db.flush()

    item = Item(title="Scanned Paper", created_by=user.id)
    db.add(item)
    db.flush()

    revision = FileRevision(
        item_id=item.id,
        object_key="rev-1",
        sha256="abc",
        size=1024,
        original_name="paper.pdf",
        full_text="Published in Nature. doi: 10.1038/s41586-020-2649-2. All rights reserved.",
        created_by=user.id,
    )
    db.add(revision)
    db.flush()

    found_doi = rescan_pdf_doi(db, user, item.id)
    assert found_doi == "10.1038/s41586-020-2649-2"

    loaded_item = db.get(Item, item.id)
    assert loaded_item.doi == "10.1038/s41586-020-2649-2"


def test_sync_metadata_from_upstream(db):
    user = User(username="sync_user", password_hash="hash")
    db.add(user)
    db.flush()

    item = Item(title="Initial Title", created_by=user.id)
    db.add(item)
    db.flush()

    mock_record = {
        "title": "A Mathematical Theory of Communication",
        "abstract": "The fundamental problem of communication is...",
        "authors": "Shannon, Claude",
        "keywords": "Information Theory; Cryptography",
        "urls": "https://doi.org/10.1002/j.1538-7305.1948.tb01338.x\nhttps://bell-labs.com/shannon1948",
        "publication_date": "1948",
        "publication_title": "Bell System Technical Journal",
        "volume": "27",
        "issue": "3",
        "pages": "379-423",
        "publisher": "Alcatel-Lucent",
        "doi": "10.1002/j.1538-7305.1948.tb01338.x",
        "identifiers": json.dumps({"doi": "10.1002/j.1538-7305.1948.tb01338.x"}),
        "reference_type": "article",
    }

    with patch("quirebase.library.identifiers.lookup_metadata", return_value=(None, mock_record)):
        updated_item = sync_metadata_from_upstream(
            db, user, item.id, provider="doi", uid_value="10.1002/j.1538-7305.1948.tb01338.x"
        )
        db.commit()

    assert updated_item.title == "A Mathematical Theory of Communication"
    assert updated_item.volume == "27"
    assert updated_item.issue == "3"
    assert updated_item.pages == "379-423"
    assert updated_item.publisher == "Alcatel-Lucent"
    assert updated_item.bibtex_type == "article"
    assert updated_item.bibtex_id is not None
    assert "https://bell-labs.com/shannon1948" in updated_item.urls
    assert updated_item.updated_by == user.id
    assert len(updated_item.author_links) == 1
    assert updated_item.author_links[0].author.last_name == "Shannon"


def test_sync_metadata_cleans_html_and_syncs_bibtex_type(db):
    user = User(username="clean_html_user", password_hash="hash")
    db.add(user)
    db.flush()

    item = Item(title="Draft Title", created_by=user.id)
    db.add(item)
    db.flush()

    mock_record = {
        "title": "<i>Quantum</i> Supremacy using a <b>Programmable</b> Superconducting Processor",
        "abstract": "<p>The promise of quantum computers is that certain computational tasks might be executed exponentially faster...</p>",
        "authors": "Arute, Frank; Arya, Kunal",
        "keywords": "Quantum Computing; Superconducting",
        "publication_date": "2019-10-23",
        "publication_title": "<i>Nature</i>",
        "journal_abbreviation": "<i>Nat.</i>",
        "volume": "574",
        "issue": "7779",
        "pages": "505-510",
        "publisher": "<b>Nature Publishing Group</b>",
        "affiliation": "Google LLC, Santa Barbara, CA, USA",
        "doi": "10.1038/s41586-019-1666-5",
        "reference_type": "journal-article",
    }

    with patch("quirebase.library.identifiers.lookup_metadata", return_value=(None, mock_record)):
        updated = sync_metadata_from_upstream(
            db, user, item.id, provider="doi", uid_value="10.1038/s41586-019-1666-5"
        )
        db.commit()

    assert updated.title == "Quantum Supremacy using a Programmable Superconducting Processor"
    assert (
        updated.abstract
        == "The promise of quantum computers is that certain computational tasks might be executed exponentially faster..."
    )
    assert updated.publication_title == "Nature"
    assert updated.journal_abbreviation == "Nat."
    assert updated.publisher == "Nature Publishing Group"
    assert updated.reference_type == "article"
    assert updated.bibtex_type == "article"
    assert updated.bibtex_id.startswith("Arute2019")
