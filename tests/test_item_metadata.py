from __future__ import annotations

import pytest
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.audit import query_events
from quirebase.core.errors import PermissionDenied, ValidationFailure
from quirebase.library import (
    Contributor,
    ExternalIdentifier,
    ItemMetadata,
    ItemMetadataData,
    ItemOverviewData,
    ItemSection,
    create_item,
    open_item_section,
    regenerate_bibtex_key,
    revise_item_metadata,
    search_library,
)
from quirebase.models import (
    Author,
    Item,
    ItemAuthor,
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
async def test_regenerate_bibtex_key_is_a_narrow_atomic_item_mutation(async_db):
    db = async_db
    owner = await _user(db, "item-mutation-owner", role="administrator")
    item = Item(
        title="Computing Machinery and Intelligence",
        workspace_id=fixture_workspace_id(owner),
        abstract="Can machines think?",
        authors="Turing, Alan",
        publication_date="1950",
        doi="10.1093/mind/lix.236.433",
        created_by=owner.id,
    )
    db.add(item)
    await db.commit()
    owner_id = owner.id
    item_id = item.id

    result = await regenerate_bibtex_key(db, owner, fixture_workspace_id(owner), item_id)

    item_view = await open_item_section(
        db, owner, fixture_workspace_id(owner), item_id, ItemSection.metadata
    )
    assert isinstance(item_view, ItemMetadataData)
    updated = item_view.item
    events, total = await query_events(db, owner, action="item.bibtex_key.regenerate")
    assert result.item_id == item_id
    assert result.version == 2
    assert updated.bibtex_id == "Turing1950Computing"
    assert updated.abstract == "Can machines think?"
    assert updated.doi == "10.1093/mind/lix.236.433"
    assert total == 1
    assert events[0].target_id == item_id
    assert updated.updated_by == owner_id


@pytest.mark.anyio
async def test_item_metadata_rejects_values_longer_than_bounded_columns(async_db):
    db = async_db
    owner = await _user(db, "bounded-item-owner")
    workspace_id = fixture_workspace_id(owner)

    with pytest.raises(ValidationFailure, match="publication date is too long"):
        await create_item(
            db,
            owner,
            workspace_id,
            ItemMetadata(title="Bounded", publication_date="x" * 33),
        )

    with pytest.raises(ValidationFailure, match="reference type is too long"):
        await create_item(
            db,
            owner,
            workspace_id,
            ItemMetadata(title="Bounded", reference_type="x" * 41),
        )

    with pytest.raises(ValidationFailure, match="contributor name is too long"):
        await create_item(
            db,
            owner,
            workspace_id,
            ItemMetadata(title="Bounded", authors=(Contributor("x" * 121),)),
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
async def test_revise_item_metadata_makes_the_dedicated_doi_authoritative(async_db):
    db = async_db
    owner = await _user(db, "identifier-owner")
    item = Item(
        title="Identifier precedence",
        workspace_id=fixture_workspace_id(owner),
        doi="10.1000/old",
        identifiers='{"doi": "10.1000/old", "pmid": "old-pmid"}',
        created_by=owner.id,
    )
    db.add(item)
    await db.flush()
    db.add(ItemIdentifier(item_id=item.id, provider="pmid", value="old-pmid"))
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
                ExternalIdentifier("doi", "10.1000/stale"),
                ExternalIdentifier("arxiv", "2401.12345"),
            ),
        ),
    )

    item_view = await open_item_section(
        db, owner, fixture_workspace_id(owner), item_id, ItemSection.overview
    )
    assert isinstance(item_view, ItemOverviewData)
    updated = item_view.item
    identifiers = {link.provider: link.value for link in item_view.identifiers}
    assert result.version == 2
    assert updated.doi == "10.1000/new"
    assert identifiers == {"arxiv": "2401.12345"}


@pytest.mark.anyio
async def test_revise_item_metadata_replaces_contributors_in_order(async_db):
    db = async_db
    owner = await _user(db, "contributor-owner")
    old_author = Author(last_name="Old", first_name="Author")
    db.add(old_author)
    await db.flush()
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        title="Contributor replacement",
        authors="Old, Author",
        created_by=owner.id,
    )
    db.add(item)
    await db.flush()
    db.add(ItemAuthor(item_id=item.id, author_id=old_author.id, position=1, role="author"))
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
                Contributor("Shannon", "Claude", is_corresponding=True),
                Contributor("Weaver", "Warren"),
            ),
            editors=(),
        ),
    )

    item_view = await open_item_section(
        db, owner, fixture_workspace_id(owner), item_id, ItemSection.metadata
    )
    assert isinstance(item_view, ItemMetadataData)
    assert item_view.item.authors == "Shannon, Claude; Weaver, Warren"
    assert item_view.item.editors is None
    assert [link.author.last_name for link in item_view.authors] == [
        "Shannon",
        "Weaver",
    ]
    assert [link.position for link in item_view.authors] == [1, 2]
    assert item_view.authors[0].is_corresponding
    matches, total, _, _ = await search_library(
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
                authors=(Contributor("Van  Rossum", "Guido"), Contributor("Van Rossum", "Guido")),
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
            authors=(Contributor("Shannon", "Claude"),),
            doi="10.1002/j.1538-7305.1948.tb01338.x",
        ),
    )

    item_view = await open_item_section(
        db, owner, fixture_workspace_id(owner), result.item_id, ItemSection.overview
    )
    assert isinstance(item_view, ItemOverviewData)
    created = item_view.item
    assert result.version == 1
    assert created.title == "A Mathematical Theory of Communication"
    assert created.created_by == owner.id
    assert created.authors == "Shannon, Claude"
    assert created.doi == "10.1002/j.1538-7305.1948.tb01338.x"
    assert created.keywords == "Information Theory; Communication"


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
                editors=(Contributor("Invalid", is_corresponding=True),),
                doi="10.1000/should-not-persist",
            ),
        )

    db.expire_all()
    unchanged = await db.get(Item, item_id)
    assert unchanged is not None
    assert unchanged.title == "Original title"
    assert unchanged.version == 1
    assert unchanged.doi is None


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

    with pytest.raises(PermissionDenied, match=r"items\.edit"):
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
