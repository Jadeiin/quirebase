from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from item_helpers import contributor
from workspace_helpers import provision_initial_workspace

from quirebase.core.errors import (
    ResourceUnavailable,
    ValidationFailure,
    WorkspaceMembershipRequired,
)
from quirebase.library import (
    AuthorFilter,
    LibraryFilter,
    create_item,
    get_library_facets,
    search_authors_typeahead,
    search_library,
)
from quirebase.models import Item, Project, ProjectItem, User, WorkspaceMember

pytestmark = pytest.mark.anyio


async def _library(db):
    owner = User(username="facet-owner", password_hash="unused")
    other = User(username="facet-other", password_hash="unused")
    db.add_all([owner, other])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    foreign_workspace = await provision_initial_workspace(db, other)
    await db.commit()
    ids = []
    for metadata in (
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "JournalArticle",
            "title": "Spectral graph",
            "date_published": "2025",
            "contributors": (contributor("Smith", "John"), contributor("Research; Council")),
            "subjects": [{"subject": v} for v in ("Graph; theory", "Robotics", "Robotics")],
        },
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "JournalArticle",
            "title": "Graph methods",
            "date_published": "2026",
            "contributors": (contributor("Smith", "John"), contributor("Wang", "Wei")),
            "subjects": [{"subject": v} for v in ("Robotics",)],
        },
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "Book",
            "title": "Unrelated book",
            "date_published": "2026",
            "contributors": (contributor("Smith", "Jane"),),
            "subjects": [{"subject": v} for v in ("Biology",)],
        },
        {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Empty metadata"},
    ):
        result = await create_item(db, owner, workspace.id, metadata)
        ids.append(result.item_id)
    await create_item(
        db,
        other,
        foreign_workspace.id,
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Graph secret",
            "contributors": (contributor("Secret"),),
            "subjects": [{"subject": v} for v in ("Secret",)],
        },
    )
    project = Project(workspace_id=workspace.id, name="Working set", created_by=owner.id)
    db.add(project)
    await db.flush()
    db.add_all([
        ProjectItem(
            workspace_id=workspace.id, project_id=project.id, item_id=item_id, added_by=owner.id
        )
        for item_id in ids[:2]
    ])
    await db.commit()
    return (owner, other, workspace.id, foreign_workspace.id, ids, project.id)


async def test_facets_count_distinct_items_and_retain_multivalued_terms(persistence_db):
    owner, _, workspace_id, _, ids, project_id = await _library(persistence_db)
    facets = await get_library_facets(persistence_db, owner, workspace_id)
    assert [(row.last_name, row.first_name, row.item_count) for row in facets.authors] == [
        ("Smith", "John", 2),
        ("Research; Council", None, 1),
        ("Smith", "Jane", 1),
        ("Wang", "Wei", 1),
    ]
    assert [(row.value, row.item_count) for row in facets.keywords] == [
        ("Robotics", 2),
        ("Biology", 1),
        ("Graph; theory", 1),
    ]
    assert {row.value: row.item_count for row in facets.reference_types} == {
        "JournalArticle": 2,
        "Book": 1,
        "Document": 1,
    }
    assert sum(row.item_count for row in facets.authors) > len(ids)
    narrowed = await get_library_facets(
        persistence_db,
        owner,
        workspace_id,
        LibraryFilter(project=project_id, q="graph", year="2025", keyword_exact="Robotics"),
    )
    assert [(row.last_name, row.item_count) for row in narrowed.authors] == [
        ("Research; Council", 1),
        ("Smith", 1),
    ]
    assert [(row.value, row.item_count) for row in narrowed.reference_types] == [
        ("JournalArticle", 1)
    ]
    limited = await get_library_facets(persistence_db, owner, workspace_id, limit=1)
    assert sum(row.item_count for row in limited.reference_types) == 1
    empty = await get_library_facets(
        persistence_db, owner, workspace_id, LibraryFilter(q="missingterm")
    )
    assert empty.authors == empty.keywords == empty.reference_types == ()


