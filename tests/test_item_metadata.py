from __future__ import annotations

import pytest
from item_helpers import contributor, contributor_values, metadata_list_values, stored_doi
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.access import resolve_workspace_context
from quirebase.audit import query_events
from quirebase.core.errors import PermissionDenied, ValidationFailure
from quirebase.library import (
    ExternalIdentifier,
    ItemMetadata,
    ItemMetadataData,
    ItemOverviewData,
    ItemSection,
    create_item,
    open_item_section,
    regenerate_citation_key,
    revise_item_metadata,
    search_library,
)
from quirebase.models import (
    Item,
    ItemIdentifier,
    User,
    WorkspaceMember,
    WorkspaceRole,
)


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
        title="Computing Machinery and Intelligence",
        workspace_id=fixture_workspace_id(owner),
        abstract="Can machines think?",
        authors=contributor_values("Turing, Alan"),
        publication_date="1950",
        identifier_links=[
            ItemIdentifier(
                workspace_id=fixture_workspace_id(owner),
                provider="doi",
                value="10.1093/mind/lix.236.433",
            )
        ],
        created_by=owner.id,
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
    assert updated.abstract == "Can machines think?"
    assert (await stored_doi(db, updated)) == "10.1093/mind/lix.236.433"
    assert total == 1
    assert events[0].target_id == str(item_id)
    assert updated.updated_by == owner_id


@pytest.mark.anyio
async def test_item_metadata_rejects_values_longer_than_bounded_columns(async_db):
    db = async_db
    owner = await _user(db, "bounded-item-owner")
    workspace_id = fixture_workspace_id(owner)

    with pytest.raises(ValidationFailure, match="publication date must use"):
        await create_item(
            db,
            owner,
            workspace_id,
            ItemMetadata(title="Bounded", publication_date="x" * 33),
        )

    with pytest.raises(ValidationFailure, match="reference type must be a supported"):
        await create_item(
            db,
            owner,
            workspace_id,
            ItemMetadata(title="Bounded", reference_type="x" * 41),
        )

    with pytest.raises(ValidationFailure, match="identifier value is too long"):
        await create_item(
            db,
            owner,
            workspace_id,
            ItemMetadata(
                title="Bounded",
                identifiers=(ExternalIdentifier("pmid", "x" * 501),),
            ),
        )


@pytest.mark.anyio
async def test_revise_item_metadata_unifies_equivalent_doi_inputs(async_db):
    db = async_db
    owner = await _user(db, "identifier-owner")
    item = Item(
        title="Identifier precedence",
        workspace_id=fixture_workspace_id(owner),
        identifier_links=[
            ItemIdentifier(
                workspace_id=fixture_workspace_id(owner), provider="doi", value="10.1000/old"
            )
        ],
        created_by=owner.id,
    )
    db.add(item)
    await db.flush()
    db.add(
        ItemIdentifier(
            workspace_id=item.workspace_id, item_id=item.id, provider="pmid", value="old-pmid"
        )
    )
    await db.commit()
    item_id = item.id
    item_version = item.version
    item_title = item.title

    result = await revise_item_metadata(
        db,
        owner,
        fixture_workspace_id(owner),
        item_id,
        item_version,
        ItemMetadata(
            title=item_title,
            doi="https://doi.org/10.1000/new",
            identifiers=(
                ExternalIdentifier("doi", "10.1000/NEW"),
                ExternalIdentifier("arxiv", "2401.12345"),
            ),
        ),
    )

    item_view = await open_item_section(
        db,
        await resolve_workspace_context(db, owner, fixture_workspace_id(owner)),
        item_id,
        ItemSection.overview,
    )
    assert isinstance(item_view, ItemOverviewData)
    updated = item_view.item
    identifiers = {link.provider: link.value for link in item_view.identifiers}
    assert result.version == 2
    assert (await stored_doi(db, updated)) == "10.1000/new"
    assert identifiers == {"arxiv": "2401.12345", "doi": "10.1000/new"}


