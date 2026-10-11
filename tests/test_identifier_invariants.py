from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from inquiro import CandidateRecord, Identifier
from item_helpers import stored_doi
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from workspace_helpers import provision_initial_workspace

from quirebase.core.errors import ValidationFailure
from quirebase.library import (
    ExternalIdentifier,
    ItemMetadata,
    commit_import_batch,
    copy_item_to_workspace,
    create_item,
    create_item_from_metadata_record,
    revise_item_metadata,
    stage_import_batch,
)
from quirebase.models import AuditEvent, ImportBatch, Item, ItemIdentifier, User
from quirebase.workspaces import create_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


async def _owner(db):
    actor = User(
        username="identifier-invariants-owner", password_hash="unused", role="administrator"
    )
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    await db.commit()
    return actor, workspace.id


async def test_articles_in_the_same_journal_do_not_claim_issn_item_identity(persistence_db):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    source = b"""@article{first, title={First Article}, doi={10.1000/first}, issn={1234-5678}}
    @article{second, title={Second Article}, doi={10.1000/second}, issn={1234-5678}}"""

    batch, records, errors = await stage_import_batch(db, actor, workspace_id, source, "bibtex")

    assert errors == []
    assert len(records) == 2
    assert all(not record["identifiers"] for record in records)
    await commit_import_batch(db, actor, workspace_id, batch.id)
    items = (await db.scalars(select(Item).where(Item.workspace_id == workspace_id))).all()
    assert {(await stored_doi(db, item)) for item in items} == {"10.1000/first", "10.1000/second"}
    assert all(item.custom_fields == {"issn": "1234-5678"} for item in items)
    assert (
        await db.scalar(
            select(func.count())
            .select_from(ItemIdentifier)
            .where(ItemIdentifier.provider == "issn")
        )
        == 0
    )


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex"])
@pytest.mark.parametrize("entry_type", ["incollection", "inbook"])
async def test_book_and_chapters_can_share_container_isbn(persistence_db, file_format, entry_type):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    source = (
        "@book{volume, title={Collected chapters}, isbn={9780131103627}}\n"
        f"@{entry_type}{{first, title={{First chapter}}, doi={{10.1000/first}}, "
        "isbn={9780131103627}}\n"
        f"@{entry_type}{{second, title={{Second chapter}}, doi={{10.1000/second}}, "
        "isbn={9780131103627}}"
    ).encode()

    batch, records, errors = await stage_import_batch(db, actor, workspace_id, source, file_format)

    assert errors == []
    assert len(records) == 3
    assert all(not record["identifiers"] for record in records[1:])
    await commit_import_batch(db, actor, workspace_id, batch.id)
    items = (await db.scalars(select(Item).where(Item.workspace_id == workspace_id))).all()
    assert len(items) == 3
    chapters = [item for item in items if item.reference_type == "chapter"]
    assert {(await stored_doi(db, item)) for item in chapters} == {
        "10.1000/first",
        "10.1000/second",
    }
    assert all(item.custom_fields == {"isbn": "9780131103627"} for item in chapters)
    identities = (
        await db.scalars(select(ItemIdentifier).where(ItemIdentifier.provider == "isbn"))
    ).all()
    assert len(identities) == 1
    assert (identities[0].provider, identities[0].value) == ("isbn", "9780131103627")
    assert (await db.get(Item, identities[0].item_id)).reference_type == "book"


@pytest.mark.parametrize("second_value", ["W123", "W456"])
async def test_duplicate_provider_entries_are_rejected_before_creation(
    persistence_db, second_value
):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    with pytest.raises(ValidationFailure, match="one identifier per provider"):
        await create_item(
            db,
            actor,
            workspace_id,
            ItemMetadata(
                title="Rejected duplicate providers",
                identifiers=(
                    ExternalIdentifier("openalex", "W123"),
                    ExternalIdentifier(" OPENALEX ", second_value),
                ),
            ),
        )
    assert await db.scalar(select(func.count()).select_from(Item)) == 0


@pytest.mark.parametrize("source", ["provider", "import"])
async def test_duplicate_provider_candidates_are_rejected_before_dict_projection(
    persistence_db, source
):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    if source == "provider":
        record = CandidateRecord(
            provider="openalex",
            lookup_identifier=Identifier("openalex", "W123"),
            title="Rejected Provider result",
            identifiers=(Identifier("openalex", "W123"), Identifier("OPENALEX", "W456")),
        )
        with pytest.raises(ValidationFailure, match="one identifier per provider"):
            await create_item_from_metadata_record(db, actor, workspace_id, record)
    else:
        batch = ImportBatch(
            workspace_id=workspace_id,
            actor_id=actor.id,
            file_format="bibtex",
            records=[
                {
                    "title": "Rejected import",
                    "identifiers": {"openalex": "W123", "OPENALEX": "W456"},
                }
            ],
            errors=[],
        )
        db.add(batch)
        await db.commit()
        with pytest.raises(ValidationFailure, match="one identifier per provider"):
            await commit_import_batch(db, actor, workspace_id, batch.id)
    assert await db.scalar(select(func.count()).select_from(Item)) == 0