@pytest.mark.parametrize(
    "credit",
    [
        {
            "type": "Person",
            "person": {"family_name": "Smith ", "given_name": " Jane  Ann\t"},
            "roles": ["Author"],
        },
        {
            "type": "Person",
            "person": {"family_name": "Smith ", "given_name": ""},
            "roles": ["Author"],
        },
        {"type": "Person", "person": {"name": " Ada  Lovelace "}, "roles": ["Author"]},
        {"type": "Person", "person": {"given_name": " Ada  Lovelace "}, "roles": ["Author"]},
        {
            "type": "Organization",
            "organization": {"name": " Research   Council "},
            "roles": ["Author"],
        },
    ],
)
@pytest.mark.parametrize("keyword", [" topic ", " topic\t term ", " \t "])
async def test_exact_filters_select_the_preserved_author_and_keyword_facet_values(
    persistence_db, credit, keyword
):
    db = persistence_db
    owner = User(username=f"facet-owner-{uuid4()}", password_hash="unused")
    db.add(owner)
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    await db.commit()
    entity = credit["type"].lower()
    stripped = credit | {
        entity: {name: " ".join(value.split()) for name, value in credit[entity].items()}
    }
    for author, subject in ((credit, keyword), (stripped, keyword.strip() or "topic")):
        metadata = {
            "id": f"urn:uuid:{uuid4()}",
            "type": "JournalArticle",
            "title": "Research",
            "contributors": [author],
            "subjects": [{"subject": subject}],
        }
        result = await create_item(db, owner, workspace.id, metadata)
        assert (await db.get(Item, result.item_id)).work == metadata
    facets = await get_library_facets(db, owner, workspace.id)
    assert len(facets.authors) == len(facets.keywords) == 2
    for facet in facets.authors:
        filters = {
            "authors": (
                AuthorFilter(
                    facet.last_name, facet.first_name if facet.first_name is not None else ""
                ),
            )
        }
        _, total = await search_library(db, owner, workspace.id, LibraryFilter(**filters))
        assert total == facet.item_count == 1
        narrowed = await get_library_facets(db, owner, workspace.id, LibraryFilter(**filters))
        assert narrowed.authors == (facet,)
    for facet in facets.keywords:
        _, total = await search_library(
            db, owner, workspace.id, LibraryFilter(keyword_exact=facet.value)
        )
        assert total == facet.item_count == 1
        narrowed = await get_library_facets(
            db, owner, workspace.id, LibraryFilter(keyword_exact=facet.value)
        )
        assert narrowed.keywords == (facet,)


@pytest.mark.parametrize(
    "filters, indexes",
    [
        ({"author": "sMiTh, jOhN"}, [0, 1]),
        ({"authors": (AuthorFilter("Smith", "John"), AuthorFilter("Smith", "Jane"))}, []),
        ({"authors": (AuthorFilter("Smith", "John"), AuthorFilter("Wang", "Wei"))}, [1]),
        ({"authors": (AuthorFilter("Smith", "John"), AuthorFilter("Research; Council", ""))}, [0]),
        ({"authors": (AuthorFilter("Smith"), AuthorFilter("Smith", "John"))}, [0, 1]),
        (
            {
                "authors": (AuthorFilter("Smith", "John"), AuthorFilter("Wang", "Wei")),
                "year": "2025",
            },
            [],
        ),
        ({"authors": (AuthorFilter("Smith", "John"), AuthorFilter("Smith", "John"))}, [0, 1]),
        ({"authors": (AuthorFilter("Smith", "Wei"), AuthorFilter("Wang", "John"))}, []),
        (
            {
                "authors": (AuthorFilter("Research; Council", ""), AuthorFilter("Smith", "Jane")),
                "year": "2026",
            },
            [],
        ),
        ({"author": "Research; Council"}, [0]),
        ({"authors": (AuthorFilter("Smith", "John"),)}, [0, 1]),
        ({"authors": (AuthorFilter("Smith", "Jane"),)}, [2]),
        ({"authors": (AuthorFilter("Smith"),)}, [0, 1, 2]),
        ({"authors": (AuthorFilter("Smith", "Wei"),)}, []),
        pytest.param(
            {"author": "John", "authors": (AuthorFilter("Wang", "Wei"),)},
            [],
            id="combined-author-cross-credits",
        ),
        pytest.param(
            {"author": "Wei", "authors": (AuthorFilter("Wang", "Wei"),)},
            [1],
            id="combined-author-same-credit",
        ),
        pytest.param(
            {"author": "JOHN", "authors": (AuthorFilter("Smith", "John"),)},
            [0, 1],
            id="combined-author-case-insensitive-text",
        ),
        pytest.param(
            {"author": "%", "authors": (AuthorFilter("Smith", "John"),)},
            [],
            id="combined-author-literal-wildcard",
        ),
        ({"authors": (AuthorFilter("Research; Council", ""),)}, [0]),
        ({"authors": (AuthorFilter("Smith", ""),)}, []),
        ({"authors": (AuthorFilter("smith"),)}, []),
        ({"keyword": "graph;"}, [0]),
        ({"keyword_exact": "Graph; theory"}, [0]),
        ({"keyword_exact": "Graph"}, []),
        ({"keyword": "%"}, []),
        ({"author": "_"}, []),
        ({"reference_type": "Book"}, [2]),
        ({"has_files": False, "keyword_exact": "Robotics"}, [0, 1]),
    ],
)
async def test_json_filters_match_elements_and_share_facet_candidates(
    persistence_db, filters, indexes
):
    owner, _, workspace_id, _, ids, _ = await _library(persistence_db)
    items, total = await search_library(
        persistence_db, owner, workspace_id, LibraryFilter(**filters)
    )
    facets = await get_library_facets(persistence_db, owner, workspace_id, LibraryFilter(**filters))
    assert total == len(indexes)
    assert {item.id for item in items} == {ids[index] for index in indexes}
    assert sum(row.item_count for row in facets.reference_types) == total


