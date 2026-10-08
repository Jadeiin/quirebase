from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from inquiro.bibliography import builtin_style_xml
from sqlalchemy import delete, event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.access import resolve_workspace_context
from quirebase.audit import record_event
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable, ValidationFailure
from quirebase.library import (
    Contributor,
    ExternalIdentifier,
    ItemMetadata,
    ItemMetadataData,
    ItemOverviewData,
    ItemSection,
    create_item,
    item_sections,
    open_item_section,
)
from quirebase.library._persistence import ItemReadRepository, ItemTagRepository
from quirebase.library.citations import (
    CitationStyleRepository,
    CitationStyleService,
    create_custom_citation_style,
    delete_custom_citation_style,
)
from quirebase.library.tags import TagRepository, delete_tag, get_or_create_tag, rename_tag
from quirebase.models import (
    AuditEvent,
    Author,
    CitationStyle,
    Item,
    ItemAuthor,
    ItemIdentifier,
    ItemRead,
    ItemTag,
    Project,
    ProjectItem,
    SystemSetting,
    Tag,
    User,
)
from quirebase.operations.settings import RuntimeSettingsService, update_runtime_settings
from quirebase.projects._persistence import ProjectItemRepository

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
        Item(workspace_id=workspace_id, title=f"Batch item {index}", created_by=actor.id)
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
    root_id, actor_id = root.id, actor.id

    async def add(ids):
        if kind == "tag":
            _assignments, created_ids = await ItemTagRepository(session=db).assign_many(
                workspace_id, ids, root_id
            )
            return len(created_ids)
        return await ProjectItemRepository(session=db).add_missing(
            workspace_id, root_id, ids, actor_id
        )

    return item_ids, add, ItemTag if kind == "tag" else ProjectItem, root_id


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
        # Bound the write count: crossing a batch boundary must not become
        # one statement or savepoint per Item.
        assert len(inserts) == 2
        assert await add(item_ids) == 0
        assert len(inserts) == 2
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
    # This missing Item sorts after every existing root, so the first chunk
    # succeeds before a later chunk fails its lineage foreign key.
    with pytest.raises(IntegrityError) as failure:
        await add([*item_ids, UUID(int=(1 << 128) - 1)])
    assert await persistence_db.scalar(select(func.count()).select_from(model)) == 0
    # Keep the failure traceback alive: rolled-back ORM results must not remain
    # readable as phantom links through Session.get()'s identity-map fast path.
    if kind == "tag":
        assert await persistence_db.get(ItemTag, (min(item_ids), root_id)) is None
    assert failure.value is not None
    # Recovery preserves the caller's transaction for a subsequent valid write.
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
    item = Item(workspace_id=workspace_id, title="Concurrent reading", created_by=actor_id)
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
            # Hold the first inserted reading row uncommitted while the other
            # section attempts to write the same user/Item reading record.
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
    item = Item(workspace_id=workspace_id, title="Reading order", created_by=actor_id)
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
    persistence_db, persistence_sessions, persistence_actor
):
    workspace_id = fixture_workspace_id(persistence_actor)
    actor_id = persistence_actor.id
    item = Item(workspace_id=workspace_id, title="Uncommitted reading", created_by=actor_id)
    persistence_db.add(item)
    await persistence_db.commit()
    item_id = item.id
    await ItemReadRepository(session=persistence_db).record_reading(
        workspace_id, actor_id, item_id, datetime.now(UTC)
    )
    async with persistence_sessions() as observer:
        assert await observer.get(ItemRead, (actor_id, item_id)) is None
    await persistence_db.rollback()
    async with persistence_sessions() as observer:
        assert await observer.get(ItemRead, (actor_id, item_id)) is None


@pytest.mark.anyio
@pytest.mark.parametrize("existing", [False, True])
async def test_item_reading_propagates_foreign_workspace_constraint_errors(
    persistence_db, persistence_actor, existing
):
    workspace_id = fixture_workspace_id(persistence_actor)
    actor_id = persistence_actor.id
    item = Item(workspace_id=workspace_id, title="Scoped reading", created_by=actor_id)
    persistence_db.add(item)
    await persistence_db.commit()
    item_id = item.id
    read_at = datetime.now(UTC)
    repository = ItemReadRepository(session=persistence_db)
    if existing:
        await repository.record_reading(workspace_id, actor_id, item_id, read_at)
        await persistence_db.commit()

    with pytest.raises(IntegrityError):
        await repository.record_reading(uuid4(), actor_id, item_id, read_at + timedelta(seconds=1))
    # Savepoint recovery leaves the caller's transaction usable even when the
    # insert failed for lineage rather than a recoverable concurrent reading.
    await repository.record_reading(workspace_id, actor_id, item_id, read_at)
    read = await persistence_db.get(ItemRead, (actor_id, item_id))
    assert (read.workspace_id, read.last_read_at) == (workspace_id, read_at)