async def test_provider_identifier_conflict_preserves_the_existing_item(persistence_db):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    first = await create_item(
        db,
        actor,
        workspace_id,
        ItemMetadata(title="First", identifiers=(ExternalIdentifier("arxiv", "2401.00001"),)),
    )
    second = await create_item(
        db,
        actor,
        workspace_id,
        ItemMetadata(title="Second", identifiers=(ExternalIdentifier("arxiv", "2401.00002"),)),
    )
    with pytest.raises(ValidationFailure, match="already assigned to another Item"):
        await revise_item_metadata(
            db,
            actor,
            workspace_id,
            second.item_id,
            second.version,
            ItemMetadata(
                title="Rejected edit", identifiers=(ExternalIdentifier(" ARXIV ", " 2401.00001 "),)
            ),
        )
    item = await db.get(Item, second.item_id)
    assert (item.title, item.version) == ("Second", 1)
    assert (
        await db.scalar(select(ItemIdentifier).where(ItemIdentifier.item_id == second.item_id))
    ).value == "2401.00002"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(ItemIdentifier)
            .where(ItemIdentifier.item_id == first.item_id)
        )
        == 1
    )
    assert (
        await db.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "item.update")
        )
        == 0
    )


@pytest.mark.parametrize(
    ("provider", "value", "alias"),
    [
        ("openalex", "W123", "https://openalex.org/w123"),
        ("arxiv", "2401.00001", "https://arxiv.org/abs/2401.00001"),
        ("doi", "10.1000/example", "HTTPS://DOI.ORG/10.1000/EXAMPLE"),
    ],
)
async def test_equivalent_provider_id_spellings_share_one_workspace_claim(
    persistence_db, provider, value, alias
):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    await create_item(
        db,
        actor,
        workspace_id,
        ItemMetadata(title="First", identifiers=(ExternalIdentifier(provider, value),)),
    )
    with pytest.raises(ValidationFailure, match="already assigned to another Item"):
        await create_item(
            db,
            actor,
            workspace_id,
            ItemMetadata(title="Second", identifiers=(ExternalIdentifier(provider, alias),)),
        )
    assert await db.scalar(select(func.count()).select_from(Item)) == 1


@pytest.mark.parametrize("violation", ["item_provider", "workspace_identity", "workspace_lineage"])
async def test_database_enforces_identifier_uniqueness_and_lineage(persistence_db, violation):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    first = await create_item(
        db,
        actor,
        workspace_id,
        ItemMetadata(title="First", identifiers=(ExternalIdentifier("openalex", "W123"),)),
    )
    second = await create_item(db, actor, workspace_id, ItemMetadata(title="Second"))
    another = await create_workspace(db, actor, "Another", owner_username=actor.username)
    await db.commit()
    values = {
        "workspace_id": another.id if violation == "workspace_lineage" else workspace_id,
        "item_id": second.item_id if violation == "workspace_identity" else first.item_id,
        "provider": "openalex",
        "value": "W123" if violation == "workspace_identity" else "W456",
    }

    async def insert_invalid_identifier():
        async with db.begin_nested():
            await db.execute(insert(ItemIdentifier).values(**values))

    with pytest.raises(IntegrityError):
        await insert_invalid_identifier()
    assert await db.scalar(select(func.count()).select_from(ItemIdentifier)) == 1


async def test_cross_workspace_copy_preserves_independent_identifier_claims(persistence_db):
    db = persistence_db
    actor, source_workspace = await _owner(db)
    target_workspace = await create_workspace(db, actor, "Target", owner_username=actor.username)
    await db.commit()
    target_workspace_id = target_workspace.id
    source = await create_item(
        db,
        actor,
        source_workspace,
        ItemMetadata(
            title="Source",
            doi="10.1000/source",
            identifiers=(ExternalIdentifier("openalex", "W123"),),
        ),
    )
    copied = await copy_item_to_workspace(
        db, actor, source_workspace, target_workspace_id, source.item_id
    )
    copied_id = copied.id
    rows = (await db.scalars(select(ItemIdentifier).where(ItemIdentifier.value == "W123"))).all()
    assert {(row.workspace_id, row.item_id) for row in rows} == {
        (source_workspace, source.item_id),
        (target_workspace_id, copied_id),
    }
    assert (await stored_doi(db, copied)) == "10.1000/source"
    with pytest.raises(ValidationFailure, match="already assigned to another Item"):
        await copy_item_to_workspace(
            db, actor, source_workspace, target_workspace_id, source.item_id
        )
    assert (
        await db.scalar(
            select(func.count()).select_from(Item).where(Item.workspace_id == target_workspace_id)
        )
        == 1
    )