async def test_facets_and_suggestions_obey_workspace_and_project_discovery(persistence_db):
    db = persistence_db
    owner, other, workspace_id, foreign_id, _, project_id = await _library(db)
    with pytest.raises(WorkspaceMembershipRequired):
        await get_library_facets(db, owner, foreign_id)
    with pytest.raises(ResourceUnavailable):
        await get_library_facets(db, other, foreign_id, LibraryFilter(project=project_id))
    db.add(
        WorkspaceMember(
            workspace_id=workspace_id, user_id=other.id, role="viewer", invited_by=owner.id
        )
    )
    managed = Project(
        workspace_id=workspace_id, name="Managed", participation="managed", created_by=owner.id
    )
    db.add(managed)
    await db.commit()
    with pytest.raises(ResourceUnavailable):
        await get_library_facets(db, other, workspace_id, LibraryFilter(project=managed.id))
    with pytest.raises(ResourceUnavailable):
        await search_authors_typeahead(db, other, workspace_id, "S", project=managed.id)
    suggestions = await search_authors_typeahead(
        db, owner, workspace_id, "Smith", project=project_id
    )
    assert suggestions == [{"last_name": "Smith", "first_name": "John", "full_name": "John Smith"}]


async def test_facets_follow_the_same_result_page_for_every_sort(persistence_db):
    from quirebase.library import item_summary

    db = persistence_db
    owner, _, workspace_id, _, ids, _ = await _library(db)
    for item_id in ids[:2]:
        item = await db.get(Item, item_id)
        item.work = {
            **item.work,
            "title": "Same title",
            "container": {"title": "Same publication"},
        }
        item.created_at = datetime(2025, 1, 1, tzinfo=UTC)
        item.updated_at = datetime(2025, 1, 2, tzinfo=UTC)
    await db.commit()
    for sort in ["title", "author", "publication", "published", "created", "updated"]:
        for direction in [None, "asc", "desc"]:
            for limit, offset in [(2, 0), (2, 2), (3, 1), (1, 3), (2, 50)]:
                rows, total = await search_library(
                    db,
                    owner,
                    workspace_id,
                    limit=limit,
                    offset=offset,
                    sort=sort,
                    direction=direction,
                )
                assert total == 4
                facets = await get_library_facets(
                    db,
                    owner,
                    workspace_id,
                    limit=limit,
                    offset=offset,
                    sort=sort,
                    direction=direction,
                )
                authors = Counter()
                keywords = Counter()
                for item in rows:
                    authors.update({
                        (author["last_name"], author["first_name"])
                        for author in item_summary(item)["authors"]
                    })
                    keywords.update({
                        subject["subject"] for subject in item.work.get("subjects", [])
                    })
                assert {
                    (row.last_name, row.first_name): row.item_count for row in facets.authors
                } == dict(authors)
                assert {row.value: row.item_count for row in facets.keywords} == dict(keywords)
                assert {row.value: row.item_count for row in facets.reference_types} == dict(
                    Counter(item.work["type"] for item in rows)
                )
    for parameters in [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"sort": "unknown"},
        {"direction": "unknown"},
    ]:
        with pytest.raises(ValidationFailure):
            await get_library_facets(db, owner, workspace_id, **parameters)


