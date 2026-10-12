from __future__ import annotations

import pytest
from item_helpers import contributor
from workspace_helpers import provision_initial_workspace

from quirebase.core.errors import ResourceUnavailable, WorkspaceMembershipRequired
from quirebase.library import (
    ItemMetadata,
    LibraryFilter,
    create_item,
    get_library_facets,
    search_authors_typeahead,
    search_library,
)
from quirebase.models import Project, ProjectItem, ReferenceType, User, WorkspaceMember

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
        ItemMetadata(
            "Spectral graph",
            authors=(contributor("Smith", "John"), contributor("Research; Council")),
            keywords=("Graph; theory", "Robotics", "Robotics"),
            publication_date="2025",
            reference_type=ReferenceType.article_journal,
        ),
        ItemMetadata(
            "Graph methods",
            authors=(contributor("Smith", "John"), contributor("Wang", "Wei")),
            keywords=("Robotics",),
            publication_date="2026",
            reference_type=ReferenceType.article_journal,
        ),
        ItemMetadata(
            "Unrelated book",
            authors=(contributor("Smith", "Jane"),),
            keywords=("Biology",),
            publication_date="2026",
            reference_type=ReferenceType.book,
        ),
        ItemMetadata("Empty metadata"),
    ):
        result = await create_item(db, owner, workspace.id, metadata)
        ids.append(result.item_id)
    await create_item(
        db,
        other,
        foreign_workspace.id,
        ItemMetadata("Graph secret", authors=(contributor("Secret"),), keywords=("Secret",)),
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
    return owner, other, workspace.id, foreign_workspace.id, ids, project.id


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
        ReferenceType.article_journal: 2,
        ReferenceType.book: 1,
        ReferenceType.document: 1,
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
        (ReferenceType.article_journal, 1)
    ]
    limited = await get_library_facets(persistence_db, owner, workspace_id, limit=1)
    assert len(limited.authors) == len(limited.keywords) == len(limited.reference_types) == 1
    empty = await get_library_facets(
        persistence_db, owner, workspace_id, LibraryFilter(q="missingterm")
    )
    assert empty.authors == empty.keywords == empty.reference_types == ()


@pytest.mark.parametrize(
    "filters, indexes",
    [
        ({"author": "sMiTh, jOhN"}, [0, 1]),
        ({"author": "Research; Council"}, [0]),
        ({"author_last_name": "Smith", "author_first_name": "John"}, [0, 1]),
        ({"author_last_name": "Smith", "author_first_name": "Jane"}, [2]),
        ({"author_last_name": "Smith"}, [0, 1, 2]),
        ({"author_last_name": "Smith", "author_first_name": "Wei"}, []),
        pytest.param(
            {"author": "John", "author_last_name": "Wang", "author_first_name": "Wei"},
            [],
            id="combined-author-cross-credits",
        ),
        pytest.param(
            {"author": "Wei", "author_last_name": "Wang", "author_first_name": "Wei"},
            [1],
            id="combined-author-same-credit",
        ),
        pytest.param(
            {"author": "JOHN", "author_last_name": "Smith", "author_first_name": "John"},
            [0, 1],
            id="combined-author-case-insensitive-text",
        ),
        pytest.param(
            {"author": "%", "author_last_name": "Smith", "author_first_name": "John"},
            [],
            id="combined-author-literal-wildcard",
        ),
        ({"author_last_name": "Research; Council", "author_first_name": ""}, [0]),
        ({"author_last_name": "Smith", "author_first_name": ""}, []),
        ({"author_last_name": "smith"}, []),
        ({"keyword": "graph;"}, [0]),
        ({"keyword_exact": "Graph; theory"}, [0]),
        ({"keyword_exact": "Graph"}, []),
        ({"keyword": "%"}, []),
        ({"author": "_"}, []),
        ({"reference_type": ReferenceType.book}, [2]),
        ({"has_files": False, "keyword_exact": "Robotics"}, [0, 1]),
    ],
)
async def test_json_filters_match_elements_and_share_facet_candidates(
    persistence_db, filters, indexes
):
    owner, _, workspace_id, _, ids, _ = await _library(persistence_db)
    items, total = await search_library(persistence_db, owner, workspace_id, **filters)
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
    assert suggestions == [
        {"last_name": "Smith", "first_name": "John", "suffix": None, "full_name": "Smith, John"}
    ]
