from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import VersionConflict, WorkspaceMembershipRequired, WorkspaceUnavailable
from quirebase.library import (
    copy_item_to_workspace,
    create_item,
    find_duplicates,
    get_library_facets,
    revise_item_metadata,
    search_library,
)
from quirebase.library._metadata import candidate_write
from quirebase.library.imports import commit_import_batch, stage_import_batch
from quirebase.models import ImportBatch, Item, User, Workspace, WorkspaceMember, WorkspaceRole

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


def work(title="Research", *, resource_id=None, **fields):
    return {"id": resource_id or f"urn:uuid:{uuid4()}", "type": "Dataset", "title": title, **fields}


async def owner(db):
    actor = User(username=f"owner-{uuid4()}", password_hash="hash")
    db.add(actor)
    await db.flush()
    await provision_initial_workspace(db, actor)
    await db.commit()
    return actor, fixture_workspace_id(actor)


async def test_duplicate_identifiers_coexist_and_suggest_connected_groups(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    a = work(
        "First",
        resource_id="https://doi.org/10.1234/ONE",
        identifiers=[{"identifier_type": "DOI", "identifier": "10.1234/two"}],
    )
    b = work(
        "Second",
        identifiers=[
            {"identifier_type": "DOI", "identifier": "doi:10.1234/one"},
            {"identifier_type": "PMID", "identifier": "42"},
        ],
    )
    c = work("Third", identifiers=[{"identifier_type": "PMID", "identifier": "42"}])
    results = [await create_item(db, actor, workspace_id, value) for value in (a, b, c)]
    groups = await find_duplicates(db, actor, workspace_id, "identifier")
    assert len(groups) == 1
    assert {item.id for item in groups[0]} == {row.item_id for row in results}
    assert (await db.get(Item, results[0].item_id)).work == a


@pytest.mark.parametrize(
    "kind,key,url,bare",
    [
        ("PMID", "pmid", "https://pubmed.ncbi.nlm.nih.gov/42", "42"),
        ("PMCID", "pmcid", "https://pmc.ncbi.nlm.nih.gov/articles/PMC42/", "PMC42"),
    ],
)
async def test_openalex_pubmed_urls_suggest_the_same_duplicates_as_bare_identifiers(
    persistence_db, kind, key, url, bare
):
    from inquiro.work import read_work

    db = persistence_db
    actor, workspace_id = await owner(db)
    source = read_work(
        {"id": "https://openalex.org/W123", "display_name": "OpenAlex", "ids": {key: url}},
        "openalex",
    )
    original = deepcopy(source)
    created = [
        await create_item(db, actor, workspace_id, value)
        for value in (source, work(identifiers=[{"identifier_type": kind, "identifier": bare}]))
    ]
    groups = await find_duplicates(db, actor, workspace_id, "identifier")
    assert len(groups) == 1
    assert {item.id for item in groups[0]} == {row.item_id for row in created}
    assert (await db.get(Item, created[0].item_id)).work == original


@pytest.mark.parametrize("kind", ["PMID", "PMCID"])
async def test_malformed_identifier_urls_do_not_block_creation_or_import_confirmation(
    persistence_db, kind
):
    import json

    db = persistence_db
    actor, workspace_id = await owner(db)
    value = work(identifiers=[{"identifier_type": kind, "identifier": "https://[bad"}])
    created = await create_item(db, actor, workspace_id, value)
    preview = await stage_import_batch(
        db, actor, workspace_id, json.dumps(value).encode(), "commonmeta"
    )
    assert len(preview.records) == 1 and not preview.errors
    imported = await commit_import_batch(db, actor, workspace_id, preview.id)
    assert len(imported) == 1
    assert await commit_import_batch(db, actor, workspace_id, preview.id) == imported
    assert await find_duplicates(db, actor, workspace_id, "identifier") == []
    assert (await db.get(Item, created.item_id)).work == value
    assert (await db.get(Item, imported[0])).work == value


async def test_csl_reimport_keeps_unicode_doi_duplicates_distinct_from_lowercase_doi(
    persistence_db,
):
    from inquiro.bibliography import export_bibliography_records

    db = persistence_db
    actor, workspace_id = await owner(db)
    values = [
        work(identifiers=[{"identifier_type": "DOI", "identifier": doi}])
        for doi in ("10.1234/Über", "10.1234/über")
    ]
    originals = [await create_item(db, actor, workspace_id, value) for value in values]
    content = export_bibliography_records(values[:1], "csl-json", citation_keys=["unicode"])
    preview = await stage_import_batch(db, actor, workspace_id, content.encode(), "csl-json")
    assert len(preview.records) == 1, preview.errors
    imported = await commit_import_batch(db, actor, workspace_id, preview.id)
    groups = await find_duplicates(db, actor, workspace_id, "identifier")
    assert len(groups) == 1
    assert {item.id for item in groups[0]} == {originals[0].item_id, imported[0]}
    assert (await db.get(Item, originals[0].item_id)).work == values[0]


async def test_container_related_and_credit_identifiers_are_isolated(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    dataset = work(
        resource_id="https://doi.org/10.1234/dataset",
        container={
            "identifiers": [
                {"identifier_type": "DOI", "identifier": "10.1234/paper"},
                {"identifier_type": "ISBN", "identifier": "9780131103627"},
            ]
        },
        relations=[{"id": "https://doi.org/10.1234/paper", "type": "IsSupplementTo"}],
        contributors=[
            {
                "type": "Person",
                "person": {"name": "Jane", "id": "https://orcid.org/0000-0002-1825-0097"},
                "roles": ["Author"],
            }
        ],
    )
    await create_item(db, actor, workspace_id, dataset)
    await create_item(db, actor, workspace_id, work(resource_id="https://doi.org/10.1234/paper"))
    assert await find_duplicates(db, actor, workspace_id, "identifier") == []


async def test_legacy_pubmed_url_does_not_match_a_pmc_article(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    ids = [
        (
            await create_item(db, actor, workspace_id, work(str(index), resource_id=resource_id))
        ).item_id
        for index, resource_id in enumerate([
            "https://www.ncbi.nlm.nih.gov/pubmed/42",
            "https://pubmed.ncbi.nlm.nih.gov/42/",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC42/",
        ])
    ]
    groups = await find_duplicates(db, actor, workspace_id, "identifier")
    assert [{item.id for item in group} for group in groups] == [set(ids[:2])]


@pytest.mark.parametrize("role", ["Author", "Editor"])
async def test_search_indexes_active_credit_name_and_all_supplied_name_parts(persistence_db, role):
    db = persistence_db
    actor, workspace_id = await owner(db)
    created = await create_item(
        db,
        actor,
        workspace_id,
        work(
            contributors=[
                {
                    "type": "Person",
                    "person": {
                        "name": "A. Researcher",
                        "family_name": "Researcher",
                        "given_name": "Ada",
                    },
                    "organization": {"name": "Inactive Council"},
                    "roles": [role],
                }
            ]
        ),
    )
    for term in ("Ada", "Researcher"):
        items, count = await search_library(db, actor, workspace_id, q=term)
        assert count == 1 and [item.id for item in items] == [created.item_id]
    assert (await search_library(db, actor, workspace_id, q="Inactive"))[1] == 0


async def test_identifier_lookup_is_authorized_and_workspace_scoped(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    outsider, private_id = await owner(db)
    await create_item(db, outsider, private_id, work(resource_id="https://doi.org/10.1234/private"))
    assert await find_duplicates(db, actor, workspace_id, "identifier") == []
    with pytest.raises((WorkspaceUnavailable, WorkspaceMembershipRequired)):
        await find_duplicates(db, actor, private_id, "identifier")


async def test_import_duplicates_keep_both_records_and_confirmation_is_idempotent(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    await create_item(db, actor, workspace_id, work(resource_id="https://doi.org/10.1234/shared"))
    batch = await stage_import_batch(
        db,
        actor,
        workspace_id,
        b"@article{first,title={First},doi={10.1234/shared}}\n@article{second,title={Second},doi={10.1234/shared}}",
        "bibtex",
    )
    assert len(batch.records) == 2
    assert all(
        error.code == "format_limitations" and error.severity == "warning" for error in batch.errors
    )
    ids = await commit_import_batch(db, actor, workspace_id, batch.id)
    assert len(set(ids)) == 2
    assert await commit_import_batch(db, actor, workspace_id, batch.id) == ids
    stored = await db.get(ImportBatch, batch.id)
    assert stored.status == "committed" and stored.records == []


async def test_copy_into_workspace_with_same_identifier_preserves_work(persistence_db):
    db = persistence_db
    actor, source_id = await owner(db)
    destination = Workspace(name="Target", created_by=actor.id)
    db.add(destination)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=destination.id, user_id=actor.id, role=WorkspaceRole.owner))
    await db.commit()
    metadata = work(
        resource_id="https://doi.org/10.1234/shared",
        identifiers=[{"identifier_type": "DOI", "identifier": "10.1234/another"}],
        relations=[{"id": "https://doi.org/10.1234/related", "type": "IsSupplementTo"}],
    )
    source = await create_item(db, actor, source_id, metadata)
    await create_item(db, actor, destination.id, metadata)
    copied = await copy_item_to_workspace(db, actor, source_id, destination.id, source.item_id)
    assert copied.id != source.item_id
    assert copied.work == metadata
    assert len(await find_duplicates(db, actor, destination.id, "identifier")) == 1


async def test_full_work_revision_keeps_hidden_fields_and_enforces_cas(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    metadata = work(
        relations=[{"id": "https://doi.org/10.1234/related", "type": "IsSupplementTo"}],
        funding_references=[{"funder_name": "Foundation"}],
    )
    created = await create_item(db, actor, workspace_id, metadata)
    changed = deepcopy(metadata) | {"title": "Revised"}
    result = await revise_item_metadata(
        db, actor, workspace_id, created.item_id, created.version, changed
    )
    assert result.version == created.version + 1
    with pytest.raises(VersionConflict):
        await revise_item_metadata(
            db, actor, workspace_id, created.item_id, created.version, metadata
        )
    assert (await db.get(Item, created.item_id)).work == changed


async def test_partial_provider_sync_preserves_local_facts(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    local = work(
        contributors=[
            {"type": "Organization", "organization": {"name": "Local council"}, "roles": ["Author"]}
        ],
        subjects=[{"subject": "Local topic"}],
        relations=[{"id": "https://doi.org/10.1234/related", "type": "IsSupplementTo"}],
    )
    created = await create_item(db, actor, workspace_id, local)
    item = await db.get(Item, created.item_id)
    incoming = work(
        "Provider title",
        contributors=[{"type": "Person", "person": {"family_name": "Smith"}, "roles": ["Author"]}],
        subjects=[{"subject": "Provider topic"}],
    )
    merged = candidate_write(incoming, current=item.work)["work"]
    assert merged["id"] == local["id"]
    assert merged["contributors"][0] == local["contributors"][0]
    assert merged["relations"] == local["relations"]
    assert merged["subjects"] == [{"subject": "Local topic"}, {"subject": "Provider topic"}]


async def test_search_facets_read_work_and_author_roles(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    metadata = work(
        "Dataset Alpha",
        contributors=[
            {
                "type": "Person",
                "person": {"family_name": "Smith", "given_name": "Jane"},
                "roles": ["Author"],
            },
            {
                "type": "Organization",
                "organization": {"name": "Editors council"},
                "roles": ["Editor"],
            },
        ],
        subjects=[{"subject": "Graph; theory"}],
        identifiers=[{"identifier_type": "PMID", "identifier": "123456"}],
    )
    await create_item(db, actor, workspace_id, metadata)
    facets = await get_library_facets(db, actor, workspace_id)
    assert [(row.last_name, row.item_count) for row in facets.authors] == [("Smith", 1)]
    assert [(row.value, row.item_count) for row in facets.keywords] == [("Graph; theory", 1)]
    assert (await search_library(db, actor, workspace_id, q="123456"))[1] == 1
    assert (
        await search_library(db, actor, workspace_id, author="Smith", keyword_exact="Graph; theory")
    )[1] == 1


async def test_concurrent_creation_allows_shared_identifiers(persistence_sessions):
    async with persistence_sessions() as db:
        actor, workspace_id = await owner(db)
        actor_id = actor.id

    async def create():
        async with persistence_sessions() as db:
            actor = await db.get(User, actor_id)
            return await create_item(
                db, actor, workspace_id, work(resource_id="https://doi.org/10.1234/shared")
            )

    results = await asyncio.gather(create(), create())
    assert len({row.item_id for row in results}) == 2
    async with persistence_sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Item)) == 2


async def test_provider_merge_keeps_local_credit_ids_and_affiliations(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    credit = {
        "type": "Person",
        "person": {
            "id": "https://orcid.org/0000-0002-1825-0097",
            "family_name": "Smith",
            "given_name": "Jane",
            "affiliations": [{"name": "Local Institute"}],
        },
        "roles": ["Author", "CorrespondingAuthor"],
    }
    metadata = work(contributors=[credit], funding_references=[{"funder_name": "Local Foundation"}])
    created = await create_item(db, actor, workspace_id, metadata)
    item = await db.get(Item, created.item_id)
    incoming = {
        "contributors": [
            {
                "type": "Person",
                "person": {
                    "family_name": "Smith",
                    "given_name": "Jane",
                    "affiliations": [{"name": "Provider Institute"}],
                },
                "roles": ["Author"],
            }
        ],
        "funding_references": [{"funder_name": "Provider Foundation"}],
    }
    merged = candidate_write(incoming, current=item.work)["work"]
    assert len(merged["contributors"]) == 1
    merged_credit = merged["contributors"][0]
    assert merged_credit["person"]["id"] == credit["person"]["id"]
    assert merged_credit["roles"] == credit["roles"]
    assert merged_credit["person"]["affiliations"] == [
        {"name": "Local Institute"},
        {"name": "Provider Institute"},
    ]
    assert merged["funding_references"] == [
        {"funder_name": "Local Foundation"},
        {"funder_name": "Provider Foundation"},
    ]


@pytest.mark.parametrize("reverse", [False, True])
async def test_provider_merge_preserves_suffix_distinguished_authors_across_repeated_syncs(
    persistence_db, reverse
):
    db = persistence_db
    actor, workspace_id = await owner(db)
    credits = [
        {
            "type": "Person",
            "person": {
                "name": f"John Smith {suffix}",
                "family_name": "Smith",
                "given_name": "John",
                "affiliations": [{"name": f"{suffix} local institute"}],
            },
            "roles": ["Author", "CorrespondingAuthor"],
        }
        for suffix in ("Jr", "Sr")
    ]
    incoming = [
        {
            "type": "Person",
            "person": {
                "name": f"John Smith {suffix}",
                "family_name": "Smith",
                "given_name": "John",
                "affiliations": [{"name": f"{suffix} provider institute"}],
            },
            "roles": ["Author"],
        }
        for suffix in (("Sr", "Jr") if reverse else ("Jr", "Sr"))
    ]
    original = deepcopy(incoming)
    created = await create_item(db, actor, workspace_id, work(contributors=credits))
    item = await db.get(Item, created.item_id)
    for _ in range(3):
        merged = candidate_write({"contributors": incoming}, current=item.work)["work"]
        assert len(merged["contributors"]) == 2
        assert [credit["person"]["name"] for credit in merged["contributors"]] == [
            "John Smith Jr",
            "John Smith Sr",
        ]
        for suffix, credit in zip(("Jr", "Sr"), merged["contributors"], strict=True):
            assert credit["person"]["affiliations"] == [
                {"name": f"{suffix} local institute"},
                {"name": f"{suffix} provider institute"},
            ]
            assert credit["roles"] == ["Author", "CorrespondingAuthor"]
        item.work = merged
        await db.commit()
    assert incoming == original


async def test_provider_merge_does_not_conflate_shared_display_names(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    credits = [
        {
            "type": "Person",
            "person": {"name": "A. Smith", "family_name": "Smith", "given_name": given},
            "roles": ["Author"],
        }
        for given in ("Ada", "Alan")
    ]
    created = await create_item(db, actor, workspace_id, work(contributors=credits))
    item = await db.get(Item, created.item_id)
    for _ in range(3):
        merged = candidate_write({"contributors": credits}, current=item.work)["work"]
        assert merged["contributors"] == credits
        item.work = merged
        await db.commit()


@pytest.mark.parametrize("local_role", [None, "CorrespondingAuthor", "DataCuration"])
@pytest.mark.parametrize("upstream_role", [None, "CorrespondingAuthor"])
async def test_provider_merge_preserves_separate_author_editor_credits_on_repeated_sync(
    persistence_db, local_role, upstream_role
):
    import json

    from inquiro.bibliography import parse_bibliography_records, work_to_csl_json
    from inquiro.work import work_authors

    db = persistence_db
    actor, workspace_id = await owner(db)
    source = {
        "id": "https://doi.org/10.1000/roles",
        "type": "article-journal",
        "title": "Research",
        "author": [{"family": "Smith", "given": "Jane"}],
        "editor": [{"family": "Smith", "given": "Jane"}],
    }
    records, diagnostics = parse_bibliography_records(json.dumps(source), "csl-json")
    assert len(records) == 1, diagnostics
    local = records[0].work
    if local_role:
        local["contributors"][0]["roles"].append(local_role)
    local["contributors"][0]["person"]["affiliations"] = [{"name": "Author Institute"}]
    local["contributors"][1]["person"]["affiliations"] = [{"name": "Editor Institute"}]
    created = await create_item(db, actor, workspace_id, local)
    item = await db.get(Item, created.item_id)
    incoming = {"contributors": [records[0].work["contributors"][0]]}
    incoming = deepcopy(incoming)
    incoming["contributors"][0]["roles"] = ["Author"]
    if upstream_role:
        incoming["contributors"][0]["roles"].append(upstream_role)
    incoming["contributors"][0]["person"]["affiliations"] = [{"name": "Provider Institute"}]
    original = deepcopy(incoming)
    for _ in range(3):
        merged = candidate_write(incoming, current=item.work)["work"]
        assert len(merged["contributors"]) == 2
        author, editor = merged["contributors"]
        expected_roles = list(
            dict.fromkeys(role for role in ["Author", local_role, upstream_role] if role)
        )
        assert author["roles"] == expected_roles
        assert author["person"]["affiliations"] == [
            {"name": "Author Institute"},
            {"name": "Provider Institute"},
        ]
        assert editor == local["contributors"][1]
        assert work_authors(merged) == [author]
        projected = work_to_csl_json(merged)
        assert projected["author"] == [{"family": "Smith", "given": "Jane"}]
        assert projected["editor"] == [{"family": "Smith", "given": "Jane"}]
        item.work = merged
        await db.commit()
    assert incoming == original


async def test_provider_merge_does_not_append_already_represented_ambiguous_credits(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    incoming = {
        "type": "Person",
        "person": {"family_name": "Smith", "given_name": "Jane"},
        "roles": ["Author"],
    }
    credits = [
        incoming | {"person": incoming["person"] | {"affiliations": [{"name": name}]}}
        for name in ("First Institute", "Second Institute")
    ]
    created = await create_item(db, actor, workspace_id, work(contributors=credits))
    item = await db.get(Item, created.item_id)
    for _ in range(3):
        merged = candidate_write({"contributors": [incoming]}, current=item.work)["work"]
        assert merged["contributors"] == credits
        item.work = merged
        await db.commit()


async def test_bibtex_export_reimport_preserves_protected_names_title_and_key_on_commit(
    persistence_db,
):
    from inquiro.bibliography import export_bibliography_records

    db = persistence_db
    actor, workspace_id = await owner(db)
    credit = {
        "type": "Organization",
        "organization": {"name": "Research and Development Corp."},
        "roles": ["Author"],
    }
    metadata = work("A <i>great</i> result", type="JournalArticle", contributors=[credit])
    content = export_bibliography_records([metadata], "bibtex", citation_keys=["smith2024"])
    preview = await stage_import_batch(db, actor, workspace_id, content.encode(), "bibtex")
    assert len(preview.records) == 1, preview.errors
    assert all(error.severity == "warning" for error in preview.errors)
    ids = await commit_import_batch(db, actor, workspace_id, preview.id)
    assert await commit_import_batch(db, actor, workspace_id, preview.id) == ids
    item = await db.get(Item, ids[0])
    assert item.citation_key == "smith2024"
    assert item.work["type"] == "JournalArticle"
    assert item.work["title"] == metadata["title"]
    assert item.work["contributors"] == [credit]


async def test_import_commits_valid_duplicate_alongside_invalid_item(persistence_db):
    import json

    db = persistence_db
    actor, workspace_id = await owner(db)
    existing = work("Existing", resource_id="https://doi.org/10.1234/shared")
    await create_item(db, actor, workspace_id, existing)
    values = [
        existing | {"title": "Valid duplicate"},
        {"id": f"urn:uuid:{uuid4()}", "type": "Dataset"},
    ]
    preview = await stage_import_batch(
        db, actor, workspace_id, json.dumps(values).encode(), "commonmeta"
    )
    assert len(preview.records) == 1
    assert any(error.row == 2 and error.code == "invalid_item" for error in preview.errors)
    assert len(preview.errors) == 1
    ids = await commit_import_batch(db, actor, workspace_id, preview.id)
    assert len(ids) == 1
    assert (await db.get(Item, ids[0])).work["title"] == "Valid duplicate"
    assert await commit_import_batch(db, actor, workspace_id, preview.id) == ids


async def test_typed_work_is_revalidated_before_persistence(persistence_db):
    from quirebase.core.errors import ValidationFailure
    from quirebase.library import Work

    db = persistence_db
    actor, workspace_id = await owner(db)
    value = Work.model_validate(work())
    # model_copy deliberately bypasses Pydantic validation; the Library write
    # boundary must still reject the resulting invalid standard payload.
    invalid = value.model_copy(update={"id": "relative-id"})
    with pytest.raises(ValidationFailure):
        await create_item(db, actor, workspace_id, invalid)
    assert await db.scalar(select(func.count()).select_from(Item)) == 0


@pytest.mark.parametrize("invalid", [{"author": ["Jane Smith"]}, {"issued": "2024"}])
async def test_malformed_csl_import_keeps_valid_siblings_and_commit_replay(persistence_db, invalid):
    import json

    db = persistence_db
    actor, workspace_id = await owner(db)
    valid = {"id": "https://doi.org/10.1234/valid", "type": "article-journal", "title": "Valid"}
    preview = await stage_import_batch(
        db, actor, workspace_id, json.dumps([valid | invalid, valid]).encode(), "csl-json"
    )
    assert len(preview.records) == 1
    assert [(error.row, error.code) for error in preview.errors if error.severity == "error"] == [
        (1, "invalid_record")
    ]
    ids = await commit_import_batch(db, actor, workspace_id, preview.id)
    assert len(ids) == 1
    assert (await db.get(Item, ids[0])).work["title"] == "Valid"
    assert await commit_import_batch(db, actor, workspace_id, preview.id) == ids


async def test_ris_conversion_losses_are_diagnosed_before_staging(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    content = b"TY  - JOUR\nT1  - State-of-the-art\nDO  - 10.1000/foo-bar\nER  - \nTY  - JOUR\nTI  - Valid alias title\nDO  - 10.1000/valid\nER  - "
    preview = await stage_import_batch(db, actor, workspace_id, content, "ris")
    assert len(preview.records) == 1
    assert preview.records[0].metadata.title == "Valid alias title"
    assert any(error.row == 1 and error.code == "invalid_record" for error in preview.errors)
    ids = await commit_import_batch(db, actor, workspace_id, preview.id)
    assert len(ids) == 1
    assert (await db.get(Item, ids[0])).work["title"] == "Valid alias title"


@pytest.mark.parametrize("person", [{"given_name": "Ada"}, {"name": "Ada"}])
async def test_single_name_authors_have_consistent_suggestions_facets_and_filters(
    persistence_db, person
):
    from quirebase.library import LibraryFilter, search_authors_typeahead

    db = persistence_db
    actor, workspace_id = await owner(db)
    created = await create_item(
        db,
        actor,
        workspace_id,
        work(contributors=[{"type": "Person", "person": person, "roles": ["Author"]}]),
    )
    assert await search_authors_typeahead(db, actor, workspace_id, "Ada") == [
        {"last_name": "Ada", "first_name": None, "full_name": "Ada"}
    ]
    facets = await get_library_facets(db, actor, workspace_id)
    assert [(row.last_name, row.first_name, row.item_count) for row in facets.authors] == [
        ("Ada", None, 1)
    ]
    filtered = await get_library_facets(
        db, actor, workspace_id, LibraryFilter(author_last_name="Ada", author_first_name="")
    )
    assert filtered == facets
    items, total = await search_library(db, actor, workspace_id, author="Ada")
    assert total == 1 and [item.id for item in items] == [created.item_id]


async def test_contributor_type_selects_active_names_in_library_projections(persistence_db):
    from quirebase.library import search_authors_typeahead
    from quirebase.library._metadata import item_summary

    db = persistence_db
    actor, workspace_id = await owner(db)
    metadata = work(
        contributors=[
            {
                "type": "Organization",
                "person": {
                    "name": "Ada Researcher",
                    "family_name": "Researcher",
                    "given_name": "Ada",
                },
                "organization": {"name": "Research Council"},
                "roles": ["Author"],
            }
        ]
    )
    created = await create_item(db, actor, workspace_id, metadata)
    item = await db.get(Item, created.item_id)
    assert item.work == metadata
    assert item_summary(item)["authors"] == "Research Council"
    suggestions = await search_authors_typeahead(db, actor, workspace_id, "Research")
    assert suggestions == [
        {"last_name": "Research Council", "first_name": None, "full_name": "Research Council"}
    ]
    facets = await get_library_facets(db, actor, workspace_id)
    assert [(row.last_name, row.first_name) for row in facets.authors] == [
        ("Research Council", None)
    ]
    assert (await search_library(db, actor, workspace_id, author="Ada"))[1] == 0
    assert (await search_library(db, actor, workspace_id, author="Council"))[1] == 1


@pytest.mark.parametrize("source", ["bibliography", "identifier", "pdf"])
async def test_import_previews_do_not_read_stored_items(persistence_db, monkeypatch, source):
    from unittest.mock import AsyncMock

    from inquiro import CandidateRecord, Identifier

    from quirebase.core.config import get_settings
    from quirebase.library.imports import (
        check_pdf_import_eligibility,
        stage_identifier_import_batch,
    )

    db = persistence_db
    actor, workspace_id = await owner(db)
    metadata = work(resource_id="https://doi.org/10.1234/shared")
    await create_item(db, actor, workspace_id, metadata)
    monkeypatch.setattr(
        "quirebase.library.imports.lookup_candidate",
        AsyncMock(
            return_value=CandidateRecord(
                provider="crossref",
                lookup_identifier=Identifier("doi", "10.1234/shared"),
                work=metadata,
            )
        ),
    )
    batch = ImportBatch(
        workspace_id=workspace_id,
        actor_id=actor.id,
        file_format="pdf",
        status="pending",
        records=[],
        errors=[],
    )
    db.add(batch)
    await db.commit()
    reads = []

    def record_query(state):
        statement = str(state.statement).lower()
        if state.is_select and "from items" in statement:
            reads.append(statement)

    event.listen(db.sync_session, "do_orm_execute", record_query)
    try:
        if source == "bibliography":
            preview = await stage_import_batch(
                db,
                actor,
                workspace_id,
                b"@article{x,title={Research},doi={10.1234/shared}}",
                "bibtex",
            )
            assert len(preview.records) == 1
            assert all(
                error.code == "format_limitations" and error.severity == "warning"
                for error in preview.errors
            )
        elif source == "identifier":
            preview = await stage_identifier_import_batch(
                db, actor, workspace_id, "10.1234/shared", settings=get_settings()
            )
            assert len(preview.records) == 1 and not preview.errors
        else:
            assert await check_pdf_import_eligibility(
                db, batch.id, {"_pdf": {"object_key": "candidate.pdf"}}
            ) == {"eligible": True, "object_key": "candidate.pdf"}
        assert reads == []
    finally:
        event.remove(db.sync_session, "do_orm_execute", record_query)