async def test_facets_return_all_values_in_the_item_page_without_top_fifty_cutoff(persistence_db):
    db = persistence_db
    owner, _, workspace_id, _, _, _ = await _library(db)
    credits = [contributor(f"Rare {index:03}") for index in range(73)]
    subjects = [{"subject": f"Keyword {index:03}"} for index in range(73)]
    await create_item(
        db,
        owner,
        workspace_id,
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Many choices",
            "contributors": [*credits, credits[-1]],
            "subjects": [*subjects, subjects[-1]],
        },
    )
    await create_item(
        db,
        owner,
        workspace_id,
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "Book",
            "title": "Many other",
            "contributors": [contributor("Other page")],
            "subjects": [{"subject": "Other"}],
        },
    )
    facets = await get_library_facets(
        db, owner, workspace_id, LibraryFilter(q="Many"), limit=1, sort="title"
    )
    assert len(facets.authors) == len(facets.keywords) == 73
    assert (facets.authors[-1].last_name, facets.authors[-1].item_count) == ("Rare 072", 1)
    assert (facets.keywords[-1].value, facets.keywords[-1].item_count) == ("Keyword 072", 1)
    second = await get_library_facets(
        db, owner, workspace_id, LibraryFilter(q="Many"), limit=1, offset=1, sort="title"
    )
    assert [(row.last_name, row.item_count) for row in second.authors] == [("Other page", 1)]
    assert [(row.value, row.item_count) for row in second.keywords] == [("Other", 1)]
    assert [(row.value, row.item_count) for row in second.reference_types] == [("Book", 1)]


async def test_author_facets_and_suggestions_display_record_names_without_reidentifying_them(
    persistence_db,
):
    from quirebase.library import item_summary

    db = persistence_db
    owner, _, workspace_id, _, _, _ = await _library(db)
    credits = [
        {
            "type": "Person",
            "person": {"name": " 王伟 ", "family_name": "Wang", "given_name": " Wei "},
            "roles": ["Author"],
        },
        {
            "type": "Organization",
            "organization": {"name": " Research Council "},
            "person": {"name": "Inactive Person"},
            "roles": ["Author"],
        },
        {"type": "Person", "person": {"given_name": " Ada "}, "roles": ["Author"]},
        {
            "type": "Person",
            "person": {"name": " \t ", "family_name": "Smith ", "given_name": " Jane "},
            "roles": ["Author"],
        },
        {
            "type": "Person",
            "person": {"name": "John Smith Jr.", "family_name": "Smith", "given_name": "John"},
            "roles": ["Author"],
        },
        {
            "type": "Person",
            "person": {"name": "John Smith Sr.", "family_name": "Smith", "given_name": "John"},
            "roles": ["Author"],
        },
        {"type": "Person", "person": {"name": "\t\u3000"}, "roles": ["Author"]},
        {
            "type": "Person",
            "person": {"family_name": "\t", "given_name": "\u3000"},
            "roles": ["Author"],
        },
        {
            "type": "Organization",
            "organization": {"name": " \n "},
            "roles": ["Author"],
        },
        {
            "type": "Person",
            "person": {"name": "Different A", "family_name": "\t", "given_name": "\u3000"},
            "roles": ["Author"],
        },
        {
            "type": "Person",
            "person": {"name": "Different B", "family_name": "\t", "given_name": "\u3000"},
            "roles": ["Author"],
        },
        {
            "type": "Person",
            "person": {"name": "Visible Name", "family_name": "\n"},
            "roles": ["Author"],
        },
        {
            "type": "Person",
            "person": {"name": " \t ", "family_name": "\n"},
            "roles": ["Author"],
        },
    ]
    for index, credit in enumerate(credits):
        created = await create_item(
            db,
            owner,
            workspace_id,
            {
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": f"Name projections {index}",
                "contributors": [credit],
            },
        )
        item = await db.get(Item, created.item_id)
        assert item.work["contributors"] == [credit]
        if index == 3:
            assert item_summary(item)["authors"] == [
                {"full_name": "Jane Smith", "last_name": "Smith ", "first_name": " Jane "}
            ]
        if 6 <= index < 9:
            assert item_summary(item)["authors"] == []
    facets = await get_library_facets(db, owner, workspace_id, LibraryFilter(q="projections"))
    names = {
        (row.last_name, row.first_name): (row.full_name, row.item_count) for row in facets.authors
    }
    assert names == {
        ("Wang", " Wei "): ("王伟", 1),
        (" Research Council ", None): ("Research Council", 1),
        (" Ada ", None): ("Ada", 1),
        ("Smith ", " Jane "): ("Jane Smith", 1),
        ("Smith", "John"): ("John Smith", 2),
        ("\n", None): ("Visible Name", 2),
    }
    for choice in facets.authors:
        _, total = await search_library(
            db,
            owner,
            workspace_id,
            LibraryFilter(
                q="projections", authors=(AuthorFilter(choice.last_name, choice.first_name or ""),)
            ),
        )
        assert total == choice.item_count
    assert await search_authors_typeahead(db, owner, workspace_id, "王") == [
        {"last_name": "Wang", "first_name": " Wei ", "full_name": "王伟"}
    ]
    john = await search_authors_typeahead(db, owner, workspace_id, "John")
    assert john == [{"last_name": "Smith", "first_name": "John", "full_name": "John Smith"}]
    assert await search_authors_typeahead(db, owner, workspace_id, "Visible") == [
        {"last_name": "\n", "first_name": None, "full_name": "Visible Name"}
    ]


