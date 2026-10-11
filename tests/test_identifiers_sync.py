from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from advanced_alchemy.types import FileObject
from inquiro import (
    Affiliation,
    CandidateNotFound,
    CandidateRecord,
    Contributor,
    Identifier,
    InvalidProviderRequest,
    ProviderUnavailable,
    ResourceLink,
)
from item_helpers import contributor_values, stored_doi
from sqlalchemy import select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import ResourceNotFound, ValidationFailure, VersionConflict
from quirebase.library import UpstreamServiceError
from quirebase.library.identifiers import (
    apply_metadata_record,
    generate_citation_key,
    get_item_identifiers,
    rescan_pdf_doi,
    set_item_identifiers,
    sync_metadata_from_upstream,
)
from quirebase.models import AuditEvent, FileRevision, Item, ItemIdentifier, User


async def _user(db, username: str) -> User:
    user = User(username=username, password_hash="hash")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


async def _return_async(value):
    await asyncio.sleep(0)
    return value


async def _raise_async(error: Exception):
    await asyncio.sleep(0)
    raise error


async def _ignore_async(*_args):
    await asyncio.sleep(0)


def candidate(lookup_identifier: Identifier, values: dict) -> CandidateRecord:
    raw_identifiers = values.get("identifiers") or {}
    if isinstance(raw_identifiers, str):
        raw_identifiers = json.loads(raw_identifiers)
    if doi := values.get("doi"):
        raw_identifiers = {**raw_identifiers, "doi": doi}
    identifiers = tuple(
        Identifier(str(provider), str(value)) for provider, value in raw_identifiers.items()
    )
    fields = {
        name: values.get(name)
        for name in (
            "abstract",
            "publication_date",
            "publication_title",
            "journal_abbreviation",
            "volume",
            "issue",
            "pages",
            "publisher",
            "reference_type",
        )
    }
    if values.get("doi"):
        identifiers = (
            *(row for row in identifiers if row.provider != "doi"),
            Identifier("doi", values["doi"]),
        )
    return CandidateRecord(
        provider={"doi": "crossref", "pmid": "pubmed"}.get(
            lookup_identifier.provider, lookup_identifier.provider
        ),
        lookup_identifier=lookup_identifier,
        title=values["title"],
        identifiers=identifiers,
        authors=tuple(
            Contributor(
                name.strip(),
                affiliations=(Affiliation(values["affiliation"]),)
                if values.get("affiliation")
                else None,
            )
            for name in values["authors"].split(";")
        )
        if values.get("authors") is not None
        else None,
        keywords=tuple(name.strip() for name in values["keywords"].split(";"))
        if values.get("keywords") is not None
        else None,
        urls=tuple(ResourceLink(url) for url in values["urls"].splitlines())
        if values.get("urls") is not None
        else None,
        **fields,
    )


@pytest.mark.anyio
async def test_apply_metadata_record_projects_unknown_upstream_type_to_document(async_db):
    user = await _user(async_db, "reference-type-owner")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Reference type",
        created_by=user.id,
    )
    async_db.add(item)
    await async_db.flush()

    await apply_metadata_record(async_db, user, item, {"reference_type": "x" * 41})
    assert item.reference_type == "document"


@pytest.mark.anyio
async def test_set_and_get_item_identifiers(async_db):
    db = async_db
    user = await _user(db, "ident_test_user")

    item = Item(
        workspace_id=fixture_workspace_id(user), title="Information Theory", created_by=user.id
    )
    db.add(item)
    await db.flush()

    id_pairs = [
        ("doi", "10.1002/j.1538-7305.1948.tb01338.x"),
        ("arxiv", "2401.00001"),
        ("pmid", "12345678"),
    ]
    await set_item_identifiers(db, user, fixture_workspace_id(user), item.id, id_pairs)
    await db.commit()

    loaded_ids = await get_item_identifiers(db, item.id)
    assert len(loaded_ids) == 3
    providers = {link.provider: link.value for link in loaded_ids}
    assert providers["arxiv"] == "2401.00001"

    # DOI and other identifiers live only in the association table.
    loaded_item = await db.get(Item, item.id)
    assert loaded_item is not None
    assert (await stored_doi(db, loaded_item)) == "10.1002/j.1538-7305.1948.tb01338.x"
    idents_dict = {link.provider: link.value for link in await get_item_identifiers(db, item.id)}
    assert idents_dict["doi"] == "10.1002/j.1538-7305.1948.tb01338.x"
    assert idents_dict["arxiv"] == "2401.00001"


