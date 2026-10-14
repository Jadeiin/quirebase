from __future__ import annotations

import random
from uuid import uuid4

import pytest
from item_helpers import contributor
from sqlalchemy import func, select
from workspace_helpers import provision_initial_workspace

from quirebase.audit import record_event
from quirebase.core.errors import ValidationFailure
from quirebase.library import (
    commit_import_batch,
    create_item,
    find_duplicates,
    regenerate_citation_key,
    revise_item_metadata,
    search_library,
)
from quirebase.models import AuditEvent, ImportBatch, Item, User
from quirebase.operations.workflows import dispatch_maintenance_workflow, dispatch_workspace_reindex

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


async def _owner(db):
    actor = User(username="limits-owner", password_hash="unused", role="administrator")
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    await db.commit()
    return (actor, workspace.id)


@pytest.mark.parametrize("value", ["2024", "2024-02", "2024-02-29"])
async def test_publication_date_preserves_its_precision(persistence_db, value):
    actor, workspace_id = await _owner(persistence_db)
    created = await create_item(
        persistence_db,
        actor,
        workspace_id,
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Precision",
            "date_published": value,
        },
    )
    item = await persistence_db.get(Item, created.item_id)
    assert item.work.get("date_published") == value


@pytest.mark.parametrize("value", ["0000", "2023-02-29", "2024-13", "2024-2", "Spring 2024"])
async def test_manual_publication_date_rejects_invalid_or_free_text_values(persistence_db, value):
    actor, workspace_id = await _owner(persistence_db)
    with pytest.raises(ValidationFailure):
        await create_item(
            persistence_db,
            actor,
            workspace_id,
            {
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": "Invalid",
                "date_published": value,
            },
        )
    assert await persistence_db.scalar(select(func.count()).select_from(Item)) == 0


async def test_json_contributors_preserve_long_unicode_names(persistence_db):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    result = await create_item(
        db,
        actor,
        workspace_id,
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Long name",
            "contributors": (contributor("ﬃ" * 150, "研究者" * 100),),
        },
    )
    item = await db.get(Item, result.item_id)
    assert item.work["contributors"][0]["person"]["family_name"] == "ﬃ" * 150
    assert item.work["contributors"][0]["person"]["given_name"] == "研究者" * 100
    result = await revise_item_metadata(
        db,
        actor,
        workspace_id,
        result.item_id,
        result.version,
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Updated",
            "contributors": (contributor("ﬃ" * 151, "研究者" * 100),),
        },
    )
    await db.refresh(item)
    assert item.version == 2
    assert item.work["contributors"][0]["person"]["family_name"] == "ﬃ" * 151