@pytest.mark.anyio
async def test_revise_item_metadata_replaces_contributors_in_order(async_db):
    db = async_db
    owner = await _user(db, "contributor-owner")
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        title="Contributor replacement",
        authors=contributor_values("Old, Author"),
        created_by=owner.id,
    )
    db.add(item)
    await db.flush()
    await db.commit()
    item_id = item.id
    item_version = item.version
    item_title = item.title

    await revise_item_metadata(
        db,
        owner,
        fixture_workspace_id(owner),
        item_id,
        item_version,
        ItemMetadata(
            title=item_title,
            authors=(
                contributor("Shannon", "Claude", is_corresponding=True),
                contributor("Weaver", "Warren"),
            ),
            editors=(),
        ),
    )

    item_view = await open_item_section(
        db,
        await resolve_workspace_context(db, owner, fixture_workspace_id(owner)),
        item_id,
        ItemSection.metadata,
    )
    assert isinstance(item_view, ItemMetadataData)
    assert [row["family_name"] for row in item_view.item.authors] == ["Shannon", "Weaver"]
    assert item_view.item.editors == []
    assert [contributor.family_name for contributor in item_view.metadata.authors] == [
        "Shannon",
        "Weaver",
    ]
    assert item_view.metadata.authors[0].is_corresponding
    matches, total = await search_library(
        db, owner, fixture_workspace_id(owner), q="Contributor replacement"
    )
    assert total == 1
    assert matches[0].id == item_id


@pytest.mark.anyio
async def test_revise_item_metadata_rejects_canonically_duplicate_contributors(async_db):
    owner = await _user(async_db, "canonical-contributor-owner")
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        title="Canonical contributor identity",
        created_by=owner.id,
    )
    async_db.add(item)
    await async_db.commit()

    with pytest.raises(ValidationFailure, match="unique within a role"):
        await revise_item_metadata(
            async_db,
            owner,
            fixture_workspace_id(owner),
            item.id,
            item.version,
            ItemMetadata(
                title=item.title,
                authors=(contributor("Van  Rossum", "Guido"), contributor("Van Rossum", "Guido")),
            ),
        )


@pytest.mark.anyio
async def test_create_item_accepts_typed_metadata_and_returns_a_mutation_result(async_db):
    db = async_db
    owner = await _user(db, "create-item-owner")

    result = await create_item(
        db,
        owner,
        fixture_workspace_id(owner),
        ItemMetadata(
            title="A Mathematical Theory of Communication",
            abstract="The fundamental problem of communication.",
            publication_date="1948",
            keywords=("Information Theory", "Communication"),
            authors=(contributor("Shannon", "Claude"),),
            doi="10.1002/j.1538-7305.1948.tb01338.x",
        ),
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
    assert created.title == "A Mathematical Theory of Communication"
    assert created.created_by == owner.id
    assert created.authors == contributor_values("Shannon, Claude")
    assert (await stored_doi(db, created)) == "10.1002/j.1538-7305.1948.tb01338.x"
    assert created.keywords == metadata_list_values("Information Theory; Communication")


@pytest.mark.anyio
async def test_revise_item_metadata_rolls_back_every_change_when_a_group_is_invalid(async_db):
    db = async_db
    owner = await _user(db, "atomic-item-owner")
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        title="Original title",
        created_by=owner.id,
    )
    db.add(item)
    await db.commit()
    item_id = item.id
    item_version = item.version

    with pytest.raises(ValidationFailure, match="editors cannot be corresponding authors"):
        await revise_item_metadata(
            db,
            owner,
            fixture_workspace_id(owner),
            item_id,
            item_version,
            ItemMetadata(
                title="Partially updated title",
                editors=(contributor("Invalid", is_corresponding=True),),
                doi="10.1000/should-not-persist",
            ),
        )

    db.expire_all()
    unchanged = await db.get(Item, item_id)
    assert unchanged is not None
    assert unchanged.title == "Original title"
    assert unchanged.version == 1
    assert (await stored_doi(db, unchanged)) is None


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
        title="Private metadata",
        created_by=owner.id,
    )
    db.add(item)
    await db.commit()
    item_id = item.id
    item_version = item.version

    with pytest.raises(PermissionDenied, match=r"item\.update"):
        await revise_item_metadata(
            db,
            outsider,
            fixture_workspace_id(owner),
            item_id,
            item_version,
            ItemMetadata(title="Unauthorized update"),
        )

    db.expire_all()
    unchanged = await db.get(Item, item_id)
    assert unchanged is not None
    assert unchanged.title == "Private metadata"
    assert unchanged.version == 1