@pytest.mark.anyio
async def test_generate_citation_key(async_db):
    db = async_db
    user = await _user(db, "key_user")

    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="A Mathematical Theory of Communication",
        authors=contributor_values("Shannon, Claude; Weaver, Warren"),
        publication_date="1948-07-01",
        created_by=user.id,
    )
    db.add(item)
    await db.flush()

    key = generate_citation_key(item)
    assert key.startswith("Shannon1948Mathematical")


@pytest.mark.anyio
async def test_generate_citation_key_parses_first_last_author_name(async_db):
    db = async_db
    user = await _user(db, "first_last_key_user")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Computing Machinery and Intelligence",
        authors=contributor_values("Alan Turing"),
        publication_date="1950",
        created_by=user.id,
    )

    assert generate_citation_key(item).startswith("Turing1950Computing")


@pytest.mark.anyio
async def test_rescan_pdf_doi(async_db):
    db = async_db
    user = await _user(db, "pdf_doi_user")

    item = Item(workspace_id=fixture_workspace_id(user), title="Scanned Paper", created_by=user.id)
    db.add(item)
    await db.flush()

    revision = FileRevision(
        workspace_id=fixture_workspace_id(user),
        item_id=item.id,
        full_text="Published in Nature. doi: 10.1038/s41586-020-2649-2. All rights reserved.",
        created_by=user.id,
        file=FileObject(
            backend="documents",
            filename="rev-1",
            size=1024,
            content_type="application/pdf",
            metadata={"original_name": "paper.pdf"},
        ),
    )
    db.add(revision)
    await db.flush()

    initial_version = item.version
    with patch("quirebase.library.identifiers.search_index") as search_index_factory:
        search_index_factory.return_value.index_item = AsyncMock()
        found_doi = await rescan_pdf_doi(db, user, fixture_workspace_id(user), item.id)
    assert found_doi == "10.1038/s41586-020-2649-2"

    loaded_item = await db.get(Item, item.id)
    assert loaded_item is not None
    assert (await stored_doi(db, loaded_item)) == "10.1038/s41586-020-2649-2"
    assert loaded_item.version == initial_version + 1
    assert loaded_item.updated_by == user.id
    search_index_factory.return_value.index_item.assert_awaited_once_with(db, item.id)


@pytest.mark.anyio
async def test_rescan_pdf_doi_does_not_replace_manual_doi(async_db):
    db = async_db
    user = await _user(db, "pdf_doi_manual")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Manual DOI",
        identifier_links=[
            ItemIdentifier(
                workspace_id=fixture_workspace_id(user), provider="doi", value="10.1000/manual"
            )
        ],
        created_by=user.id,
    )
    db.add(item)
    await db.flush()
    db.add(
        FileRevision(
            workspace_id=fixture_workspace_id(user),
            item_id=item.id,
            full_text="doi: 10.1000/detected",
            created_by=user.id,
            file=FileObject(
                backend="documents",
                filename="manual-rev",
                size=1,
                content_type="application/pdf",
                metadata={"original_name": "manual.pdf"},
            ),
        )
    )
    await db.commit()
    initial_version = item.version

    found_doi = await rescan_pdf_doi(db, user, fixture_workspace_id(user), item.id)

    assert found_doi == "10.1000/manual"
    await db.refresh(item)
    assert (await stored_doi(db, item)) == "10.1000/manual"
    assert item.version == initial_version