async def test_import_batch_cannot_claim_the_same_provider_identifier_twice(persistence_db):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    batch = ImportBatch(
        workspace_id=workspace_id,
        actor_id=actor.id,
        file_format="bibtex",
        records=[
            {"title": title, "identifiers": {"openalex": "W123"}} for title in ("First", "Second")
        ],
        errors=[],
    )
    db.add(batch)
    await db.commit()
    batch_id = batch.id
    with pytest.raises(ValidationFailure, match="already assigned to another Item"):
        await commit_import_batch(db, actor, workspace_id, batch_id)
    await db.rollback()
    batch = await db.get(ImportBatch, batch_id)
    assert batch.status == "ready" and batch.committed_item_ids is None
    assert await db.scalar(select(func.count()).select_from(Item)) == 0


@pytest.mark.concurrency_case("identifier-claim")
@pytest.mark.parametrize(("provider", "value"), [("openalex", "W123"), ("doi", "10.1000/example")])
async def test_concurrent_items_cannot_claim_the_same_identifier(
    postgres_sessions, postgres_search_tables, postgres_race, monkeypatch, provider, value
):
    async with postgres_sessions() as db:
        actor, workspace_id = await _owner(db)
        first = await create_item(db, actor, workspace_id, ItemMetadata(title="First"))
        second = await create_item(db, actor, workspace_id, ItemMetadata(title="Second"))
        actor_id = actor.id
    replacement = ItemMetadata(title="Claimed", identifiers=(ExternalIdentifier(provider, value),))

    async def claim_second():
        async with postgres_race.session("second") as db:
            with pytest.raises(ValidationFailure, match="already assigned to another Item"):
                await revise_item_metadata(
                    db, await db.get(User, actor_id), workspace_id, second.item_id, 1, replacement
                )

    async with postgres_race.session("first") as db:
        commit = db.commit
        monkeypatch.setattr(db, "commit", AsyncMock(side_effect=db.flush))
        await revise_item_metadata(
            db, await db.get(User, actor_id), workspace_id, first.item_id, 1, replacement
        )
        postgres_race.start("second", claim_second())
        await postgres_race.wait_blocked("second", "first")
        await commit()
        await postgres_race.join("second")
    async with postgres_sessions() as db:
        rows = (await db.scalars(select(ItemIdentifier))).all()
        assert len(rows) == 1 and rows[0].item_id == first.item_id
        loser = await db.get(Item, second.item_id)
        assert (loser.title, loser.version) == ("Second", 1)
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "item.update")
            )
            == 1
        )


async def test_doi_unicode_characters_remain_distinct_workspace_claims(persistence_db):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    values = ("10.1000/AßÉ", "10.1000/ASSÉ", "10.1000/Aßé")
    for value in values:
        await create_item(db, actor, workspace_id, ItemMetadata(title=value, doi=value))
    rows = (await db.scalars(select(ItemIdentifier).where(ItemIdentifier.provider == "doi"))).all()
    assert {row.value for row in rows} == {"10.1000/aßÉ", "10.1000/assÉ", "10.1000/aßé"}
    assert "doi" not in Item.__table__.columns


async def test_copy_rejects_a_doi_already_claimed_in_the_target_workspace(persistence_db):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    target = await create_workspace(db, actor, "Target", owner_username=actor.username)
    await db.commit()
    target_id = target.id
    source = await create_item(
        db, actor, workspace_id, ItemMetadata(title="Source", doi="10.1000/COPY")
    )
    await create_item(
        db, actor, target_id, ItemMetadata(title="Existing", doi="https://doi.org/10.1000/copy")
    )
    with pytest.raises(ValidationFailure, match="already assigned"):
        await copy_item_to_workspace(db, actor, workspace_id, target_id, source.item_id)
    assert (
        await db.scalar(
            select(func.count()).select_from(Item).where(Item.workspace_id == target_id)
        )
        == 1
    )


async def test_import_batch_cannot_claim_equivalent_dois_twice(persistence_db):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    batch = ImportBatch(
        workspace_id=workspace_id,
        actor_id=actor.id,
        file_format="bibtex",
        records=[
            {"title": "First", "doi": "10.1000/SAME"},
            {"title": "Second", "identifiers": {"doi": "https://doi.org/10.1000/same"}},
        ],
        errors=[],
    )
    db.add(batch)
    await db.commit()
    batch_id = batch.id
    with pytest.raises(ValidationFailure, match="already assigned"):
        await commit_import_batch(db, actor, workspace_id, batch_id)
    await db.rollback()
    assert await db.scalar(select(func.count()).select_from(Item)) == 0
    assert (await db.get(ImportBatch, batch_id)).status == "ready"