@pytest.mark.anyio
async def test_setting_bulk_writes_refresh_loaded_values_and_share_caller_rollback(
    persistence_db, persistence_sessions, persistence_actor
):
    actor_id = persistence_actor.id
    await update_runtime_settings(persistence_db, persistence_actor, {"session_days": 30})
    loaded = await persistence_db.get(SystemSetting, "session_days")
    service = RuntimeSettingsService(persistence_db)
    await service.store(
        actor_id, {"session_days": 45, "metadata_contact_email": " new@example.org "}
    )
    assert loaded.value == "45"
    assert loaded.updated_by == actor_id
    assert inspect(loaded).persistent and not inspect(loaded).expired
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
    persistence_db, persistence_actor
):
    await update_runtime_settings(persistence_db, persistence_actor, {"session_days": 30})
    with pytest.raises(IntegrityError):
        await RuntimeSettingsService(persistence_db).store(
            uuid4(), {"session_days": 45, "metadata_contact_email": "new@example.org"}
        )
    assert (await persistence_db.get(SystemSetting, "session_days")).value == "30"
    assert await persistence_db.get(SystemSetting, "metadata_contact_email") is None


@pytest.mark.anyio
async def test_item_service_creation_rolls_back_search_and_audit_when_enqueue_fails(
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
            ItemMetadata(
                "Uncommitted Item",
                authors=(Contributor("Uncommitted", "Author"),),
                identifiers=(ExternalIdentifier("pmid", "uncommitted"),),
            ),
        )
    async with persistence_sessions() as observer:
        for model in (Item, Author, ItemAuthor, ItemIdentifier):
            assert await observer.scalar(select(func.count()).select_from(model)) == 0
        assert await observer.scalar(text("SELECT count(*) FROM item_search")) == 0
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == "item.create"))
            is None
        )


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["rename", "delete"])
async def test_tag_service_mutation_and_audit_rollback_together(
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
async def test_citation_service_validates_and_installs_inside_caller_transaction(
    persistence_db, persistence_sessions, persistence_actor
):
    workspace_id = fixture_workspace_id(persistence_actor)
    service = CitationStyleService(persistence_db)
    with pytest.raises(ValidationFailure, match="not a valid citation style"):
        await service.install(workspace_id, persistence_actor.id, "Invalid", "<invalid/>")
    xml = builtin_style_xml("apa")
    assert xml is not None
    style = await service.install(workspace_id, persistence_actor.id, "  Local Style  ", xml)
    style_id = style.id
    assert style.name == "Local Style" and inspect(style).persistent
    async with persistence_sessions() as observer:
        assert await observer.get(CitationStyle, style_id) is None
    await persistence_db.rollback()
    async with persistence_sessions() as observer:
        assert await observer.get(CitationStyle, style_id) is None


@pytest.mark.anyio
async def test_citation_service_delete_rejects_foreign_workspace_identity(
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
async def test_service_mutations_translate_a_missing_root_on_repository_reread(
    persistence_db, persistence_actor, monkeypatch, operation
):
    workspace_id = fixture_workspace_id(persistence_actor)
    if operation == "citation_delete":
        xml = builtin_style_xml("apa")
        assert xml is not None
        root = await create_custom_citation_style(
            persistence_db, persistence_actor, workspace_id, "Vanishing", xml
        )
        repository_type, model, domain_error = (
            CitationStyleRepository,
            CitationStyle,
            ResourceNotFound,
        )
        mutation = delete_custom_citation_style(
            persistence_db, persistence_actor, workspace_id, root.id
        )
    else:
        root = await get_or_create_tag(persistence_db, persistence_actor, workspace_id, "Vanishing")
        await persistence_db.commit()
        repository_type, model, domain_error = TagRepository, Tag, ResourceUnavailable
        mutation = (
            rename_tag(persistence_db, persistence_actor, workspace_id, root.id, "New Name")
            if operation == "tag_rename"
            else delete_tag(persistence_db, persistence_actor, workspace_id, root.id)
        )
    root_id = root.id
    original_get = repository_type.get

    async def delete_before_get(self, *args, **kwargs):
        # Inject a missing row at the reread boundary. This tests error translation;
        # concurrent root deletion/locking is covered by controlled PostgreSQL schedules.
        await persistence_db.execute(delete(model).where(model.id == root_id))
        return await original_get(self, *args, **kwargs)

    monkeypatch.setattr(repository_type, "get", delete_before_get)
    with pytest.raises(domain_error, match="not found"):
        await mutation


@pytest.mark.anyio
@pytest.mark.parametrize("size", [2, 50])
async def test_import_batch_resolves_shared_authors_once_and_preserves_replay(
    persistence_db, persistence_actor, size
):
    from sqlalchemy import event

    from quirebase.library import commit_import_batch, stage_import_batch

    workspace_id = fixture_workspace_id(persistence_actor)
    contents = "\n".join(
        f"@article{{entry{index}, title={{Batch item {index}}}, "
        f"author={{Shared, Author and Writer{index}, Name}}, "
        f"editor={{SHARED, AUTHOR}}, year={{2026}}, doi={{10.1000/{index}}}}}"
        for index in range(size)
    ).encode()
    batch, records, errors = await stage_import_batch(
        persistence_db, persistence_actor, workspace_id, contents, "bibtex"
    )
    assert len(records) == size and errors == []
    batch_id = batch.id
    author_reads: list[str] = []

    def track_author_reads(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "FROM authors" in statement:
            author_reads.append(statement)

    engine = persistence_db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", track_author_reads)
    try:
        item_ids = await commit_import_batch(
            persistence_db, persistence_actor, workspace_id, batch_id
        )
    finally:
        event.remove(engine, "before_cursor_execute", track_author_reads)
    assert len(author_reads) == 1
    items = [await persistence_db.get(Item, item_id) for item_id in item_ids]
    assert [item.title for item in items] == [f"Batch item {index}" for index in range(size)]
    assert [item.doi for item in items] == [f"10.1000/{index}" for index in range(size)]
    assert await persistence_db.scalar(select(func.count()).select_from(Author)) == size + 1
    assert await persistence_db.scalar(select(func.count()).select_from(ItemAuthor)) == size * 3
    shared = await persistence_db.scalar(
        select(Author).where(Author.identity_key == "shared\x1fauthor")
    )
    assert (
        await persistence_db.scalar(
            select(func.count()).select_from(ItemAuthor).where(ItemAuthor.author_id == shared.id)
        )
        == size * 2
    )
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
async def test_item_service_merge_preserves_omissions_and_replacement_clears_links(
    persistence_db, persistence_actor
):
    from quirebase.library._item_service import ItemService

    service = ItemService(persistence_db)
    item = await service.create_from_metadata(
        fixture_workspace_id(persistence_actor),
        persistence_actor.id,
        ItemMetadata(
            "Original",
            authors=(Contributor("Shared", "Author"),),
            editors=(Contributor("Shared", "Author"),),
            doi="10.1000/original",
            identifiers=(ExternalIdentifier("pmid", "original"),),
            urls=("https://example.com/original",),
            keywords=("original",),
            bibtex_key="UserSelectedKey",
        ),
    )
    await service.merge_candidate(item, {"title": "Merged", "keywords": "new"})
    assert item.title == "Merged"
    assert item.authors == "Shared, Author" and item.editors == "Shared, Author"
    assert item.doi == "10.1000/original" and item.bibtex_id == "UserSelectedKey"
    assert item.urls == "https://example.com/original" and item.keywords == "original; new"
    assert await persistence_db.scalar(select(func.count()).select_from(ItemAuthor)) == 2
    assert await persistence_db.scalar(select(func.count()).select_from(ItemIdentifier)) == 1

    assert (
        await service.replace_metadata(item, persistence_actor.id, 1, ItemMetadata("Replaced")) == 2
    )
    await persistence_db.refresh(item)
    assert item.title == "Replaced" and item.version == 2
    assert item.authors is None and item.editors is None
    assert item.doi is None and item.identifiers is None
    assert item.urls is None and item.keywords is None and item.bibtex_id is None
    assert await persistence_db.scalar(select(func.count()).select_from(ItemAuthor)) == 0
    assert await persistence_db.scalar(select(func.count()).select_from(ItemIdentifier)) == 0


@pytest.mark.anyio
async def test_bulk_candidate_aggregates_remain_inside_caller_rollback(
    persistence_db, persistence_sessions, persistence_actor
):
    from quirebase.library._item_service import ItemService

    items = await ItemService(persistence_db).create_many_from_candidates(
        fixture_workspace_id(persistence_actor),
        persistence_actor.id,
        [
            {"title": "First", "authors": "Shared, Author", "identifiers": {"pmid": "first"}},
            {"title": "Second", "editors": "Shared, Author", "doi": "10.1000/second"},
        ],
    )
    assert len(items) == 2
    for item in items:
        assert inspect(item).persistent and not inspect(item).expired
    record_event(persistence_db, persistence_actor.id, "test.bulk", "item")
    await persistence_db.flush()
    await persistence_db.rollback()
    async with persistence_sessions() as observer:
        for model in (Item, Author, ItemAuthor, ItemIdentifier):
            assert await observer.scalar(select(func.count()).select_from(model)) == 0
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == "test.bulk"))
            is None
        )
