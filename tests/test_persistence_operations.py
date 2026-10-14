from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from inquiro.bibliography import builtin_style_xml
from item_helpers import (
    contributor,
    stored_doi,
    work_identifier,
)
from sqlalchemy import delete, event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.access import resolve_workspace_context
from quirebase.audit import record_event
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable, ValidationFailure
from quirebase.library import (
    ItemMetadataData,
    ItemOverviewData,
    ItemSection,
    create_item,
    item_sections,
    open_item_section,
    revise_item_metadata,
)
from quirebase.library.citations import create_custom_citation_style, delete_custom_citation_style
from quirebase.library.tags import _assign_item_tags, delete_tag, get_or_create_tag, rename_tag
from quirebase.models import (
    AuditEvent,
    CitationStyle,
    Item,
    ItemRead,
    ItemTag,
    Project,
    ProjectItem,
    SystemSetting,
    Tag,
    User,
)
from quirebase.operations import settings as runtime_settings
from quirebase.operations.settings import update_runtime_settings
from quirebase.projects.workspaces import _add_missing_project_items

pytestmark = pytest.mark.shared_postgres


@pytest.fixture
async def persistence_actor(persistence_db):
    actor = User(username="persistence-owner", password_hash="unused", role="administrator")
    persistence_db.add(actor)
    await persistence_db.flush()
    await provision_initial_workspace(persistence_db, actor)
    await persistence_db.commit()
    return actor


async def _association_batch(db, actor, kind):
    workspace_id = fixture_workspace_id(actor)
    items = [
        Item(
            workspace_id=workspace_id,
            created_by=actor.id,
            work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": f"Batch item {index}"},
        )
        for index in range(501)
    ]
    root = (
        Tag(workspace_id=workspace_id, name="Batch tag", created_by=actor.id)
        if kind == "tag"
        else Project(workspace_id=workspace_id, name="Batch project", created_by=actor.id)
    )
    db.add_all([*items, root])
    await db.commit()
    item_ids = [item.id for item in items]
    root_id, actor_id = (root.id, actor.id)

    async def add(ids):
        if kind == "tag":
            created_ids = await _assign_item_tags(db, workspace_id, ids, root_id)
            return len(created_ids)
        return await _add_missing_project_items(db, workspace_id, root_id, ids, actor_id)

    return (item_ids, add, ItemTag if kind == "tag" else ProjectItem, root_id)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["tag", "project"])
async def test_association_batches_deduplicate_and_share_caller_rollback(
    persistence_db, persistence_sessions, persistence_actor, kind
):
    item_ids, add, model, _root_id = await _association_batch(
        persistence_db, persistence_actor, kind
    )
    engine = persistence_db.bind.sync_engine
    inserts = []

    def record_insert(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith(f"INSERT INTO {model.__tablename__}"):
            inserts.append(statement)

    event.listen(engine, "before_cursor_execute", record_insert)
    try:
        assert await add([*item_ids, item_ids[0]]) == len(item_ids)
        assert len(inserts) == 2
        assert await add(item_ids) == 0
        assert len(inserts) == 4
        assert await add([]) == 0
        assert len(inserts) == 4
    finally:
        event.remove(engine, "before_cursor_execute", record_insert)
    async with persistence_sessions() as observer:
        assert await observer.scalar(select(func.count()).select_from(model)) == 0
    await persistence_db.rollback()
    assert await persistence_db.scalar(select(func.count()).select_from(model)) == 0
    assert await add(item_ids[:1]) == 1
    await persistence_db.commit()
    async with persistence_sessions() as observer:
        assert await observer.scalar(select(func.count()).select_from(model)) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["tag", "project"])
