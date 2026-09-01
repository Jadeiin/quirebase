from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from inquiro import (
    CandidateNotFound,
    CandidateRecord,
    Identifier,
    InvalidProviderRequest,
    ProviderUnavailable,
)
from sqlalchemy import select

from quirebase.core.errors import ResourceNotFound, ValidationFailure, VersionConflict
from quirebase.library import UpstreamServiceError
from quirebase.library.identifiers import (
    generate_bibtex_key,
    get_item_identifiers,
    rescan_pdf_doi,
    set_item_identifiers,
    sync_metadata_from_upstream,
)
from quirebase.models import AuditEvent, FileRevision, Item, User


async def _return_async(value):
    await asyncio.sleep(0)
    return value


async def _raise_async(error: Exception):
    await asyncio.sleep(0)
    raise error


def candidate(identifier: Identifier, values: dict) -> CandidateRecord:
    raw_identifiers = values.get("identifiers") or {}
    if isinstance(raw_identifiers, str):
        raw_identifiers = json.loads(raw_identifiers)
    identifiers = tuple(
        Identifier(str(provider), str(value)) for provider, value in raw_identifiers.items()
    )
    fields = {
        name: values.get(name)
        for name in (
            "abstract",
            "authors",
            "keywords",
            "publication_date",
            "publication_title",
            "journal_abbreviation",
            "volume",
            "issue",
            "pages",
            "publisher",
            "affiliation",
            "doi",
            "urls",
            "reference_type",
        )
    }
    return CandidateRecord(
        provider=identifier.provider,
        identifier=identifier,
        title=values["title"],
        identifiers=identifiers,
        **fields,
    )


@pytest.mark.anyio
async def test_set_and_get_item_identifiers(async_db):
    db = async_db
    user = User(username="ident_test_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Information Theory", created_by=user.id)
    db.add(item)
    await db.flush()

    id_pairs = [
        ("doi", "10.1002/j.1538-7305.1948.tb01338.x"),
        ("arxiv", "2401.00001"),
        ("pmid", "12345678"),
    ]
    await set_item_identifiers(db, user, item.id, id_pairs)
    await db.commit()

    loaded_ids = await get_item_identifiers(db, item.id)
    assert len(loaded_ids) == 2
    providers = {link.provider: link.value for link in loaded_ids}
    assert providers["arxiv"] == "2401.00001"

    # Check cache on Item
    loaded_item = await db.get(Item, item.id)
    assert loaded_item is not None
    assert loaded_item.doi == "10.1002/j.1538-7305.1948.tb01338.x"
    idents_dict = json.loads(loaded_item.identifiers)
    assert "doi" not in idents_dict
    assert idents_dict["arxiv"] == "2401.00001"


@pytest.mark.anyio
async def test_generate_bibtex_key(async_db):
    db = async_db
    user = User(username="key_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(
        title="A Mathematical Theory of Communication",
        authors="Shannon, Claude; Weaver, Warren",
        publication_date="1948-07-01",
        created_by=user.id,
    )
    db.add(item)
    await db.flush()

    key = generate_bibtex_key(item)
    assert key.startswith("Shannon1948Mathematical")


@pytest.mark.anyio
async def test_generate_bibtex_key_parses_first_last_author_name(async_db):
    db = async_db
    user = User(username="first_last_key_user", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(
        title="Computing Machinery and Intelligence",
        authors="Alan Turing",
        publication_date="1950",
        created_by=user.id,
    )

    assert generate_bibtex_key(item).startswith("Turing1950Computing")


@pytest.mark.anyio
async def test_rescan_pdf_doi(async_db):
    db = async_db
    user = User(username="pdf_doi_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Scanned Paper", created_by=user.id)
    db.add(item)
    await db.flush()

    revision = FileRevision(
        item_id=item.id,
        object_key="rev-1",
        size=1024,
        original_name="paper.pdf",
        full_text="Published in Nature. doi: 10.1038/s41586-020-2649-2. All rights reserved.",
        created_by=user.id,
    )
    db.add(revision)
    await db.flush()

    initial_version = item.version
    with patch("quirebase.library.identifiers.search_index") as search_index_factory:
        search_index_factory.return_value.index_item = AsyncMock()
        found_doi = await rescan_pdf_doi(db, user, item.id)
    assert found_doi == "10.1038/s41586-020-2649-2"

    loaded_item = await db.get(Item, item.id)
    assert loaded_item is not None
    assert loaded_item.doi == "10.1038/s41586-020-2649-2"
    assert loaded_item.version == initial_version + 1
    assert loaded_item.updated_by == user.id
    search_index_factory.return_value.index_item.assert_awaited_once_with(db, item.id)


@pytest.mark.anyio
async def test_sync_metadata_from_upstream(async_db):
    db = async_db
    user = User(username="sync_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Initial Title", created_by=user.id)
    db.add(item)
    await db.commit()

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

    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        return_value=candidate(
            Identifier("doi", "10.1002/j.1538-7305.1948.tb01338.x"), mock_record
        ),
    ):
        updated_item = await sync_metadata_from_upstream(
            db,
            user,
            item.id,
            item.version,
            provider="doi",
            uid_value="10.1002/j.1538-7305.1948.tb01338.x",
        )
        await db.commit()

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


