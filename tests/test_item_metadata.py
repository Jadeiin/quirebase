from __future__ import annotations

from uuid import uuid4

import pytest
from item_helpers import (
    contributor,
    contributor_values,
    metadata_list_values,
    stored_doi,
    work_identifier,
)
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.access import resolve_workspace_context
from quirebase.audit import query_events
from quirebase.core.errors import PermissionDenied, ValidationFailure
from quirebase.library import (
    ItemMetadataData,
    ItemOverviewData,
    ItemSection,
    LibraryFilter,
    create_item,
    open_item_section,
    regenerate_citation_key,
    revise_item_metadata,
    search_library,
)
from quirebase.models import Item, User, WorkspaceMember, WorkspaceRole


async def _user(db, username: str, *, role: str = "member") -> User:
    user = User(username=username, password_hash="unused", role=role)
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


@pytest.mark.anyio
async def test_regenerate_citation_key_is_a_narrow_atomic_item_mutation(async_db):
    db = async_db
    owner = await _user(db, "item-mutation-owner", role="administrator")
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        created_by=owner.id,
        work={
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Computing Machinery and Intelligence",
            "description": "Can machines think?",
            "date_published": "1950",
            "contributors": contributor_values("Turing, Alan"),
            "identifiers": [{"identifier_type": "DOI", "identifier": "10.1093/mind/lix.236.433"}],
        },
    )
    db.add(item)
    await db.commit()
    owner_id = owner.id
    item_id = item.id
    result = await regenerate_citation_key(db, owner, fixture_workspace_id(owner), item_id)
    item_view = await open_item_section(
        db,
        await resolve_workspace_context(db, owner, fixture_workspace_id(owner)),
        item_id,
        ItemSection.metadata,
    )
    assert isinstance(item_view, ItemMetadataData)
    updated = item_view.item
    events, total = await query_events(db, owner, action="item.citation_key.regenerate")
    assert result.item_id == item_id
    assert result.version == 2
    assert updated.citation_key == "Turing1950Computing"
    assert updated.work.get("description") == "Can machines think?"
    assert stored_doi(updated) == "10.1093/mind/lix.236.433"
    assert total == 1
    assert events[0].target_id == str(item_id)
    assert updated.updated_by == owner_id


