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


def test_regenerate_bibtex_key_is_a_narrow_atomic_item_mutation(db):
    owner = User(
        username="item-mutation-owner",
        password_hash="unused",
        role="administrator",
    )
    db.add(owner)
    db.flush()
    item = Item(
        title="Computing Machinery and Intelligence",
        abstract="Can machines think?",
        authors="Turing, Alan",
        publication_date="1950",
        doi="10.1093/mind/lix.236.433",
        created_by=owner.id,
    )
    db.add(item)
    db.commit()

    result = regenerate_bibtex_key(
        db,
        owner,
        item.id,
        item.version,
    )

    workspace = open_item_workspace(db, owner, item.id, WorkspaceSection.metadata)
    assert isinstance(workspace, MetadataWorkspace)
    updated = workspace.item
    events, total = query_events(db, owner, action="item.bibtex_key.regenerate")
    assert result.item_id == item.id
    assert result.version == 2
    assert updated.bibtex_id == "Turing1950Computing"
    assert updated.abstract == "Can machines think?"
    assert updated.doi == "10.1093/mind/lix.236.433"
    assert total == 1
    assert events[0].target_id == item.id


def test_revise_item_metadata_makes_the_dedicated_doi_authoritative(db):
    owner = User(username="identifier-owner", password_hash="unused")
    db.add(owner)
    db.flush()
    item = Item(
        title="Identifier precedence",
        doi="10.1000/old",
        identifiers='{"doi": "10.1000/old", "pmid": "old-pmid"}',
        created_by=owner.id,
    )
    db.add(item)
    db.flush()
    db.add_all([
        ItemIdentifier(item_id=item.id, provider="doi", value="10.1000/old"),
        ItemIdentifier(item_id=item.id, provider="pmid", value="old-pmid"),
    ])
    db.commit()

    result = revise_item_metadata(
        db,
        owner,
        item.id,
        item.version,
        ItemMetadata(
            title=item.title,
            doi="https://doi.org/10.1000/new",
            identifiers=(
                ExternalIdentifier("doi", "10.1000/stale"),
                ExternalIdentifier("arxiv", "2401.12345"),
            ),
        ),
    )

    workspace = open_item_workspace(db, owner, item.id, WorkspaceSection.summary)
    assert isinstance(workspace, SummaryWorkspace)
    updated = workspace.item
    identifiers = {link.provider: link.value for link in workspace.identifiers}
    assert result.version == 2
    assert updated.doi == "10.1000/new"
    assert identifiers == {"arxiv": "2401.12345", "doi": "10.1000/new"}


def test_revise_item_metadata_replaces_contributors_in_order(db):
    owner = User(username="contributor-owner", password_hash="unused")
    old_author = Author(last_name="Old", first_name="Author")
    db.add_all([owner, old_author])
    db.flush()
    item = Item(title="Contributor replacement", authors="Old, Author", created_by=owner.id)
    db.add(item)
    db.flush()
    db.add(ItemAuthor(item_id=item.id, author_id=old_author.id, position=1, role="author"))
    db.commit()

    revise_item_metadata(
        db,
        owner,
        item.id,
        item.version,
        ItemMetadata(
            title=item.title,
            authors=(
                Contributor("Shannon", "Claude", is_corresponding=True),
                Contributor("Weaver", "Warren"),
            ),
            editors=(),
        ),
    )

    workspace = open_item_workspace(db, owner, item.id, WorkspaceSection.metadata)
    assert isinstance(workspace, MetadataWorkspace)
    assert workspace.item.authors == "Shannon, Claude; Weaver, Warren"
    assert workspace.item.editors is None
    assert [link.author.last_name for link in workspace.authors] == [
        "Shannon",
        "Weaver",
    ]
    assert [link.position for link in workspace.authors] == [1, 2]
    assert workspace.authors[0].is_corresponding
    matches, total, _, _ = search_library(db, owner, q="Contributor replacement")
    assert total == 1
    assert matches[0].id == item.id


def test_create_item_accepts_typed_metadata_and_returns_a_mutation_result(db):
    owner = User(username="create-item-owner", password_hash="unused")
    db.add(owner)
    db.commit()

    result = create_item(
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

    workspace = open_item_workspace(db, owner, result.item_id, WorkspaceSection.summary)
    assert isinstance(workspace, SummaryWorkspace)
    created = workspace.item
    assert result.version == 1
    assert created.title == "A Mathematical Theory of Communication"
    assert created.created_by == owner.id
    assert created.authors == "Shannon, Claude"
    assert created.doi == "10.1002/j.1538-7305.1948.tb01338.x"
    assert created.keywords == "Information Theory; Communication"


def test_revise_item_metadata_rolls_back_every_change_when_a_group_is_invalid(db):
    owner = User(username="atomic-item-owner", password_hash="unused")
    db.add(owner)
    db.flush()
    item = Item(title="Original title", created_by=owner.id)
    db.add(item)
    db.commit()

    with pytest.raises(ValidationFailure, match="editors cannot be corresponding authors"):
        revise_item_metadata(
            db,
            owner,
            item.id,
            item.version,
            ItemMetadata(
                title="Partially updated title",
                editors=(Contributor("Invalid", is_corresponding=True),),
                doi="10.1000/should-not-persist",
            ),
        )

    db.expire_all()
    unchanged = db.get(Item, item.id)
    assert unchanged is not None
    assert unchanged.title == "Original title"
    assert unchanged.version == 1
    assert unchanged.doi is None


def test_revise_item_metadata_enforces_item_owner_permissions(db):
    owner = User(username="permission-owner", password_hash="unused")
    outsider = User(username="permission-outsider", password_hash="unused")
    db.add_all([owner, outsider])
    db.flush()
    item = Item(title="Private metadata", created_by=owner.id)
    db.add(item)
    db.commit()

    with pytest.raises(ResourceUnavailable, match="item not found"):
        revise_item_metadata(
            db,
            outsider,
            item.id,
            item.version,
            ItemMetadata(title="Unauthorized update"),
        )

    db.expire_all()
    unchanged = db.get(Item, item.id)
    assert unchanged is not None
    assert unchanged.title == "Private metadata"
    assert unchanged.version == 1