async def test_association_batch_constraint_failure_rolls_back_all_chunks(
    persistence_db, persistence_actor, kind
):
    item_ids, add, model, root_id = await _association_batch(
        persistence_db, persistence_actor, kind
    )
    with pytest.raises(IntegrityError) as failure:
        await add([*item_ids, UUID(int=(1 << 128) - 1)])
    assert await persistence_db.scalar(select(func.count()).select_from(model)) == 0
    if kind == "tag":
        assert await persistence_db.get(ItemTag, (min(item_ids), root_id)) is None
    assert failure.value is not None
    assert await add(item_ids[:1]) == 1
    await persistence_db.commit()


@pytest.mark.anyio
@pytest.mark.concurrency_case("item-reading")
@pytest.mark.parametrize("first_section", [ItemSection.overview, ItemSection.metadata])
async def test_concurrent_item_sections_record_reading_once(
    persistence_db, persistence_sessions, persistence_actor, monkeypatch, first_section
):
    actor_id = persistence_actor.id
    workspace_id = fixture_workspace_id(persistence_actor)
    item = Item(
        workspace_id=workspace_id,
        created_by=actor_id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Concurrent reading"},
    )
    persistence_db.add(item)
    await persistence_db.commit()
    item_id = item.id
    first_ready, second_writing, release_commit = (asyncio.Event() for _ in range(3))
    async with persistence_sessions() as first_db, persistence_sessions() as second_db:
        first_actor = await first_db.get(User, actor_id)
        second_actor = await second_db.get(User, actor_id)
        first_context = await resolve_workspace_context(first_db, first_actor, workspace_id)
        second_context = await resolve_workspace_context(second_db, second_actor, workspace_id)
        commit = first_db.commit

        async def held_commit():
            await first_db.flush()
            first_ready.set()
            await release_commit.wait()
            await commit()

        monkeypatch.setattr(first_db, "commit", held_commit)
        connection = await second_db.connection()

        def record_write(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.startswith(("INSERT INTO item_reads", "UPDATE item_reads")):
                second_writing.set()

        event.listen(connection.sync_connection, "before_cursor_execute", record_write)
        second_section = (
            ItemSection.metadata if first_section is ItemSection.overview else ItemSection.overview
        )
        try:
            async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
                first = tasks.create_task(
                    open_item_section(first_db, first_context, item_id, first_section)
                )
                await first_ready.wait()
                second = tasks.create_task(
                    open_item_section(second_db, second_context, item_id, second_section)
                )
                await second_writing.wait()
                release_commit.set()
        finally:
            event.remove(connection.sync_connection, "before_cursor_execute", record_write)
        views = {type(first.result()), type(second.result())}
        assert views == {ItemOverviewData, ItemMetadataData}
        assert first.result().item.id == second.result().item.id == item_id
    async with persistence_sessions() as observer:
        reads = (await observer.scalars(select(ItemRead))).all()
        assert len(reads) == 1
        assert (reads[0].user_id, reads[0].item_id, reads[0].workspace_id) == (
            actor_id,
            item_id,
            workspace_id,
        )


@pytest.mark.anyio
async def test_item_reading_retains_the_latest_timestamp(
    persistence_db, persistence_sessions, persistence_actor, monkeypatch
):
    actor_id = persistence_actor.id
    workspace_id = fixture_workspace_id(persistence_actor)
    item = Item(
        workspace_id=workspace_id,
        created_by=actor_id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Reading order"},
    )
    persistence_db.add(item)
    await persistence_db.commit()
    item_id = item.id
    started_at = datetime(2026, 10, 8, tzinfo=UTC)
    read_at = started_at
    latest_read_at = started_at
    monkeypatch.setattr(item_sections, "datetime", SimpleNamespace(now=lambda _timezone: read_at))
    for offset in (0, 1, -1):
        read_at = started_at + timedelta(seconds=offset)
        latest_read_at = max(latest_read_at, read_at)
        context = await resolve_workspace_context(persistence_db, persistence_actor, workspace_id)
        await open_item_section(persistence_db, context, item_id, ItemSection.overview)
        async with persistence_sessions() as observer:
            read = await observer.get(ItemRead, (actor_id, item_id))
            assert read.last_read_at == latest_read_at


@pytest.mark.anyio
async def test_item_reading_insert_shares_the_callers_rollback(
    persistence_db, persistence_sessions, persistence_actor, monkeypatch
):
    workspace_id = fixture_workspace_id(persistence_actor)
    actor_id = persistence_actor.id
    item = Item(
        workspace_id=workspace_id,
        created_by=actor_id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Uncommitted reading"},
    )
    persistence_db.add(item)
    await persistence_db.commit()
    item_id = item.id
    context = await resolve_workspace_context(persistence_db, persistence_actor, workspace_id)
    monkeypatch.setattr(persistence_db, "commit", AsyncMock(side_effect=persistence_db.flush))
    await open_item_section(persistence_db, context, item_id, ItemSection.metadata)
    async with persistence_sessions() as observer:
        assert await observer.get(ItemRead, (actor_id, item_id)) is None
    await persistence_db.rollback()
    async with persistence_sessions() as observer:
        assert await observer.get(ItemRead, (actor_id, item_id)) is None


@pytest.mark.anyio
@pytest.mark.parametrize("existing", [False, True])
async def test_item_reading_propagates_foreign_workspace_constraint_errors(
    persistence_db, persistence_actor, monkeypatch, existing
):
    workspace_id = fixture_workspace_id(persistence_actor)
    actor_id = persistence_actor.id
    item = Item(
        workspace_id=workspace_id,
        created_by=actor_id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Scoped reading"},
    )
    persistence_db.add(item)
    await persistence_db.commit()
    item_id = item.id
    read_at = datetime.now(UTC)
    monkeypatch.setattr(item_sections, "datetime", SimpleNamespace(now=lambda _timezone: read_at))
    context = await resolve_workspace_context(persistence_db, persistence_actor, workspace_id)
    if existing:
        await open_item_section(persistence_db, context, item_id, ItemSection.metadata)
    monkeypatch.setattr(persistence_db, "commit", AsyncMock(side_effect=persistence_db.flush))
    monkeypatch.setattr(persistence_db, "rollback", AsyncMock())
    execute = persistence_db.execute

    async def invalid_lineage(statement, *args, **kwargs):
        if getattr(getattr(statement, "table", None), "name", None) == ItemRead.__tablename__:
            statement = statement.values(workspace_id=uuid4())
        return await execute(statement, *args, **kwargs)

    monkeypatch.setattr(persistence_db, "execute", invalid_lineage)
    with pytest.raises(IntegrityError):
        await open_item_section(persistence_db, context, item_id, ItemSection.metadata)
    monkeypatch.setattr(persistence_db, "execute", execute)
    await open_item_section(persistence_db, context, item_id, ItemSection.metadata)
    read = await persistence_db.get(ItemRead, (actor_id, item_id))
    assert (read.workspace_id, read.last_read_at) == (workspace_id, read_at)


@pytest.mark.anyio
async def test_setting_bulk_writes_refresh_loaded_values_and_share_caller_rollback(
    persistence_db, persistence_sessions, persistence_actor, monkeypatch
):
    actor_id = persistence_actor.id
    await update_runtime_settings(persistence_db, persistence_actor, {"session_days": 30})
    loaded = await persistence_db.get(SystemSetting, "session_days")
    monkeypatch.setattr(persistence_db, "commit", AsyncMock(side_effect=persistence_db.flush))
    await update_runtime_settings(
        persistence_db,
        persistence_actor,
        {"session_days": 45, "metadata_contact_email": " new@example.org "},
    )
    assert loaded.value == "45"
    assert loaded.updated_by == actor_id
    assert inspect(loaded).persistent and (not inspect(loaded).expired)
    record_event(persistence_db, actor_id, "test.settings", "system_settings")
    await persistence_db.flush()
    async with persistence_sessions() as observer:
        assert (await observer.get(SystemSetting, "session_days")).value == "30"
        assert await observer.get(SystemSetting, "metadata_contact_email") is None
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == "test.settings"))
            is None
        )
    await persistence_db.rollback()
    async with persistence_sessions() as observer:
        assert (await observer.get(SystemSetting, "session_days")).value == "30"
        assert await observer.get(SystemSetting, "metadata_contact_email") is None
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == "test.settings"))
            is None
        )