@pytest.mark.anyio
async def test_sync_metadata_from_upstream(async_db):
    db = async_db
    user = await _user(db, "sync_user")

    item = Item(workspace_id=fixture_workspace_id(user), title="Initial Title", created_by=user.id)
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
            fixture_workspace_id(user),
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
    assert updated_item.citation_key is not None
    assert {"url": "https://bell-labs.com/shannon1948"} in updated_item.urls
    assert updated_item.updated_by == user.id
    assert len(updated_item.authors) == 1
    assert updated_item.authors[0]["display_name"] == "Shannon, Claude"
    assert updated_item.authors[0]["family_name"] is None


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
    user = await _user(db, f"sync-error-{domain_error.__name__}")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Original title",
        created_by=user.id,
    )
    db.add(item)
    await db.commit()
    item_id = item.id
    item_version = item.version

    failing_runtime = type(
        "FailingRuntime",
        (),
        {
            "__aenter__": _return_async,
            "__aexit__": _ignore_async,
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
            fixture_workspace_id(user),
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
async def test_sync_by_doi_stores_a_confirmed_doi_identifier(async_db):
    db = async_db
    user = await _user(db, "canonical_doi_sync")
    item = Item(workspace_id=fixture_workspace_id(user), title="Initial", created_by=user.id)
    db.add(item)
    await db.commit()

    record = {"title": "Updated", "doi": "10.1000/canonical"}
    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        return_value=candidate(Identifier("crossref", "10.1000/canonical"), record),
    ):
        await sync_metadata_from_upstream(
            db,
            user,
            fixture_workspace_id(user),
            item.id,
            item.version,
            provider="crossref",
            uid_value="https://doi.org/10.1000/canonical",
        )

    assert (await stored_doi(db, item)) == "10.1000/canonical"
    assert [(row.provider, row.value) for row in await get_item_identifiers(db, item.id)] == [
        ("doi", "10.1000/canonical")
    ]


@pytest.mark.anyio
async def test_non_doi_sync_preserves_existing_canonical_doi_when_upstream_omits_it(async_db):
    db = async_db
    user = await _user(db, "preserve_canonical_doi")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Initial",
        identifier_links=[
            ItemIdentifier(
                workspace_id=fixture_workspace_id(user), provider="doi", value="10.1000/existing"
            )
        ],
        created_by=user.id,
    )
    db.add(item)
    await db.commit()

    record = {"title": "Updated", "identifiers": {"openalex": "W123", "pmid": "12345678"}}
    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        return_value=candidate(Identifier("openalex", "W123"), record),
    ):
        await sync_metadata_from_upstream(
            db,
            user,
            fixture_workspace_id(user),
            item.id,
            item.version,
            provider="openalex",
            uid_value="W123",
        )

    assert (await stored_doi(db, item)) == "10.1000/existing"
    assert {
        record.provider: record.value for record in await get_item_identifiers(db, item.id)
    } == {
        "doi": "10.1000/existing",
        "openalex": "W123",
        "pmid": "12345678",
    }


@pytest.mark.anyio
async def test_sync_metadata_cleans_html_and_syncs_reference_type(async_db):
    db = async_db
    user = await _user(db, "clean_html_user")

    item = Item(workspace_id=fixture_workspace_id(user), title="Draft Title", created_by=user.id)
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
        "reference_type": "article-journal",
    }

    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        return_value=candidate(Identifier("doi", "10.1038/s41586-019-1666-5"), mock_record),
    ):
        updated = await sync_metadata_from_upstream(
            db,
            user,
            fixture_workspace_id(user),
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
    assert updated.reference_type == "article-journal"
    assert updated.citation_key.startswith("Arute2019")

    event = await db.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "item.sync_upstream")
        .order_by(AuditEvent.created_at.desc())
    )
    assert event is not None
    detail = event.detail
    assert detail["provider"] == "crossref"
    assert detail["lookup_provider"] == "doi"
    assert detail["new_citation_key"].startswith("Arute2019")
    assert detail["citation_key_updated"] is True


@pytest.mark.anyio
async def test_sync_metadata_from_upstream_rejects_a_stale_version(async_db, async_session_factory):
    db = async_db
    owner = await _user(db, "concurrent_sync_owner")
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        title="Original title",
        created_by=owner.id,
    )
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
                fixture_workspace_id(owner),
                item_id,
                first_item.version,
                provider="doi",
                uid_value="10.1000/current",
            )
            with pytest.raises(VersionConflict):
                await sync_metadata_from_upstream(
                    second,
                    second_owner,
                    fixture_workspace_id(owner),
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
async def test_sync_metadata_uses_returned_identity_instead_of_lookup_input(async_db):
    db = async_db
    user = await _user(db, "normalized_upstream_sync")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Initial",
        identifier_links=[
            ItemIdentifier(
                workspace_id=fixture_workspace_id(user), provider="doi", value="10.1000/canonical"
            )
        ],
        created_by=user.id,
    )
    db.add(item)
    await db.commit()

    record = {"title": "Updated", "identifiers": {"openalex": "W123"}}
    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        return_value=candidate(Identifier("openalex", "W122"), record),
    ):
        await sync_metadata_from_upstream(
            db,
            user,
            fixture_workspace_id(user),
            item.id,
            item.version,
            provider="openalex",
            uid_value="https://openalex.org/W122",
        )

    assert (await stored_doi(db, item)) == "10.1000/canonical"
    assert [
        (identifier.provider, identifier.value)
        for identifier in await get_item_identifiers(db, item.id)
    ] == [("doi", "10.1000/canonical"), ("openalex", "W123")]
