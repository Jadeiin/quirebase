from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from advanced_alchemy.types import FileObject
from item_helpers import contributor
from test_http import authenticated_async_client
from workspace_helpers import fixture_membership_id, provision_initial_workspace

from quirebase.core.errors import ResourceUnavailable, WorkspaceMembershipRequired
from quirebase.library import LibraryFilter, create_item, get_library_facets, search_library
from quirebase.models import (
    Attachment,
    FileRevision,
    ImportBatch,
    ItemTag,
    Project,
    ProjectItem,
    ProjectParticipant,
    Tag,
    User,
    WorkspaceMember,
)

pytestmark = pytest.mark.anyio


def _work(title: str) -> dict:
    return {
        "id": f"urn:uuid:{uuid4()}",
        "type": "JournalArticle",
        "title": f"{title} study",
        "date_published": "2026",
        "container": {"title": "Organization journal"},
        "contributors": [contributor("Research", title)],
        "subjects": [{"subject": "Organization"}, {"subject": title}],
    }


@dataclass(frozen=True)
class OrganizationLibrary:
    users: dict[str, User]
    workspace_id: UUID
    foreign_workspace_id: UUID
    items: dict[str, UUID]
    tags: tuple[UUID, ...]
    projects: dict[str, UUID]
    receipt_id: UUID


async def _library(db) -> OrganizationLibrary:
    users = {
        role: User(username=f"organization-{role}", password_hash="unused")
        for role in ("owner", "admin", "viewer", "outsider")
    }
    db.add_all(users.values())
    await db.flush()
    owner = users["owner"]
    workspace = await provision_initial_workspace(db, owner)
    foreign = await provision_initial_workspace(db, users["outsider"])
    db.add_all([
        WorkspaceMember(workspace_id=workspace.id, user_id=users[role].id, role=role)
        for role in ("admin", "viewer")
    ])
    await db.commit()
    items = {}
    for name in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"):
        result = await create_item(db, owner, workspace.id, _work(name))
        items[name] = result.item_id
    foreign_item = await create_item(db, users["outsider"], foreign.id, _work("Foreign"))
    tags = [
        Tag(workspace_id=workspace.id, name=name, created_by=owner.id)
        for name in ("Reading", "Reference")
    ]
    foreign_tag = Tag(workspace_id=foreign.id, name="Reading", created_by=users["outsider"].id)
    projects = {
        name: Project(
            workspace_id=workspace.id,
            name=name,
            participation=participation,
            state=state,
            created_by=owner.id,
        )
        for name, participation, state in (
            ("Open", "open", "active"),
            ("Workspace", "workspace", "active"),
            ("Hidden", "managed", "active"),
            ("Archived", "open", "archived"),
            ("Participating", "managed", "archived"),
        )
    }
    foreign_project = Project(
        workspace_id=foreign.id, name="Foreign", created_by=users["outsider"].id
    )
    db.add_all([*tags, foreign_tag, *projects.values(), foreign_project])
    await db.flush()
    db.add_all([
        ItemTag(workspace_id=workspace.id, item_id=items[name], tag_id=tag.id)
        for name, tag in (("Alpha", tags[0]), ("Alpha", tags[1]), ("Beta", tags[0]))
    ])
    db.add_all([
        ProjectItem(
            workspace_id=workspace.id,
            project_id=projects[project].id,
            item_id=items[name],
            added_by=owner.id,
        )
        for name, project in (
            ("Alpha", "Open"),
            ("Alpha", "Workspace"),
            ("Gamma", "Hidden"),
            ("Delta", "Archived"),
            ("Epsilon", "Participating"),
        )
    ])
    db.add(
        ProjectParticipant(
            workspace_id=workspace.id,
            project_id=projects["Participating"].id,
            user_id=users["viewer"].id,
            workspace_member_id=await fixture_membership_id(db, workspace.id, users["viewer"].id),
        )
    )
    db.add_all([
        ItemTag(workspace_id=foreign.id, item_id=foreign_item.item_id, tag_id=foreign_tag.id),
        ProjectItem(
            workspace_id=foreign.id,
            project_id=foreign_project.id,
            item_id=foreign_item.item_id,
            added_by=users["outsider"].id,
        ),
    ])
    for model, name in ((FileRevision, "Alpha"), (Attachment, "Beta")):
        db.add(
            model(
                workspace_id=workspace.id,
                item_id=items[name],
                created_by=owner.id,
                file=FileObject(
                    backend="documents",
                    filename=f"objects/{uuid4()}.pdf",
                    size=1,
                    content_type="application/pdf",
                ),
            )
        )
    receipt = ImportBatch(
        workspace_id=workspace.id,
        actor_id=owner.id,
        file_format="commonmeta",
        records=[],
        errors=[],
        status="committed",
        committed_item_ids=[str(item_id) for name, item_id in items.items() if name != "Zeta"],
    )
    db.add(receipt)
    await db.commit()
    return OrganizationLibrary(
        users,
        workspace.id,
        foreign.id,
        items,
        tuple(tag.id for tag in tags),
        {name: project.id for name, project in projects.items()},
        receipt.id,
    )


@pytest.mark.parametrize("role", ["owner", "admin", "viewer"])
async def test_presence_filters_respect_workspace_and_project_discovery(persistence_db, role):
    db = persistence_db
    library = await _library(db)
    user = library.users[role]
    present = {
        "has_files": {"Alpha", "Beta"},
        "has_tags": {"Alpha", "Beta"},
        "has_projects": {"Alpha", "Delta", "Epsilon"} | ({"Gamma"} if role != "viewer" else set()),
    }
    for field, names in present.items():
        for value in (None, True, False):
            expected_names = (
                set(library.items)
                if value is None
                else names
                if value
                else set(library.items) - names
            )
            rows, total = await search_library(
                db, user, library.workspace_id, **{field: value}, sort="title"
            )
            assert total == len(expected_names)
            assert {row.id for row in rows} == {library.items[name] for name in expected_names}
            assert len(rows) == len({row.id for row in rows})
    for value in (True, False):
        with pytest.raises(WorkspaceMembershipRequired):
            await search_library(
                db, user, library.foreign_workspace_id, has_tags=value, has_projects=value
            )