@pytest.mark.anyio
async def test_invalid_setting_batch_changes_neither_existing_keys_nor_audit(
    persistence_db, persistence_actor
):
    await update_runtime_settings(persistence_db, persistence_actor, {"session_days": 30})
    event_count = await persistence_db.scalar(select(func.count()).select_from(AuditEvent))
    with pytest.raises(ValidationFailure, match="positive"):
        await update_runtime_settings(
            persistence_db,
            persistence_actor,
            {"session_days": 45, "metadata_contact_email": "new@example.org", "max_pdf_bytes": -1},
        )
    assert (await persistence_db.get(SystemSetting, "session_days")).value == "30"
    assert await persistence_db.get(SystemSetting, "metadata_contact_email") is None
    assert await persistence_db.scalar(select(func.count()).select_from(AuditEvent)) == event_count


@pytest.mark.anyio
async def test_setting_savepoint_propagates_unrelated_constraint_errors(
    persistence_db, persistence_actor, monkeypatch
):
    await update_runtime_settings(persistence_db, persistence_actor, {"session_days": 30})
    monkeypatch.setattr(
        runtime_settings,
        "require_system_action",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    with pytest.raises(IntegrityError):
        await update_runtime_settings(
            persistence_db,
            persistence_actor,
            {"session_days": 45, "metadata_contact_email": "new@example.org"},
        )
    assert (await persistence_db.get(SystemSetting, "session_days")).value == "30"
    assert await persistence_db.get(SystemSetting, "metadata_contact_email") is None


@pytest.mark.anyio
async def test_item_metadata_creation_rolls_back_search_and_audit_when_enqueue_fails(
    persistence_db, persistence_sessions, persistence_actor, monkeypatch
):
    from quirebase.library import item_metadata

    async def unavailable(*_args, **_kwargs):
        await persistence_db.flush()
        raise RuntimeError("durable queue unavailable")

    monkeypatch.setattr(item_metadata, "request_item_tag_recommendation", unavailable)
    with pytest.raises(RuntimeError, match="durable queue unavailable"):
        await create_item(
            persistence_db,
            persistence_actor,
            fixture_workspace_id(persistence_actor),
            {
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": "Uncommitted Item",
                "contributors": (contributor("Uncommitted", "Author"),),
                "identifiers": (work_identifier("pmid", "uncommitted"),),
            },
        )
    async with persistence_sessions() as observer:
        for model in (Item,):
            assert await observer.scalar(select(func.count()).select_from(model)) == 0
        assert await observer.scalar(text("SELECT count(*) FROM item_search")) == 0
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == "item.create"))
            is None
        )


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["rename", "delete"])
async def test_tag_mutation_and_audit_rollback_together(
    persistence_db, persistence_sessions, persistence_actor, monkeypatch, operation
):
    from quirebase.library import tags

    workspace_id = fixture_workspace_id(persistence_actor)
    tag = await get_or_create_tag(persistence_db, persistence_actor, workspace_id, "Original")
    await persistence_db.commit()
    tag_id = tag.id

    def unavailable(*args, **kwargs):
        record_event(*args, **kwargs)
        raise RuntimeError("audit projection failed")

    monkeypatch.setattr(tags, "record_event", unavailable)
    mutation = (
        rename_tag(persistence_db, persistence_actor, workspace_id, tag_id, "  New   Tag  ")
        if operation == "rename"
        else delete_tag(persistence_db, persistence_actor, workspace_id, tag_id)
    )
    with pytest.raises(RuntimeError, match="audit projection failed"):
        await mutation
    await persistence_db.rollback()
    async with persistence_sessions() as observer:
        unchanged = await observer.get(Tag, tag_id)
        assert unchanged.name == "Original" and unchanged.normalized_name == "original"
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == f"tag.{operation}"))
            is None
        )