@pytest.mark.anyio
@pytest.mark.parametrize(
    "patch",
    [{"date_published": "invalid"}, {"type": "unrecognized"}, {"custom_fields": {"rating": 5}}],
)
async def test_item_metadata_rejects_invalid_standard_fields(async_db, patch):
    owner = await _user(async_db, "strict-item-owner")
    with pytest.raises(ValidationFailure):
        await create_item(
            async_db,
            owner,
            fixture_workspace_id(owner),
            {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Bounded", **patch},
        )


@pytest.mark.anyio
async def test_revise_item_metadata_preserves_identifiers_and_normalizes_only_comparison(async_db):
    from inquiro.work import work_identifiers

    owner = await _user(async_db, "identifier-owner")
    original = {"id": "https://doi.org/10.1000/old", "type": "Document", "title": "Identity"}
    created = await create_item(async_db, owner, fixture_workspace_id(owner), original)
    revised = {
        **original,
        "id": "https://doi.org/10.1000/new",
        "identifiers": [
            work_identifier("doi", "10.1000/NEW"),
            work_identifier("arxiv", "2401.12345"),
        ],
    }
    result = await revise_item_metadata(
        async_db, owner, fixture_workspace_id(owner), created.item_id, created.version, revised
    )
    item = await async_db.get(Item, result.item_id)
    assert item.work == revised
    assert work_identifiers(item.work) == {("doi", "10.1000/new"), ("arxiv", "2401.12345")}


@pytest.mark.anyio
async def test_revise_item_metadata_replaces_contributors_in_order(async_db):
    owner = await _user(async_db, "contributor-owner")
    work = {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Contributor replacement"}
    created = await create_item(async_db, owner, fixture_workspace_id(owner), work)
    work["contributors"] = [
        contributor("Shannon", "Claude", is_corresponding=True),
        contributor("Weaver", "Warren"),
    ]
    await revise_item_metadata(
        async_db, owner, fixture_workspace_id(owner), created.item_id, created.version, work
    )
    view = await open_item_section(
        async_db,
        await resolve_workspace_context(async_db, owner, fixture_workspace_id(owner)),
        created.item_id,
        ItemSection.metadata,
    )
    assert view.item.work == work
    assert view.metadata.model_dump(mode="json", exclude_none=True) == work
    assert "CorrespondingAuthor" in work["contributors"][0]["roles"]
    assert (
        await search_library(
            async_db, owner, fixture_workspace_id(owner), LibraryFilter(q="Contributor replacement")
        )
    )[1] == 1


@pytest.mark.anyio
async def test_create_item_accepts_typed_metadata_and_returns_a_mutation_result(async_db):
    db = async_db
    owner = await _user(db, "create-item-owner")
    result = await create_item(
        db,
        owner,
        fixture_workspace_id(owner),
        {
            "id": f"https://doi.org/{'10.1002/j.1538-7305.1948.tb01338.x'}",
            "type": "Document",
            "title": "A Mathematical Theory of Communication",
            "description": "The fundamental problem of communication.",
            "date_published": "1948",
            "contributors": (contributor("Shannon", "Claude"),),
            "subjects": [{"subject": v} for v in ("Information Theory", "Communication")],
        },
    )
    item_view = await open_item_section(
        db,
        await resolve_workspace_context(db, owner, fixture_workspace_id(owner)),
        result.item_id,
        ItemSection.overview,
    )
    assert isinstance(item_view, ItemOverviewData)
    created = item_view.item
    assert result.version == 1
    assert created.work.get("title") == "A Mathematical Theory of Communication"
    assert created.created_by == owner.id
    assert created.work["contributors"] == contributor_values("Shannon, Claude")
    assert stored_doi(created) == "10.1002/j.1538-7305.1948.tb01338.x"
    assert [
        subject["subject"] for subject in created.work.get("subjects", [])
    ] == metadata_list_values("Information Theory; Communication")


@pytest.mark.anyio
async def test_revise_item_metadata_rolls_back_every_change_when_a_group_is_invalid(async_db):
    owner = await _user(async_db, "atomic-item-owner")
    work = {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Original title"}
    created = await create_item(async_db, owner, fixture_workspace_id(owner), work)
    with pytest.raises(ValidationFailure):
        await revise_item_metadata(
            async_db,
            owner,
            fixture_workspace_id(owner),
            created.item_id,
            created.version,
            {
                **work,
                "title": "Uncommitted",
                "contributors": [
                    {"type": "Person", "person": {"family_name": "Invalid"}, "roles": ["invented"]}
                ],
            },
        )
    item = await async_db.get(Item, created.item_id)
    assert item.work == work and item.version == 1


@pytest.mark.anyio
async def test_revise_item_metadata_enforces_item_owner_permissions(async_db):
    db = async_db
    owner = await _user(db, "permission-owner")
    outsider = await _user(db, "permission-outsider")
    db.add(
        WorkspaceMember(
            workspace_id=fixture_workspace_id(owner),
            user_id=outsider.id,
            role=WorkspaceRole.viewer,
            invited_by=owner.id,
        )
    )
    await db.flush()
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        created_by=owner.id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Private metadata"},
    )
    db.add(item)
    await db.commit()
    item_id = item.id
    item_version = item.version
    with pytest.raises(PermissionDenied, match="item\\.update"):
        await revise_item_metadata(
            db,
            outsider,
            fixture_workspace_id(owner),
            item_id,
            item_version,
            {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Unauthorized update"},
        )
    db.expire_all()
    unchanged = await db.get(Item, item_id)
    assert unchanged is not None
    assert unchanged.work.get("title") == "Private metadata"
    assert unchanged.version == 1
