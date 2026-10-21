from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select, update
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import VersionConflict, WorkspaceMembershipRequired, WorkspaceUnavailable
from quirebase.library import (
    LibraryFilter,
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


async def test_title_sort_keeps_stable_pages_in_both_directions(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    titles = ["Zulu", "Alpha", "Alpha", "Beta", "Étude", "Étude", "研究"]
    ids = [(await create_item(db, actor, workspace_id, work(title))).item_id for title in titles]
    ascending = [*sorted(ids[1:3]), ids[3], ids[0], *sorted(ids[4:6]), ids[6]]
    descending = [ids[6], *sorted(ids[4:6]), ids[0], ids[3], *sorted(ids[1:3])]
    for direction, expected in [("asc", ascending), ("desc", descending)]:
        actual = []
        for offset in range(0, len(ids), 2):
            rows, total = await search_library(
                db, actor, workspace_id, sort="title", direction=direction, limit=2, offset=offset
            )
            assert total == len(ids)
            actual.extend(row.id for row in rows)
        assert actual == expected
    await revise_item_metadata(db, actor, workspace_id, ids[0], 1, work("Aardvark"))
    rows, _ = await search_library(db, actor, workspace_id, sort="title")
    assert rows[0].id == ids[0]


async def test_author_sort_uses_first_author_then_editor_before_pagination(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)

    def person(family, role="Author", **fields):
        return {"type": "Person", "person": {"family_name": family, **fields}, "roles": [role]}

    credits = [
        [person("Aardvark", "Editor"), person("Smith", name="Alice Smith"), person("Aaron")],
        [person("Adams", name="Zoe Adams")],
        [
            {
                "type": "Organization",
                "organization": {"name": "Baker Council"},
                "person": {"family_name": "Aardvark"},
                "roles": ["Author"],
            }
        ],
        [person("Clark", "Editor"), person("Aaron", "Editor")],
        [{"type": "Person", "person": {"name": "Delta"}, "roles": ["Author"]}],
        [{"type": "Person", "person": {"given_name": "Echo"}, "roles": ["Author"]}],
        [],
        [person("Aaron", "Translator")],
        [
            {
                "type": "Person",
                "person": {"id": "https://orcid.org/0000-0002-1825-0097"},
                "roles": ["Author"],
            },
            person("Foxtrot", "Editor"),
        ],
        [person("Smith", given_name="Bob")],
        [person("研究")],
    ]
    ids = [
        (
            await create_item(
                db, actor, workspace_id, work(str(i), **({"contributors": rows} if rows else {}))
            )
        ).item_id
        for i, rows in enumerate(credits)
    ]
    outsider, other_workspace = await owner(db)
    await create_item(db, outsider, other_workspace, work("Outside", contributors=[person("AAA")]))
    missing = sorted(ids[6:8])
    for direction, expected in [
        ("asc", [*ids[1:6], ids[8], *sorted([ids[0], ids[9]]), ids[10], *missing]),
        ("desc", [ids[10], *sorted([ids[0], ids[9]]), ids[8], *reversed(ids[1:6]), *missing]),
    ]:
        actual = []
        for offset in range(0, len(ids), 2):
            rows, total = await search_library(
                db, actor, workspace_id, sort="author", direction=direction, limit=2, offset=offset
            )
            assert total == len(ids)
            actual.extend(row.id for row in rows)
        assert actual == expected
    rows, _ = await search_library(db, actor, workspace_id, sort="author")
    assert rows[0].id == ids[1]
    await revise_item_metadata(
        db, actor, workspace_id, ids[0], 1, work("Revised", contributors=[person("Aaron")])
    )
    rows, _ = await search_library(db, actor, workspace_id, sort="author")
    assert rows[0].id == ids[0]


async def test_publication_sort_preserves_precision_and_puts_missing_dates_last(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    dates = [
        "2023",
        "2024",
        "2024-01",
        "2024-01-01",
        "2024-02-03T23:00:00Z",
        "2024-02-03T01:00:00+08:00",
        None,
        None,
    ]
    ids = [
        (
            await create_item(
                db,
                actor,
                workspace_id,
                work(f"Date {index}", **({"date_published": date} if date else {})),
            )
        ).item_id
        for index, date in enumerate(dates)
    ]
    # Items from another Workspace never enter the ordering or count.
    outsider, other_id = await owner(db)
    await create_item(db, outsider, other_id, work("Outside", date_published="2099"))
    for direction, expected in [
        ("asc", [*ids[:4], *sorted(ids[4:6]), *sorted(ids[6:])]),
        ("desc", [*sorted(ids[4:6]), *reversed(ids[:4]), *sorted(ids[6:])]),
    ]:
        rows, total = await search_library(
            db, actor, workspace_id, sort="published", direction=direction
        )
        assert total == len(ids) and [row.id for row in rows] == expected
        assert [row.work.get("date_published") for row in rows] == [
            dates[ids.index(id)] for id in expected
        ]
    rows, total = await search_library(
        db, actor, workspace_id, sort="published", year="2024", limit=2, offset=2
    )
    assert total == 5 and [row.id for row in rows] == [ids[3], ids[2]]


@pytest.mark.parametrize("sort", ["created", "updated"])
async def test_timestamp_sort_supports_both_directions_before_pagination(persistence_db, sort):
    db = persistence_db
    actor, workspace_id = await owner(db)
    ids = [(await create_item(db, actor, workspace_id, work(str(i)))).item_id for i in range(3)]
    for index, id in enumerate(ids):
        timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
        await db.execute(
            update(Item).where(Item.id == id).values(created_at=timestamp, updated_at=timestamp)
        )
    await db.commit()
    for direction, expected in [("asc", ids[:2]), ("desc", list(reversed(ids))[:2])]:
        rows, total = await search_library(
            db, actor, workspace_id, sort=sort, direction=direction, limit=2
        )
        assert total == 3 and [row.id for row in rows] == expected


async def test_publication_sort_supports_both_directions_and_missing_names(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    publications = ["Zulu Journal", "Alpha Journal", "Alpha Journal", "特刊", "", None]
    ids = [
        (
            await create_item(
                db,
                actor,
                workspace_id,
                work(
                    f"Publication {index}",
                    **({"container": {"title": publication}} if publication is not None else {}),
                ),
            )
        ).item_id
        for index, publication in enumerate(publications)
    ]
    for direction, expected in [
        ("asc", [*sorted(ids[1:3]), ids[0], ids[3], *sorted(ids[4:])]),
        ("desc", [ids[3], ids[0], *sorted(ids[1:3]), *sorted(ids[4:])]),
    ]:
        rows, total = await search_library(
            db, actor, workspace_id, sort="publication", direction=direction
        )
        assert total == 6 and [row.id for row in rows] == expected
    rows, total = await search_library(
        db, actor, workspace_id, sort="publication", limit=1, offset=2
    )
    assert total == 6 and rows[0].id == ids[0]
    rows, total = await search_library(
        db, actor, workspace_id, sort="publication", publication_title="Alpha Journal"
    )
    assert total == 2 and [row.id for row in rows] == sorted(ids[1:3])


async def test_duplicate_identifiers_group_each_shared_key_without_transitive_matching(
    persistence_db,
):
    db = persistence_db
    actor, workspace_id = await owner(db)
    a = work(
        "First",
        resource_id="https://doi.org/10.1234/ONE",
        identifiers=[
            {"identifier_type": "DOI", "identifier": "10.1234/one"},
            {"identifier_type": "DOI", "identifier": "10.1234/two"},
        ],
    )
    b = work(
        "Second",
        identifiers=[
            {"identifier_type": "DOI", "identifier": "10.1234/one"},
            {"identifier_type": "PMID", "identifier": "42"},
        ],
    )
    c = work("Third", identifiers=[{"identifier_type": "PMID", "identifier": "42"}])
    results = [await create_item(db, actor, workspace_id, value) for value in (a, b, c)]
    groups = (await find_duplicates(db, actor, workspace_id, "identifier")).groups
    assert {frozenset(item.id for item in group) for group in groups} == {
        frozenset([results[0].item_id, results[1].item_id]),
        frozenset([results[1].item_id, results[2].item_id]),
    }
    assert (await db.get(Item, results[0].item_id)).work == a


async def test_identifier_scan_keeps_exact_namespace_scheme_and_workspace_boundaries(
    persistence_db,
):
    db = persistence_db
    actor, workspace_id = await owner(db)
    outsider, private_id = await owner(db)
    identifiers = [
        {"identifier_type": "DOI", "identifier": "10.1234/shared"},
        {"identifier_type": "DOI", "identifier": "10.1234/shared"},
        {"identifier_type": "PMID", "identifier": "42"},
        {"identifier_type": "PMCID", "identifier": "42"},
        {"identifier_type": "Other", "scheme": "local", "identifier": "custom"},
        {"identifier_type": "Other", "scheme": "local", "identifier": "custom"},
        {"identifier_type": "Other", "scheme": "different", "identifier": "custom"},
        {"identifier_type": "Other", "scheme": "DOI", "identifier": "10.1234/shared"},
        {"identifier_type": "DOI", "identifier": "10.1234/CASE"},
        {"identifier_type": "DOI", "identifier": "10.1234/case"},
        {"identifier_type": "DOI", "identifier": "10.1234/spaces"},
        {"identifier_type": "DOI", "identifier": " 10.1234/spaces "},
        {"identifier_type": "DOI", "identifier": "https://doi.org/10.1234/shared"},
        {"identifier_type": "DOI", "identifier": "10.1234/private"},
    ]
    created = [
        await create_item(db, actor, workspace_id, work(str(index), identifiers=[identifier]))
        for index, identifier in enumerate(identifiers)
    ]
    # A matching external identifier in a different Workspace is not a candidate.
    await create_item(db, outsider, private_id, work("Private", identifiers=[identifiers[-1]]))
    # Primary Work URIs and additional identifiers have separate exact keys.
    await create_item(
        db, actor, workspace_id, work("Primary URI", resource_id=identifiers[-2]["identifier"])
    )
    groups = (await find_duplicates(db, actor, workspace_id, "identifier")).groups
    assert {frozenset(item.id for item in group) for group in groups} == {
        frozenset([created[0].item_id, created[1].item_id]),
        frozenset([created[4].item_id, created[5].item_id]),
    }
    assert all(item.workspace_id == workspace_id for group in groups for item in group)


async def test_identifier_scan_ignores_empty_and_repeated_keys_within_one_item(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    repeated = {"identifier_type": "DOI", "identifier": "10.1234/only-one-item"}
    await create_item(db, actor, workspace_id, work("Repeated", identifiers=[repeated, repeated]))
    empty = [
        {"identifier_type": "DOI", "identifier": ""},
        {"identifier_type": "DOI", "identifier": "   "},
        {"identifier_type": "DOI", "identifier": "\t\n\r"},
        {"identifier_type": "Other", "identifier": "no-scheme"},
        {"identifier_type": "Other", "scheme": "", "identifier": "empty-scheme"},
        {"identifier_type": "Other", "scheme": "   ", "identifier": "blank-scheme"},
        {"identifier_type": "Other", "scheme": "\t\n", "identifier": "blank-scheme"},
    ]
    for index in range(2):
        await create_item(db, actor, workspace_id, work(str(index), identifiers=empty))
    scan = await find_duplicates(db, actor, workspace_id, "identifier")
    assert scan.scanned == 3
    assert scan.groups == []


async def test_identifier_scan_returns_one_group_for_multiple_shared_keys(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    shared = work(
        resource_id=f"urn:uuid:{uuid4()}",
        identifiers=[
            {"identifier_type": "DOI", "identifier": "10.1234/shared"},
            {"identifier_type": "DOI", "identifier": "10.1234/shared"},
            {"identifier_type": "PMID", "identifier": "42"},
        ],
    )
    created = [await create_item(db, actor, workspace_id, shared) for _ in range(2)]
    scan = await find_duplicates(db, actor, workspace_id, "identifier")
    assert scan.scanned == 2
    assert len(scan.groups) == 1
    assert {item.id for item in scan.groups[0]} == {row.item_id for row in created}


@pytest.mark.parametrize("mode,old_limit", [("identifier", 2000), ("title", 2000)])
async def test_duplicate_scan_finds_late_matches_beyond_old_limits(persistence_db, mode, old_limit):
    db = persistence_db
    actor, workspace_id = await owner(db)
    outsider, private_id = await owner(db)
    # Matching Items sort after the old cap; unique prefixes exercise the full scan.
    matched_ids = [uuid4(), uuid4()]
    matching = [
        work("zzzz common duplicate reference alpha", resource_id="https://doi.org/10.1234/shared"),
        work(
            "zzzz common duplicate reference alpha",
            resource_id="https://doi.org/10.1234/shared",
        ),
    ]
    await db.execute(
        insert(Item),
        [
            {"workspace_id": workspace_id, "created_by": actor.id, "work": work(f"a-{uuid4()}")}
            for _ in range(old_limit)
        ]
        + [
            {"id": item_id, "workspace_id": workspace_id, "created_by": actor.id, "work": value}
            for item_id, value in zip(matched_ids, matching, strict=True)
        ]
        + [{"workspace_id": private_id, "created_by": outsider.id, "work": matching[0]}],
    )
    await db.commit()

    scan = await find_duplicates(db, actor, workspace_id, mode)
    assert scan.scanned == old_limit + 2
    assert {item.id for group in scan.groups for item in group} == set(matched_ids)
    assert all(item.workspace_id == workspace_id for group in scan.groups for item in group)


async def test_empty_duplicate_scan(persistence_db):
    actor, workspace_id = await owner(persistence_db)
    scan = await find_duplicates(persistence_db, actor, workspace_id, "title")
    assert scan.groups == []
    assert scan.scanned == 0


async def test_same_title_scan_groups_exact_values_with_stable_order(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    outsider, private_id = await owner(db)
    titles = [
        "Alpha Research",
        "Alpha Research",
        "alpha research",
        "Alpha <i>Research</i>",
        "Alpha Research!",
        "研究",
        "研究",
        "Annual report 2023",
        "Annual report 2024",
        "",
        "",
        None,
    ]
    ids = [uuid4() for _ in titles]
    await db.execute(
        insert(Item),
        [
            {
                "id": item_id,
                "workspace_id": workspace_id,
                "created_by": actor.id,
                "work": work(title),
            }
            for item_id, title in zip(ids, titles, strict=True)
        ]
        # A title seen once here and once elsewhere is not a Workspace duplicate.
        + [{"workspace_id": private_id, "created_by": outsider.id, "work": work(titles[2])}],
    )
    await db.commit()

    scan = await find_duplicates(db, actor, workspace_id, "title")
    assert scan.scanned == len(titles)
    assert [[item.id for item in group] for group in scan.groups] == [
        sorted(ids[:2]),
        sorted(ids[5:7]),
    ]


@pytest.mark.parametrize("mode", ["identifier", "title"])
async def test_duplicate_scan_aggregates_in_sql_and_loads_only_matching_items(persistence_db, mode):
    from sqlalchemy.sql import visitors

    db = persistence_db
    actor, workspace_id = await owner(db)
    unique_id = uuid4()
    shared = work("Shared", resource_id="https://doi.org/10.1234/shared", abstract="x" * 4096)
    await db.execute(
        insert(Item),
        [
            {"workspace_id": workspace_id, "created_by": actor.id, "work": shared}
            for _ in range(1001)
        ]
        + [
            {
                "id": unique_id,
                "workspace_id": workspace_id,
                "created_by": actor.id,
                "work": work("Unique"),
            }
        ],
    )
    await db.commit()
    queries = []

    def capture(execution):
        statement = execution.statement
        if execution.is_select and (
            Item.__table__ in statement.get_final_froms()
            or any(node is Item.__table__ for node in visitors.iterate(statement))
        ):
            queries.append(statement)

    event.listen(db.sync_session, "do_orm_execute", capture)
    try:
        scan = await find_duplicates(db, actor, workspace_id, mode)
    finally:
        event.remove(db.sync_session, "do_orm_execute", capture)

    assert scan.scanned == 1002
    assert len(scan.groups) == 1 and len(scan.groups[0]) == 1001
    # Count the scope, then detect and hydrate matches in one statement. No
    # candidate projection or per-batch hydration leaves a metadata race.
    assert len(queries) == 2
    assert len(queries[0].selected_columns) == 1
    assert len(queries[1].selected_columns) >= len(Item.__table__.columns)
    assert "HAVING count(" in str(queries[1])
    assert (Item, (unique_id,), None) not in db.identity_map


@pytest.mark.parametrize("mode", ["identifier", "title", "file"])
@pytest.mark.parametrize("has_matches", [False, True])
async def test_duplicate_scan_rechecks_access_after_detection(
    persistence_db, persistence_sessions, monkeypatch, mode, has_matches
):
    from quirebase.library import duplicates
    from quirebase.models import WorkspaceMemberState

    db = persistence_db
    _, workspace_id = await owner(db)
    actor = User(username=f"viewer-{uuid4()}", password_hash="hash")
    db.add(actor)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace_id, user_id=actor.id, role=WorkspaceRole.viewer))
    shared = work("Shared")
    await db.execute(
        insert(Item),
        [
            {"workspace_id": workspace_id, "created_by": actor.id, "work": shared}
            for _ in range(2 if has_matches else 1)
        ],
    )
    if mode == "file":
        from advanced_alchemy.types import FileObject

        from quirebase.models import FileRevision, FileRevisionProcessingState

        for item in await db.scalars(select(Item).where(Item.workspace_id == workspace_id)):
            db.add(
                FileRevision(
                    workspace_id=workspace_id,
                    item_id=item.id,
                    created_by=actor.id,
                    file=FileObject(
                        backend="documents",
                        filename=f"{uuid4().hex}.pdf",
                        checksum="sha256:" + "a" * 64,
                    ),
                    processing_state=FileRevisionProcessingState.ready,
                )
            )
    await db.commit()
    original_require = duplicates.require_workspace_action
    checks = 0

    async def revoke_after_detection(*args, **kwargs):
        nonlocal checks
        checks += 1
        if checks == 2:
            async with persistence_sessions() as governor_db:
                await governor_db.execute(
                    update(WorkspaceMember)
                    .where(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.user_id == actor.id,
                    )
                    .values(state=WorkspaceMemberState.suspended)
                )
                await governor_db.commit()
        return await original_require(*args, **kwargs)

    monkeypatch.setattr(duplicates, "require_workspace_action", revoke_after_detection)
    with pytest.raises(WorkspaceMembershipRequired):
        await find_duplicates(db, actor, workspace_id, mode)


@pytest.mark.parametrize(
    "kind,key,url,bare",
    [
        ("PMID", "pmid", "https://pubmed.ncbi.nlm.nih.gov/42", "42"),
        ("PMCID", "pmcid", "https://pmc.ncbi.nlm.nih.gov/articles/PMC42/", "PMC42"),
    ],
)
async def test_identifier_scan_preserves_url_and_bare_identifier_forms(
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
    groups = (await find_duplicates(db, actor, workspace_id, "identifier")).groups
    assert groups == []
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
    imported = (await commit_import_batch(db, actor, workspace_id, preview.id)).committed_item_ids
    assert len(imported) == 1
    assert (
        await commit_import_batch(db, actor, workspace_id, preview.id)
    ).committed_item_ids == imported
    groups = (await find_duplicates(db, actor, workspace_id, "identifier")).groups
    assert [{item.id for item in group} for group in groups] == [{created.item_id, imported[0]}]
    assert (await db.get(Item, created.item_id)).work == value
    assert (await db.get(Item, imported[0])).work == value


async def test_csl_reimport_preserves_identifier_forms_without_implicit_normalization(
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
    imported = (await commit_import_batch(db, actor, workspace_id, preview.id)).committed_item_ids
    groups = (await find_duplicates(db, actor, workspace_id, "identifier")).groups
    # CSL conversion writes a resolver URI into Work.id. The raw additional DOI
    # is preserved on the source Item and is not compared across those fields.
    assert groups == []
    assert (await db.get(Item, originals[0].item_id)).work == values[0]
    assert (await db.get(Item, imported[0])).work["id"].startswith("https://doi.org/")


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
    assert (await find_duplicates(db, actor, workspace_id, "identifier")).groups == []


async def test_primary_identifier_uris_require_exact_values(persistence_db):
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
            "https://pubmed.ncbi.nlm.nih.gov/42/",
        ])
    ]
    groups = (await find_duplicates(db, actor, workspace_id, "identifier")).groups
    assert [{item.id for item in group} for group in groups] == [{ids[1], ids[3]}]


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
    assert (await find_duplicates(db, actor, workspace_id, "identifier")).groups == []
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
    ids = (await commit_import_batch(db, actor, workspace_id, batch.id)).committed_item_ids
    assert len(set(ids)) == 2
    assert (await commit_import_batch(db, actor, workspace_id, batch.id)).committed_item_ids == ids
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
    assert len((await find_duplicates(db, actor, destination.id, "identifier")).groups) == 1


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


async def test_publication_filters_share_exact_candidates_pagination_and_facets(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    publication = 'Journal & 特刊; 50%_ "Q"'
    matching = []
    for index, title in enumerate((
        publication,
        publication,
        publication + " supplement",
        publication.lower(),
    )):
        result = await create_item(
            db,
            actor,
            workspace_id,
            work(
                f"Record {index}",
                container={"title": title},
                date_published="2024-06-15",
                subjects=[{"subject": "Graph; theory"}],
                contributors=[{"type": "Person", "person": {"name": "Ada"}, "roles": ["Author"]}],
            ),
        )
        if index < 2:
            matching.append(result.item_id)
    other, other_workspace = await owner(db)
    await create_item(db, other, other_workspace, work(container={"title": publication}))
    pages = []
    for offset in (0, 1):
        rows, total = await search_library(
            db,
            actor,
            workspace_id,
            publication_title=publication,
            limit=1,
            offset=offset,
            year="2024",
            reference_type="Dataset",
            keyword_exact="Graph; theory",
            author_last_name="Ada",
            author_first_name="",
        )
        assert total == 2
        pages.extend(item.id for item in rows)
    assert set(pages) == set(matching)
    facets = await get_library_facets(
        db, actor, workspace_id, LibraryFilter(publication_title=publication)
    )
    assert [(row.last_name, row.item_count) for row in facets.authors] == [("Ada", 2)]
    assert [(row.value, row.item_count) for row in facets.keywords] == [("Graph; theory", 2)]


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


async def test_provider_merge_keeps_conflicting_ids_despite_equivalent_joined_names(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    original = {
        "type": "Person",
        "person": {
            "id": "https://orcid.org/0000-0002-1292-8987",
            "given_name": "Hossein",
            "family_name": "Bonyan Khamseh",
            "affiliations": [{"name": "Local Institute"}],
        },
        "roles": ["Author"],
    }
    incoming = {
        "type": "Person",
        "person": {
            "id": "https://orcid.org/0000-0002-7294-6626",
            "given_name": "Hossein Bonyan",
            "family_name": "Khamseh",
            "affiliations": [{"name": "Other Institute"}],
        },
        "roles": ["Author"],
    }
    created = await create_item(db, actor, workspace_id, work(contributors=[original]))
    item = await db.get(Item, created.item_id)
    for _ in range(3):
        merged = candidate_write({"contributors": [incoming]}, current=item.work)["work"]
        assert merged["contributors"] == [original, incoming]
        item.work = merged
        await db.commit()


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
    ids = (await commit_import_batch(db, actor, workspace_id, preview.id)).committed_item_ids
    assert (
        await commit_import_batch(db, actor, workspace_id, preview.id)
    ).committed_item_ids == ids
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
    ids = (await commit_import_batch(db, actor, workspace_id, preview.id)).committed_item_ids
    assert len(ids) == 1
    assert (await db.get(Item, ids[0])).work["title"] == "Valid duplicate"
    assert (
        await commit_import_batch(db, actor, workspace_id, preview.id)
    ).committed_item_ids == ids


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
    ids = (await commit_import_batch(db, actor, workspace_id, preview.id)).committed_item_ids
    assert len(ids) == 1
    assert (await db.get(Item, ids[0])).work["title"] == "Valid"
    assert (
        await commit_import_batch(db, actor, workspace_id, preview.id)
    ).committed_item_ids == ids


async def test_ris_conversion_losses_are_diagnosed_before_staging(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    content = b"TY  - JOUR\nT1  - State-of-the-art\nDO  - 10.1000/foo-bar\nER  - \nTY  - JOUR\nTI  - Valid alias title\nDO  - 10.1000/valid\nER  - "
    preview = await stage_import_batch(db, actor, workspace_id, content, "ris")
    assert len(preview.records) == 1
    assert preview.records[0].metadata.title == "Valid alias title"
    assert any(error.row == 1 and error.code == "invalid_record" for error in preview.errors)
    ids = (await commit_import_batch(db, actor, workspace_id, preview.id)).committed_item_ids
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
    assert item_summary(item)["authors"] == [
        {"full_name": "Research Council", "last_name": "Research Council", "first_name": None}
    ]
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


async def test_summary_author_credits_round_trip_exact_library_filters(persistence_db):
    from quirebase.library import item_summary
    from quirebase.web.api.library_schemas import item_search_view

    db = persistence_db
    actor, workspace_id = await owner(db)
    credits = [
        {
            "type": "Person",
            "person": {
                "name": "Credited display",
                "family_name": " Smith; & 一 ",
                "given_name": " Jane ",
            },
            "roles": ["Author"],
        },
        {
            "type": "Organization",
            "organization": {"name": " Council; & 50%_+ "},
            "person": {"family_name": "Inactive"},
            "roles": ["Author"],
        },
        {"type": "Person", "person": {"name": "Single; Name"}, "roles": ["Author"]},
        {"type": "Person", "person": {"given_name": "Ada"}, "roles": ["Author"]},
        {"type": "Person", "person": {"family_name": "Family"}, "roles": ["Author", "Editor"]},
        {"type": "Person", "person": {"name": "Editor only"}, "roles": ["Editor"]},
        {
            "type": "Person",
            "person": {"id": "https://orcid.org/0000-0002-1825-0097"},
            "roles": ["Author"],
        },
    ]
    created = await create_item(db, actor, workspace_id, work(contributors=credits))
    item = await db.get(Item, created.item_id)
    authors = item_summary(item)["authors"]
    assert authors == [
        {"full_name": "Credited display", "last_name": " Smith; & 一 ", "first_name": " Jane "},
        {"full_name": " Council; & 50%_+ ", "last_name": " Council; & 50%_+ ", "first_name": None},
        {"full_name": "Single; Name", "last_name": "Single; Name", "first_name": None},
        {"full_name": "Ada", "last_name": "Ada", "first_name": None},
        {"full_name": "Family", "last_name": "Family", "first_name": None},
    ]
    assert item_search_view(item).model_dump()["authors"] == authors
    for author in authors:
        matches, total = await search_library(
            db,
            actor,
            workspace_id,
            author_last_name=author["last_name"],
            author_first_name=author["first_name"] or "",
        )
        assert total == 1 and [row.id for row in matches] == [created.item_id]
    empty = await create_item(db, actor, workspace_id, work())
    assert item_summary(await db.get(Item, empty.item_id))["authors"] == []


@pytest.mark.parametrize("source", ["bibliography", "identifier", "pdf"])
async def test_import_previews_do_not_read_stored_items(persistence_db, monkeypatch, source):
    from unittest.mock import AsyncMock

    from inquiro import CandidateRecord, Identifier

    from quirebase.core.config import get_settings
    from quirebase.library.imports import (
        check_pdf_import_eligibility,
        stage_identifiers_import_batch,
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
            preview = await stage_identifiers_import_batch(
                db, actor, workspace_id, ["10.1234/shared"], settings=get_settings()
            )
            assert len(preview.records) == 1 and not preview.errors
        else:
            assert await check_pdf_import_eligibility(
                db, batch.id, {"_pdf": {"object_key": "candidate.pdf"}}
            ) == {"eligible": True, "object_key": "candidate.pdf"}
        assert reads == []
    finally:
        event.remove(db.sync_session, "do_orm_execute", record_query)