@pytest.mark.anyio
async def test_citation_style_validates_and_installs_inside_caller_transaction(
    persistence_db, persistence_sessions, persistence_actor, monkeypatch
):
    workspace_id = fixture_workspace_id(persistence_actor)
    monkeypatch.setattr(persistence_db, "commit", AsyncMock(side_effect=persistence_db.flush))
    with pytest.raises(ValidationFailure, match="not a valid citation style"):
        await create_custom_citation_style(
            persistence_db, persistence_actor, workspace_id, "Invalid", "<invalid/>"
        )
    xml = builtin_style_xml("apa")
    assert xml is not None
    style = await create_custom_citation_style(
        persistence_db, persistence_actor, workspace_id, "  Local Style  ", xml
    )
    style_id = style.id
    assert style.name == "Local Style" and inspect(style).persistent
    async with persistence_sessions() as observer:
        assert await observer.get(CitationStyle, style_id) is None
    await persistence_db.rollback()
    async with persistence_sessions() as observer:
        assert await observer.get(CitationStyle, style_id) is None


@pytest.mark.anyio
async def test_citation_style_delete_rejects_foreign_workspace_identity(
    persistence_db, persistence_actor
):
    other = User(username="other-persistence-owner", password_hash="unused")
    persistence_db.add(other)
    await persistence_db.flush()
    await provision_initial_workspace(persistence_db, other)
    await persistence_db.commit()
    xml = builtin_style_xml("apa")
    assert xml is not None
    style = await create_custom_citation_style(
        persistence_db, persistence_actor, fixture_workspace_id(persistence_actor), "Local", xml
    )
    with pytest.raises(ResourceNotFound):
        await delete_custom_citation_style(
            persistence_db, other, fixture_workspace_id(other), style.id
        )
    assert await persistence_db.get(CitationStyle, style.id) is not None


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["tag_rename", "tag_delete", "citation_delete"])
async def test_mutations_translate_a_missing_root_without_success_audit(
    persistence_db, persistence_actor, operation
):
    workspace_id = fixture_workspace_id(persistence_actor)
    if operation == "citation_delete":
        xml = builtin_style_xml("apa")
        assert xml is not None
        root = await create_custom_citation_style(
            persistence_db, persistence_actor, workspace_id, "Vanishing", xml
        )
        model, domain_error = (CitationStyle, ResourceNotFound)
        mutation = delete_custom_citation_style(
            persistence_db, persistence_actor, workspace_id, root.id
        )
    else:
        root = await get_or_create_tag(persistence_db, persistence_actor, workspace_id, "Vanishing")
        await persistence_db.commit()
        model, domain_error = (Tag, ResourceUnavailable)
        mutation = (
            rename_tag(persistence_db, persistence_actor, workspace_id, root.id, "New Name")
            if operation == "tag_rename"
            else delete_tag(persistence_db, persistence_actor, workspace_id, root.id)
        )
    root_id = root.id
    await persistence_db.execute(delete(model).where(model.id == root_id))
    await persistence_db.commit()
    before = await persistence_db.scalar(select(func.count()).select_from(AuditEvent))
    with pytest.raises(domain_error, match="not found"):
        await mutation
    assert await persistence_db.scalar(select(func.count()).select_from(AuditEvent)) == before


