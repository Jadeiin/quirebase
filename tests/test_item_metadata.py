from __future__ import annotations

import pytest

from quirebase.audit import query_events
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.library import (
    Contributor,
    ExternalIdentifier,
    ItemMetadata,
    MetadataWorkspace,
    SummaryWorkspace,
    WorkspaceSection,
    create_item,
    open_item_workspace,
    regenerate_bibtex_key,
    revise_item_metadata,
    search_library,
)
from quirebase.models import Author, Item, ItemAuthor, ItemIdentifier, User


@pytest.mark.anyio
async def test_regenerate_bibtex_key_is_a_narrow_atomic_item_mutation(async_db):
    db = async_db
    owner = User(
        username="item-mutation-owner",
        password_hash="unused",
        role="administrator",
    )
    db.add(owner)
    await db.flush()
    item = Item(
        title="Computing Machinery and Intelligence",
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
    item_version = item.version

    result = await regenerate_bibtex_key(
        db,
        owner,
        item_id,
        item_version,
    )

    workspace = await open_item_workspace(db, owner, item_id, WorkspaceSection.metadata)
    assert isinstance(workspace, MetadataWorkspace)
    updated = workspace.item
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
async def test_revise_item_metadata_makes_the_dedicated_doi_authoritative(async_db):
    db = async_db
    owner = User(username="identifier-owner", password_hash="unused")
    db.add(owner)
    await db.flush()
    item = Item(
        title="Identifier precedence",
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

    workspace = await open_item_workspace(db, owner, item_id, WorkspaceSection.summary)
    assert isinstance(workspace, SummaryWorkspace)
    updated = workspace.item
    identifiers = {link.provider: link.value for link in workspace.identifiers}
    assert result.version == 2
    assert updated.doi == "10.1000/new"
    assert identifiers == {"arxiv": "2401.12345"}


@pytest.mark.anyio
async def test_revise_item_metadata_replaces_contributors_in_order(async_db):
    db = async_db
    owner = User(username="contributor-owner", password_hash="unused")
    old_author = Author(last_name="Old", first_name="Author")
    db.add_all([owner, old_author])
    await db.flush()
    item = Item(title="Contributor replacement", authors="Old, Author", created_by=owner.id)
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

    workspace = await open_item_workspace(db, owner, item_id, WorkspaceSection.metadata)
    assert isinstance(workspace, MetadataWorkspace)
    assert workspace.item.authors == "Shannon, Claude; Weaver, Warren"
    assert workspace.item.editors is None
    assert [link.author.last_name for link in workspace.authors] == [
        "Shannon",
        "Weaver",
    ]
    assert [link.position for link in workspace.authors] == [1, 2]
    assert workspace.authors[0].is_corresponding
    matches, total, _, _ = await search_library(db, owner, q="Contributor replacement")
    assert total == 1
    assert matches[0].id == item_id


@pytest.mark.anyio
async def test_create_item_accepts_typed_metadata_and_returns_a_mutation_result(async_db):
    db = async_db
    owner = User(username="create-item-owner", password_hash="unused")
    db.add(owner)
    await db.commit()

    result = await create_item(
        db,
        owner,
        ItemMetadata(
            title="A Mathematical Theory of Communication",
            abstract="The fundamental problem of communication.",
            publication_date="1948",
            keywords=("Information Theory", "Communication"),
            authors=(Contributor("Shannon", "Claude"),),
            doi="10.1002/j.1538-7305.1948.tb01338.x",
        ),
    )

    workspace = await open_item_workspace(db, owner, result.item_id, WorkspaceSection.summary)
    assert isinstance(workspace, SummaryWorkspace)
    created = workspace.item
    assert result.version == 1
    assert created.title == "A Mathematical Theory of Communication"
    assert created.created_by == owner.id
    assert created.authors == "Shannon, Claude"
    assert created.doi == "10.1002/j.1538-7305.1948.tb01338.x"
    assert created.keywords == "Information Theory; Communication"


@pytest.mark.anyio
async def test_revise_item_metadata_rolls_back_every_change_when_a_group_is_invalid(async_db):
    db = async_db
    owner = User(username="atomic-item-owner", password_hash="unused")
    db.add(owner)
    await db.flush()
    item = Item(title="Original title", created_by=owner.id)
    db.add(item)
    await db.commit()
    item_id = item.id
    item_version = item.version

    with pytest.raises(ValidationFailure, match="editors cannot be corresponding authors"):
        await revise_item_metadata(
            db,
            owner,
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
    owner = User(username="permission-owner", password_hash="unused")
    outsider = User(username="permission-outsider", password_hash="unused")
    db.add_all([owner, outsider])
    await db.flush()
    item = Item(title="Private metadata", created_by=owner.id)
    db.add(item)
    await db.commit()
    item_id = item.id
    item_version = item.version

    with pytest.raises(ResourceUnavailable, match="item not found"):
        await revise_item_metadata(
            db,
            outsider,
            item_id,
            item_version,
            ItemMetadata(title="Unauthorized update"),
        )

    db.expire_all()
    unchanged = await db.get(Item, item_id)
    assert unchanged is not None
    assert unchanged.title == "Private metadata"
    assert unchanged.version == 1