async def test_presence_filters_intersect_receipts_metadata_and_specific_associations(
    persistence_db,
):
    db = persistence_db
    library = await _library(db)
    viewer = library.users["viewer"]
    filters = {
        "q": "study",
        "has_files": False,
        "has_tags": False,
        "has_projects": False,
        "import_batch": library.receipt_id,
        "year": "2026",
        "keyword_exact": "Organization",
        "author_last_name": "Research",
        "publication_title": "Organization journal",
        "reference_type": "JournalArticle",
    }
    rows, total = await search_library(db, viewer, library.workspace_id, **filters)
    assert total == 1 and [row.id for row in rows] == [library.items["Gamma"]]
    facets = await get_library_facets(db, viewer, library.workspace_id, LibraryFilter(**filters))
    assert [(row.first_name, row.item_count) for row in facets.authors] == [("Gamma", 1)]
    assert {row.value for row in facets.keywords} == {"Gamma", "Organization"}
    assert sum(row.item_count for row in facets.reference_types) == 1
    rows, total = await search_library(db, library.users["owner"], library.workspace_id, **filters)
    assert rows == [] and total == 0
    for specific, present in (
        ({"tag": library.tags[0]}, {"has_tags": False}),
        ({"project": library.projects["Open"]}, {"has_projects": False}),
    ):
        rows, total = await search_library(db, viewer, library.workspace_id, **specific, **present)
        assert rows == [] and total == 0
        facets = await get_library_facets(
            db, viewer, library.workspace_id, LibraryFilter(**specific, **present)
        )
        assert facets.authors == facets.keywords == facets.reference_types == ()
    with pytest.raises(ResourceUnavailable):
        await search_library(
            db,
            viewer,
            library.workspace_id,
            project=library.projects["Hidden"],
            has_projects=False,
        )


async def test_filtered_facets_follow_the_current_sorted_page(persistence_db):
    db = persistence_db
    library = await _library(db)
    viewer = library.users["viewer"]
    filters = LibraryFilter(has_tags=False, has_files=False)
    for direction, names in (
        ("asc", ["Delta", "Epsilon", "Gamma", "Zeta"]),
        ("desc", ["Zeta", "Gamma", "Epsilon", "Delta"]),
    ):
        for offset in (0, 1, 3, 4):
            rows, total = await search_library(
                db,
                viewer,
                library.workspace_id,
                has_tags=False,
                has_files=False,
                sort="title",
                direction=direction,
                limit=1,
                offset=offset,
            )
            expected = names[offset : offset + 1]
            assert total == 4
            assert [row.id for row in rows] == [library.items[name] for name in expected]
            facets = await get_library_facets(
                db,
                viewer,
                library.workspace_id,
                filters,
                sort="title",
                direction=direction,
                limit=1,
                offset=offset,
            )
            assert [row.first_name for row in facets.authors] == expected
            assert sum(row.item_count for row in facets.reference_types) == len(expected)


async def test_http_organization_filters_share_search_and_current_page_facets(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, original, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    user = await db.get(User, original.created_by)
    workspace_id = original.workspace_id
    ids = [
        (await create_item(db, user, workspace_id, _work(name))).item_id
        for name in ("Alpha", "Beta", "Gamma")
    ]
    tag = Tag(workspace_id=workspace_id, name="Review", created_by=user.id)
    project = Project(workspace_id=workspace_id, name="Review", created_by=user.id)
    db.add_all([tag, project])
    await db.flush()
    db.add_all([
        ItemTag(workspace_id=workspace_id, item_id=ids[0], tag_id=tag.id),
        ProjectItem(workspace_id=workspace_id, item_id=ids[0], project_id=project.id),
    ])
    receipt = ImportBatch(
        workspace_id=workspace_id,
        actor_id=user.id,
        file_format="commonmeta",
        records=[],
        errors=[],
        status="committed",
        committed_item_ids=[str(item_id) for item_id in ids],
    )
    db.add(receipt)
    await db.commit()
    path = f"/api/v1/workspaces/{workspace_id}/items"
    try:
        params = {
            "has_tags": "false",
            "has_projects": "false",
            "has_files": "false",
            "query": "study",
            "import_batch": str(receipt.id),
            "author_last_name": "Research",
            "keyword_exact": "Organization",
            "sort": "title",
            "direction": "desc",
            "limit": 1,
            "offset": 1,
        }
        response = await client.get(path, params=params)
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 2
        assert [row["id"] for row in response.json()["items"]] == [str(ids[1])]
        facets = await client.get(f"{path}/facets", params=params)
        assert facets.status_code == 200, facets.text
        assert facets.json()["authors"] == [
            {
                "last_name": "Research",
                "first_name": "Beta",
                "full_name": "Beta Research",
                "item_count": 1,
            }
        ]
        for field in ("has_tags", "has_projects"):
            for value, expected in (("true", [str(ids[0])]), ("false", list(map(str, ids[1:])))):
                response = await client.get(
                    path, params={field: value, "import_batch": str(receipt.id), "sort": "title"}
                )
                assert response.status_code == 200, response.text
                assert [row["id"] for row in response.json()["items"]] == expected
            for suffix in ("", "/facets"):
                response = await client.get(f"{path}{suffix}", params={field: "invalid"})
                assert response.status_code == 422, response.text
    finally:
        await client.aclose()