@pytest.mark.anyio
@pytest.mark.parametrize("size", [2, 50])
async def test_import_batch_embeds_record_local_contributors_and_preserves_replay(
    persistence_db, persistence_actor, size
):
    from quirebase.library import commit_import_batch, stage_import_batch

    workspace_id = fixture_workspace_id(persistence_actor)
    contents = "\n".join(
        f"@article{{entry{index}, title={{Batch item {index}}}, author={{Shared, Author and Writer{index}, Name}}, editor={{SHARED, AUTHOR}}, year={{2026}}, doi={{10.1000/{index}}}}}"
        for index in range(size)
    ).encode()
    batch = await stage_import_batch(
        persistence_db, persistence_actor, workspace_id, contents, "bibtex"
    )
    records = batch.records
    errors = batch.errors
    assert len(records) == size and all(error.severity == "warning" for error in errors)
    batch_id = batch.id
    item_ids = await commit_import_batch(persistence_db, persistence_actor, workspace_id, batch_id)
    items = [await persistence_db.get(Item, item_id) for item_id in item_ids]
    assert [item.work.get("title") for item in items] == [
        f"Batch item {index}" for index in range(size)
    ]
    assert [stored_doi(item) for item in items] == [f"10.1000/{index}" for index in range(size)]
    assert all(item.work["contributors"][0]["person"]["family_name"] == "Shared" for item in items)
    assert all(
        next(credit for credit in item.work["contributors"] if "Editor" in credit["roles"])[
            "person"
        ]["family_name"]
        == "SHARED"
        for item in items
    )
    assert all(len(item.work["contributors"]) == 3 for item in items)
    assert (
        await commit_import_batch(persistence_db, persistence_actor, workspace_id, batch_id)
        == item_ids
    )
    assert (
        await persistence_db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "bibliography.import")
        )
        == size
    )


