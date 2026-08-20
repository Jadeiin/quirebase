from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from quirebase.core.errors import VersionConflict
from quirebase.library.identifiers import (
    generate_bibtex_key,
    get_item_identifiers,
    rescan_pdf_doi,
    set_item_identifiers,
    sync_metadata_from_upstream,
)
from quirebase.models import AuditEvent, FileRevision, Item, User


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
    assert len(loaded_ids) == 2
    providers = {link.provider: link.value for link in loaded_ids}
    assert providers["arxiv"] == "2401.00001"

    # Check cache on Item
    loaded_item = db.get(Item, item.id)
    assert loaded_item.doi == "10.1002/j.1538-7305.1948.tb01338.x"
    idents_dict = json.loads(loaded_item.identifiers)
    assert "doi" not in idents_dict
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

    initial_version = item.version
    with patch("quirebase.library.identifiers.search_index") as search_index_factory:
        found_doi = rescan_pdf_doi(db, user, item.id)
    assert found_doi == "10.1038/s41586-020-2649-2"

    loaded_item = db.get(Item, item.id)
    assert loaded_item.doi == "10.1038/s41586-020-2649-2"
    assert loaded_item.version == initial_version + 1
    assert loaded_item.updated_by == user.id
    search_index_factory.return_value.index_item.assert_called_once_with(db, item.id)


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
            db,
            user,
            item.id,
            item.version,
            provider="doi",
            uid_value="10.1002/j.1538-7305.1948.tb01338.x",
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


def test_sync_by_doi_does_not_store_doi_as_provider_identifier(db):
    user = User(username="canonical_doi_sync", password_hash="hash")
    db.add(user)
    db.flush()
    item = Item(title="Initial", created_by=user.id)
    db.add(item)
    db.commit()

    record = {"title": "Updated", "doi": "10.1000/canonical"}
    with patch("quirebase.library.identifiers.lookup_metadata", return_value=(None, record)):
        sync_metadata_from_upstream(
            db,
            user,
            item.id,
            item.version,
            provider="openalex",
            uid_value="https://doi.org/10.1000/canonical",
        )

    assert item.doi == "10.1000/canonical"
    assert get_item_identifiers(db, item.id) == []


def test_non_doi_sync_preserves_existing_canonical_doi_when_upstream_omits_it(db):
    user = User(username="preserve_canonical_doi", password_hash="hash")
    db.add(user)
    db.flush()
    item = Item(title="Initial", doi="10.1000/existing", created_by=user.id)
    db.add(item)
    db.commit()

    record = {"title": "Updated", "identifiers": {"pmid": "12345678"}}
    with patch("quirebase.library.identifiers.lookup_metadata", return_value=(None, record)):
        sync_metadata_from_upstream(
            db,
            user,
            item.id,
            item.version,
            provider="openalex",
            uid_value="W123",
        )

    assert item.doi == "10.1000/existing"
    assert {record.provider: record.value for record in get_item_identifiers(db, item.id)} == {
        "openalex": "W123",
        "pmid": "12345678",
    }


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
            db,
            user,
            item.id,
            item.version,
            provider="doi",
            uid_value="10.1038/s41586-019-1666-5",
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

    event = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "item.sync_upstream")
        .order_by(AuditEvent.created_at.desc())
    )
    assert event is not None
    detail = json.loads(event.detail)
    assert detail["provider"] == "doi"
    assert detail["new_bibtex_key"].startswith("Arute2019")
    assert detail["bibtex_key_updated"] is True


def test_sync_metadata_from_upstream_rejects_a_stale_version(db):
    owner = User(username="concurrent_sync_owner", password_hash="hash")
    db.add(owner)
    db.flush()
    item = Item(title="Original title", created_by=owner.id)
    db.add(item)
    db.commit()

    record = {"title": "Upstream title"}
    with (
        Session(db.bind, expire_on_commit=False) as first,
        Session(db.bind, expire_on_commit=False) as second,
        patch("quirebase.library.identifiers.lookup_metadata", return_value=(None, record)),
    ):
        first_owner = first.get(User, owner.id)
        second_owner = second.get(User, owner.id)
        first_item = first.get(Item, item.id)
        second_item = second.get(Item, item.id)
        assert first_owner and second_owner and first_item and second_item

        sync_metadata_from_upstream(
            first,
            first_owner,
            item.id,
            first_item.version,
            provider="doi",
            uid_value="10.1000/current",
        )
        with pytest.raises(VersionConflict):
            sync_metadata_from_upstream(
                second,
                second_owner,
                item.id,
                second_item.version,
                provider="doi",
                uid_value="10.1000/stale",
            )

    db.expire_all()
    saved = db.get(Item, item.id)
    assert saved.title == "Upstream title"
    assert saved.version == 2