@pytest.mark.parametrize("entities", [False, True], ids=["unicode", "html-entities"])
async def test_title_limit_counts_visible_text_and_allows_rich_storage(persistence_db, entities):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    rng = random.Random(20261009)
    visible = (
        "&" * 1000
        if entities
        else "".join(chr(codepoint) for codepoint in rng.sample(range(19968, 40959), 1000))
    )
    title = "<i>" + ("&amp;" * 1000 if entities else visible) + "</i>"
    result = await create_item(
        db, actor, workspace_id, {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": title}
    )
    item = await db.get(Item, result.item_id)
    assert item.work.get("title") == title
    assert len(title.encode()) > 2704
    with pytest.raises(ValidationFailure, match="title is too long"):
        await revise_item_metadata(
            db,
            actor,
            workspace_id,
            result.item_id,
            result.version,
            {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "<i>" + visible + "X</i>"},
        )
    item = await db.get(Item, result.item_id)
    assert (item.work.get("title"), item.version) == (title, 1)


@pytest.mark.parametrize("origin", ["manual", "import"])
@pytest.mark.parametrize("field", ["title", "citation_key"])
async def test_metadata_limits_apply_to_creation_and_import(persistence_db, origin, field):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    values = {"title": {"title": "X" * 1001}, "citation_key": {"citation_key": "K" * 129}}[field]
    expected = {"title": "title is too long", "citation_key": "Citation key is too long"}[field]
    if origin == "manual":
        with pytest.raises(ValidationFailure, match=expected):
            await create_item(
                db,
                actor,
                workspace_id,
                {
                    "id": f"urn:uuid:{uuid4()}",
                    "type": "Document",
                    "title": values.get("title", "Rejected"),
                },
                citation_key=values.get("citation_key"),
            )
    else:
        record = {"title": "Rejected"}
        record.update(
            {"title": {"title": "X" * 1001}, "citation_key": {"citation_key": "K" * 129}}[field]
        )
        batch = ImportBatch(
            workspace_id=workspace_id,
            actor_id=actor.id,
            file_format="bibtex",
            records=[
                {
                    "work": {
                        "id": f"urn:uuid:{uuid4()}",
                        "type": "Document",
                        "title": record["title"],
                    },
                    "citation_key": record.get("citation_key"),
                }
            ],
            errors=[],
        )
        db.add(batch)
        await db.commit()
        batch_id = batch.id
        with pytest.raises(ValidationFailure, match=expected):
            await commit_import_batch(db, actor, workspace_id, batch_id)
        await db.rollback()
        batch = await db.get(ImportBatch, batch_id)
        assert batch.status == "ready"
        assert batch.committed_item_ids is None
    assert await db.scalar(select(func.count()).select_from(Item)) == 0


async def test_explicit_citation_key_accepts_128_characters(persistence_db):
    actor, workspace_id = await _owner(persistence_db)
    result = await create_item(
        persistence_db,
        actor,
        workspace_id,
        {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Explicit key"},
        citation_key="K" * 128,
    )
    item = await persistence_db.get(Item, result.item_id)
    assert item.citation_key == "K" * 128


async def test_title_search_sort_and_duplicate_results(persistence_db):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    titles = ["Spectral graphs", "Algebraic methods", "Spectral <i>graphs</i>"]
    ids = []
    for title in titles:
        result = await create_item(
            db,
            actor,
            workspace_id,
            {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": title},
        )
        ids.append(result.item_id)
    records, total = await search_library(db, actor, workspace_id, sort="title")
    assert total == 3
    assert [item.work.get("title") for item in records] == sorted(titles)
    matches, total = await search_library(db, actor, workspace_id, q="spectral", sort="title")
    assert total == 2
    assert {item.id for item in matches} == {ids[0], ids[2]}
    duplicates = await find_duplicates(db, actor, workspace_id, "title")
    assert len(duplicates) == 1
    assert {item.id for item in duplicates[0]} == {ids[0], ids[2]}


@pytest.mark.parametrize("origin", ["regenerate", "import"])
async def test_generated_citation_key_preserves_year_and_title_with_long_names(
    persistence_db, origin
):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    title = "<sup>" + "T" * 300 + "</sup>"
    if origin == "regenerate":
        result = await create_item(
            db,
            actor,
            workspace_id,
            {
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": title,
                "date_published": "2026",
                "contributors": (contributor("L" * 120),),
            },
        )
        await regenerate_citation_key(db, actor, workspace_id, result.item_id)
        item = await db.get(Item, result.item_id)
    else:
        batch = ImportBatch(
            workspace_id=workspace_id,
            actor_id=actor.id,
            file_format="bibtex",
            records=[
                {
                    "work": {
                        "id": f"urn:uuid:{uuid4()}",
                        "type": "Document",
                        "title": title,
                        "date_published": "2026",
                        "contributors": [contributor("L" * 120)],
                    }
                }
            ],
            errors=[],
        )
        db.add(batch)
        await db.commit()
        item_ids = await commit_import_batch(db, actor, workspace_id, batch.id)
        item = await db.get(Item, item_ids[0])
    assert item.citation_key == "L" + "l" * 63 + "2026" + "T" + "t" * 59


@pytest.mark.parametrize("operation", ["check_objects", "reindex"])
async def test_maintenance_keeps_complete_workflow_id_in_audit(
    persistence_db, fake_durable_operations, operation
):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    if operation == "check_objects":
        workflow_id = await dispatch_maintenance_workflow(db, actor, operation)
    else:
        workflow_id = await dispatch_workspace_reindex(db, actor, workspace_id)
    audit = await db.scalar(select(AuditEvent).where(AuditEvent.target_id == workflow_id))
    assert audit is not None
    assert len(workflow_id) == (62 if operation == "check_objects" else 93)
    assert fake_durable_operations.enqueues[-1]["workflow_id"] == audit.target_id


async def test_audit_target_ids_have_a_bounded_protocol(persistence_db):
    db = persistence_db
    target_id = "workflow:" + "x" * 246
    record_event(db, None, "test.protocol", "workflow", target_id)
    await db.commit()
    event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "test.protocol"))
    assert event.target_id == target_id
    with pytest.raises(ValidationFailure, match="audit target ID is too long"):
        record_event(db, None, "test.rejected", "workflow", target_id + "x")
    assert await db.scalar(select(func.count()).select_from(AuditEvent)) == 1