@pytest.mark.anyio
async def test_item_metadata_merge_preserves_omissions_and_replacement_clears_links(
    persistence_db, persistence_actor
):
    from quirebase.library.identifiers import _merge_metadata_work

    metadata = {
        "id": "https://doi.org/10.1000/original",
        "type": "JournalArticle",
        "title": "Original",
        "subjects": [{"subject": "original"}],
        "contributors": [contributor("Shared", "Author")],
        "identifiers": [work_identifier("pmid", "42")],
    }
    result = await create_item(
        persistence_db,
        persistence_actor,
        fixture_workspace_id(persistence_actor),
        metadata,
        citation_key="UserSelectedKey",
    )
    item = await persistence_db.get(Item, result.item_id)
    await _merge_metadata_work(
        persistence_db,
        persistence_actor,
        item,
        {"title": "Merged", "subjects": [{"subject": "new"}]},
    )
    assert item.work["title"] == "Merged"
    assert item.work["contributors"] == metadata["contributors"]
    assert item.work["subjects"] == [{"subject": "original"}, {"subject": "new"}]
    assert stored_doi(item) == "10.1000/original"
    assert item.citation_key == "UserSelectedKey"
    replaced = {"id": metadata["id"], "type": "Dataset", "title": "Replaced"}
    result = await revise_item_metadata(
        persistence_db,
        persistence_actor,
        item.workspace_id,
        item.id,
        1,
        replaced,
        citation_key=None,
    )
    await persistence_db.refresh(item)
    assert result.version == 2 and item.work == replaced and item.citation_key is None


@pytest.mark.anyio
async def test_bulk_candidate_aggregates_remain_inside_caller_rollback(
    persistence_db, persistence_sessions, persistence_actor
):
    from quirebase.library.identifiers import _create_items_from_candidates

    candidates = [
        {
            "id": "https://doi.org/10.1000/shared",
            "type": "Document",
            "title": title,
            "contributors": [contributor("Shared", "Author")],
        }
        for title in ("First", "Second")
    ]
    items = await _create_items_from_candidates(
        persistence_db,
        fixture_workspace_id(persistence_actor),
        persistence_actor.id,
        [{"work": candidate} for candidate in candidates],
    )
    assert len(items) == 2
    assert all(inspect(item).persistent and not inspect(item).expired for item in items)
    record_event(persistence_db, persistence_actor.id, "test.bulk", "item")
    await persistence_db.flush()
    await persistence_db.rollback()
    async with persistence_sessions() as observer:
        assert await observer.scalar(select(func.count()).select_from(Item)) == 0
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == "test.bulk"))
            is None
        )