@pytest.mark.parametrize(
    ("package_error", "domain_error"),
    [
        (InvalidProviderRequest("identifier is malformed"), ValidationFailure),
        (CandidateNotFound("metadata not found"), ResourceNotFound),
        (ProviderUnavailable("provider unavailable"), UpstreamServiceError),
    ],
)
@pytest.mark.anyio
async def test_sync_metadata_translates_inquiro_errors_at_library_interface(
    async_db, package_error, domain_error
):
    db = async_db
    user = User(username=f"sync-error-{domain_error.__name__}", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Original title", created_by=user.id)
    db.add(item)
    await db.commit()
    item_id = item.id
    item_version = item.version

    failing_runtime = type(
        "FailingRuntime",
        (),
        {
            "__aenter__": lambda self: _return_async(self),
            "__aexit__": lambda self, *_args: _return_async(None),
            "lookup": lambda self, *_args, **_kwargs: _raise_async(package_error),
        },
    )()
    with (
        patch("quirebase.library.providers.provider_runtime", return_value=failing_runtime),
        pytest.raises(domain_error, match=str(package_error)),
    ):
        await sync_metadata_from_upstream(
            db,
            user,
            item_id,
            item_version,
            provider="doi",
            uid_value="invalid",
        )

    saved = await db.get(Item, item_id, populate_existing=True)
    assert saved is not None
    assert saved.title == "Original title"
    assert saved.version == 1


@pytest.mark.anyio
async def test_sync_by_doi_does_not_store_doi_as_provider_identifier(async_db):
    db = async_db
    user = User(username="canonical_doi_sync", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Initial", created_by=user.id)
    db.add(item)
    await db.commit()

    record = {"title": "Updated", "doi": "10.1000/canonical"}
    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        return_value=candidate(Identifier("openalex", "10.1000/canonical"), record),
    ):
        await sync_metadata_from_upstream(
            db,
            user,
            item.id,
            item.version,
            provider="openalex",
            uid_value="https://doi.org/10.1000/canonical",
        )

    assert item.doi == "10.1000/canonical"
    assert await get_item_identifiers(db, item.id) == []


@pytest.mark.anyio
async def test_non_doi_sync_preserves_existing_canonical_doi_when_upstream_omits_it(async_db):
    db = async_db
    user = User(username="preserve_canonical_doi", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Initial", doi="10.1000/existing", created_by=user.id)
    db.add(item)
    await db.commit()

    record = {"title": "Updated", "identifiers": {"pmid": "12345678"}}
    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        return_value=candidate(Identifier("openalex", "W123"), record),
    ):
        await sync_metadata_from_upstream(
            db,
            user,
            item.id,
            item.version,
            provider="openalex",
            uid_value="W123",
        )

    assert item.doi == "10.1000/existing"
    assert {
        record.provider: record.value for record in await get_item_identifiers(db, item.id)
    } == {
        "openalex": "W123",
        "pmid": "12345678",
    }


@pytest.mark.anyio
async def test_sync_metadata_cleans_html_and_syncs_bibtex_type(async_db):
    db = async_db
    user = User(username="clean_html_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Draft Title", created_by=user.id)
    db.add(item)
    await db.commit()

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

    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        return_value=candidate(Identifier("doi", "10.1038/s41586-019-1666-5"), mock_record),
    ):
        updated = await sync_metadata_from_upstream(
            db,
            user,
            item.id,
            item.version,
            provider="doi",
            uid_value="10.1038/s41586-019-1666-5",
        )
        await db.commit()

    assert (
        updated.title
        == "<i>Quantum</i> Supremacy using a <b>Programmable</b> Superconducting Processor"
    )
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

    event = await db.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "item.sync_upstream")
        .order_by(AuditEvent.created_at.desc())
    )
    assert event is not None
    detail = json.loads(event.detail)
    assert detail["provider"] == "doi"
    assert detail["new_bibtex_key"].startswith("Arute2019")
    assert detail["bibtex_key_updated"] is True


@pytest.mark.anyio
async def test_sync_metadata_from_upstream_rejects_a_stale_version(async_db, async_session_factory):
    db = async_db
    owner = User(username="concurrent_sync_owner", password_hash="hash")
    db.add(owner)
    await db.flush()
    item = Item(title="Original title", created_by=owner.id)
    db.add(item)
    await db.commit()
    owner_id = owner.id
    item_id = item.id

    record = {"title": "Upstream title"}
    async with (
        async_session_factory() as first,
        async_session_factory() as second,
    ):
        with patch(
            "quirebase.library.identifiers.lookup_candidate",
            return_value=candidate(Identifier("doi", "10.1000/current"), record),
        ):
            first_owner = await first.get(User, owner_id)
            second_owner = await second.get(User, owner_id)
            first_item = await first.get(Item, item_id)
            second_item = await second.get(Item, item_id)
            assert first_owner and second_owner and first_item and second_item

            await sync_metadata_from_upstream(
                first,
                first_owner,
                item_id,
                first_item.version,
                provider="doi",
                uid_value="10.1000/current",
            )
            with pytest.raises(VersionConflict):
                await sync_metadata_from_upstream(
                    second,
                    second_owner,
                    item_id,
                    second_item.version,
                    provider="doi",
                    uid_value="10.1000/stale",
                )

    saved = await db.get(Item, item_id, populate_existing=True)
    assert saved is not None
    assert saved.title == "Upstream title"
    assert saved.version == 2


@pytest.mark.anyio
async def test_sync_metadata_uses_normalized_upstream_identifier(async_db):
    db = async_db
    user = User(username="normalized_upstream_sync", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Initial", doi="10.1000/canonical", created_by=user.id)
    db.add(item)
    await db.commit()

    record = {"title": "Updated"}
    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        return_value=candidate(Identifier("openalex", "W123"), record),
    ):
        await sync_metadata_from_upstream(
            db,
            user,
            item.id,
            item.version,
            provider="openalex",
            uid_value="https://openalex.org/W123",
        )

    assert item.doi == "10.1000/canonical"
    assert [
        (identifier.provider, identifier.value)
        for identifier in await get_item_identifiers(db, item.id)
    ] == [("openalex", "W123")]
