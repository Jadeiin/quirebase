from __future__ import annotations

from uuid import uuid4

import pytest
from workspace_helpers import provision_initial_workspace

from quirebase.core.errors import ResourceUnavailable
from quirebase.library import (
    BulkItemAction,
    LibraryFilter,
    apply_bulk_item_action,
    create_item,
    get_library_facets,
    search_authors_typeahead,
    search_library,
)
from quirebase.models import (
    ProjectItem,
    ProjectParticipation,
    ProjectState,
    User,
    WorkspaceMember,
    WorkspaceRole,
)
from quirebase.projects import (
    add_project_participant,
    create_project,
    remove_project_participant,
    set_project_state,
)

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


async def _project_library(db):
    owner = User(username=f"project-library-owner-{uuid4()}", password_hash="unused")
    editor = User(username=f"project-library-editor-{uuid4()}", password_hash="unused")
    db.add_all([owner, editor])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=editor.id, role=WorkspaceRole.editor))
    await db.commit()
    project = await create_project(
        db, owner, workspace.id, "Review working set", ProjectParticipation.managed
    )
    await add_project_participant(db, owner, workspace.id, project.id, editor.username)
    records = []
    for title, author, year, publication in [
        ("Project alpha", "Smith", "2024", "Journal A"),
        ("Project beta", "Zhao", "2025", "Journal B"),
        ("Project gamma", "Adams", "2025", "Journal A"),
        ("Project outside", "Alien", "2025", "Journal A"),
    ]:
        result = await create_item(
            db,
            owner,
            workspace.id,
            {
                "id": f"urn:uuid:{uuid4()}",
                "type": "JournalArticle",
                "title": title,
                "date_published": year,
                "container": {"title": publication},
                "contributors": [
                    {"type": "Person", "person": {"family_name": author}, "roles": ["Author"]}
                ],
                "subjects": [{"subject": author}],
            },
        )
        records.append(result.item_id)
    db.add_all([
        ProjectItem(
            workspace_id=workspace.id,
            project_id=project.id,
            item_id=item_id,
            added_by=owner.id,
        )
        for item_id in records[:3]
    ])
    await db.commit()
    return owner, editor, workspace, project, records


@pytest.mark.parametrize("state", list(ProjectState))
async def test_project_library_combines_scope_filters_sorting_and_read_models(
    persistence_db, state
):
    db = persistence_db
    owner, editor, workspace, project, ids = await _project_library(db)
    if state is ProjectState.archived:
        await set_project_state(db, owner, workspace.id, project.id, state)

    # The same Library search stays within the Project before ordering and pagination.
    for offset, expected in enumerate([ids[2], ids[1]]):
        rows, total = await search_library(
            db,
            editor,
            workspace.id,
            LibraryFilter(q="Project", project=project.id, year="2025"),
            sort="title",
            direction="desc",
            limit=1,
            offset=offset,
        )
        assert total == 2
        assert [row.id for row in rows] == [expected]
    rows, total = await search_library(
        db, editor, workspace.id, LibraryFilter(project=project.id), sort="author", direction="asc"
    )
    assert total == 3
    assert [row.id for row in rows] == [ids[2], ids[0], ids[1]]
    rows, total = await search_library(
        db, editor, workspace.id, LibraryFilter(project=project.id, publication_title="Journal A")
    )
    assert total == 2
    assert {row.id for row in rows} == {ids[0], ids[2]}

    facets = await get_library_facets(
        db, editor, workspace.id, LibraryFilter(project=project.id, year="2025")
    )
    assert [(row.last_name, row.item_count) for row in facets.authors] == [
        ("Adams", 1),
        ("Zhao", 1),
    ]
    assert [(row.value, row.item_count) for row in facets.keywords] == [("Adams", 1), ("Zhao", 1)]
    assert [(row.value, row.item_count) for row in facets.reference_types] == [
        ("JournalArticle", 2)
    ]
    assert await search_authors_typeahead(db, editor, workspace.id, "A", project=project.id) == [
        {"last_name": "Adams", "first_name": None, "full_name": "Adams"}
    ]


async def test_project_library_reads_recheck_participation_without_revoking_canonical_items(
    persistence_db,
):
    db = persistence_db
    owner, editor, workspace, project, ids = await _project_library(db)
    assert (await search_library(db, editor, workspace.id, LibraryFilter(project=project.id)))[
        1
    ] == 3
    assert (
        await get_library_facets(db, editor, workspace.id, LibraryFilter(project=project.id))
    ).authors
    assert await search_authors_typeahead(db, editor, workspace.id, "A", project=project.id)

    await remove_project_participant(db, owner, workspace.id, project.id, editor.id)

    with pytest.raises(ResourceUnavailable):
        await search_library(db, editor, workspace.id, LibraryFilter(project=project.id))
    with pytest.raises(ResourceUnavailable):
        await get_library_facets(db, editor, workspace.id, LibraryFilter(project=project.id))
    for query in ("A", ""):
        with pytest.raises(ResourceUnavailable):
            await search_authors_typeahead(db, editor, workspace.id, query, project=project.id)

    rows, total = await search_library(db, editor, workspace.id)
    assert total == 4
    assert {row.id for row in rows} == set(ids)
    await apply_bulk_item_action(
        db, editor, workspace.id, ids[:2], BulkItemAction.add_tag, tag_name="Still accessible"
    )