async def test_facet_endpoint_uses_the_item_paging_sorting_and_validation_contract(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from app_helpers import authenticated_async_client

    from quirebase.core.config import get_settings

    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await async_db.get(User, item.created_by)
    await create_item(
        async_db,
        owner,
        item.workspace_id,
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Zeta",
            "contributors": [contributor("Second")],
        },
    )
    path = f"/api/v1/workspaces/{item.workspace_id}/items"
    try:
        response = await client.get(
            f"{path}/facets", params={"sort": "title", "direction": "asc", "limit": 1, "offset": 1}
        )
        assert response.status_code == 200
        assert response.json()["authors"] == [
            {"last_name": "Second", "first_name": None, "full_name": "Second", "item_count": 1}
        ]
        empty = await client.get(f"{path}/facets", params={"offset": 20})
        assert empty.json() == {"authors": [], "keywords": [], "reference_types": []}
        for parameters in [
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
            {"sort": "unknown"},
            {"direction": "unknown"},
        ]:
            assert (await client.get(f"{path}/facets", params=parameters)).status_code == 422
            assert (await client.get(path, params=parameters)).status_code == 422
    finally:
        await client.aclose()
        get_settings.cache_clear()


async def test_author_choices_follow_the_selected_result_page(
    persistence_db,
):
    db = persistence_db
    owner, _, workspace_id, _, ids, _ = await _library(db)
    filters = LibraryFilter(year="2026", authors=(AuthorFilter("Smith", "Jane"),))
    rows, total = await search_library(db, owner, workspace_id, filters, sort="title", limit=1)
    assert total == 1 and [row.id for row in rows] == [ids[2]]
    facets = await get_library_facets(db, owner, workspace_id, filters, sort="title", limit=1)
    assert [(row.last_name, row.first_name, row.item_count) for row in facets.authors] == [
        ("Smith", "Jane", 1),
    ]
    assert [(row.value, row.item_count) for row in facets.keywords] == [("Biology", 1)]
    assert [(row.value, row.item_count) for row in facets.reference_types] == [("Book", 1)]


async def test_all_selected_authors_are_required_before_paging_without_duplicate_items(
    persistence_db,
):
    db = persistence_db
    owner, other, workspace_id, foreign_id, ids, _ = await _library(db)
    john, wei = contributor("Smith", "John"), contributor("Wang", "Wei")
    joint = await create_item(
        db,
        owner,
        workspace_id,
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "JournalArticle",
            "title": "Another joint study",
            "contributors": [john, wei, john],
        },
    )
    for actor, scope, credits in (
        (owner, workspace_id, [john, {**wei, "roles": ["Editor"]}]),
        (other, foreign_id, [john, wei]),
    ):
        await create_item(
            db,
            actor,
            scope,
            {
                "id": f"urn:uuid:{uuid4()}",
                "type": "JournalArticle",
                "title": "Excluded study",
                "contributors": credits,
            },
        )
    filters = LibraryFilter(authors=(AuthorFilter("Smith", "John"), AuthorFilter("Wang", "Wei")))
    pages = []
    for offset in (0, 1):
        rows, total = await search_library(
            db, owner, workspace_id, filters, sort="title", limit=1, offset=offset
        )
        assert total == 2 and len(rows) == 1
        pages.append(rows[0].id)
        facets = await get_library_facets(
            db, owner, workspace_id, filters, sort="title", limit=1, offset=offset
        )
        assert [(row.last_name, row.first_name, row.item_count) for row in facets.authors] == [
            ("Smith", "John", 1),
            ("Wang", "Wei", 1),
        ]
    assert pages == [joint.item_id, ids[1]]
