from __future__ import annotations

from uuid import uuid4

import pytest
from inquiro.bibliography import builtin_style_xml
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.audit import record_event
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable, ValidationFailure
from quirebase.library import Contributor, ExternalIdentifier, ItemMetadata, create_item
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
    SystemSetting,
    Tag,
    User,
)
from quirebase.operations.settings import RuntimeSettingsService, update_runtime_settings


@pytest.fixture
async def persistence_actor(async_db):
    actor = User(username="persistence-owner", password_hash="unused", role="administrator")
    async_db.add(actor)
    await async_db.flush()
    await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    return actor


@pytest.mark.anyio
async def test_setting_bulk_writes_refresh_loaded_values_and_share_caller_rollback(
    async_db, async_session_factory, persistence_actor
):
    actor_id = persistence_actor.id
    await update_runtime_settings(async_db, persistence_actor, {"session_days": 30})
    loaded = await async_db.get(SystemSetting, "session_days")
    service = RuntimeSettingsService(async_db)
    await service.store(
        actor_id, {"session_days": 45, "metadata_contact_email": " new@example.org "}
    )
    assert loaded.value == "45"
    assert loaded.updated_by == actor_id
    assert inspect(loaded).persistent and not inspect(loaded).expired
    record_event(async_db, actor_id, "test.settings", "system_settings")
    await async_db.flush()

    async with async_session_factory() as observer:
        assert (await observer.get(SystemSetting, "session_days")).value == "30"
        assert await observer.get(SystemSetting, "metadata_contact_email") is None
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == "test.settings"))
            is None
        )

    await async_db.rollback()
    async with async_session_factory() as observer:
        assert (await observer.get(SystemSetting, "session_days")).value == "30"
        assert await observer.get(SystemSetting, "metadata_contact_email") is None
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == "test.settings"))
            is None
        )


@pytest.mark.anyio
async def test_invalid_setting_batch_changes_neither_existing_keys_nor_audit(
    async_db, persistence_actor
):
    await update_runtime_settings(async_db, persistence_actor, {"session_days": 30})
    event_count = await async_db.scalar(select(func.count()).select_from(AuditEvent))
    with pytest.raises(ValidationFailure, match="positive"):
        await update_runtime_settings(
            async_db,
            persistence_actor,
            {"session_days": 45, "metadata_contact_email": "new@example.org", "max_pdf_bytes": -1},
        )
    assert (await async_db.get(SystemSetting, "session_days")).value == "30"
    assert await async_db.get(SystemSetting, "metadata_contact_email") is None
    assert await async_db.scalar(select(func.count()).select_from(AuditEvent)) == event_count


@pytest.mark.anyio
async def test_setting_savepoint_propagates_unrelated_constraint_errors(
    async_db, persistence_actor
):
    await update_runtime_settings(async_db, persistence_actor, {"session_days": 30})
    with pytest.raises(IntegrityError):
        await RuntimeSettingsService(async_db).store(
            uuid4(), {"session_days": 45, "metadata_contact_email": "new@example.org"}
        )
    assert (await async_db.get(SystemSetting, "session_days")).value == "30"
    assert await async_db.get(SystemSetting, "metadata_contact_email") is None


@pytest.mark.anyio
async def test_item_service_creation_rolls_back_search_and_audit_when_enqueue_fails(
    async_db, async_session_factory, persistence_actor, monkeypatch
):
    from quirebase.library import item_metadata

    async def unavailable(*_args, **_kwargs):
        await async_db.flush()
        raise RuntimeError("durable queue unavailable")

    monkeypatch.setattr(item_metadata, "request_item_tag_recommendation", unavailable)
    with pytest.raises(RuntimeError, match="durable queue unavailable"):
        await create_item(
            async_db,
            persistence_actor,
            fixture_workspace_id(persistence_actor),
            ItemMetadata(
                "Uncommitted Item",
                authors=(Contributor("Uncommitted", "Author"),),
                identifiers=(ExternalIdentifier("pmid", "uncommitted"),),
            ),
        )
    async with async_session_factory() as observer:
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
    async_db, async_session_factory, persistence_actor, monkeypatch, operation
):
    from quirebase.library import tags

    workspace_id = fixture_workspace_id(persistence_actor)
    tag = await get_or_create_tag(async_db, persistence_actor, workspace_id, "Original")
    await async_db.commit()
    tag_id = tag.id

    def unavailable(*args, **kwargs):
        record_event(*args, **kwargs)
        raise RuntimeError("audit projection failed")

    monkeypatch.setattr(tags, "record_event", unavailable)
    mutation = (
        rename_tag(async_db, persistence_actor, workspace_id, tag_id, "  New   Tag  ")
        if operation == "rename"
        else delete_tag(async_db, persistence_actor, workspace_id, tag_id)
    )
    with pytest.raises(RuntimeError, match="audit projection failed"):
        await mutation
    await async_db.rollback()
    async with async_session_factory() as observer:
        unchanged = await observer.get(Tag, tag_id)
        assert unchanged.name == "Original" and unchanged.normalized_name == "original"
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == f"tag.{operation}"))
            is None
        )


@pytest.mark.anyio
async def test_citation_service_validates_and_installs_inside_caller_transaction(
    async_db, async_session_factory, persistence_actor
):
    workspace_id = fixture_workspace_id(persistence_actor)
    service = CitationStyleService(async_db)
    with pytest.raises(ValidationFailure, match="not a valid citation style"):
        await service.install(workspace_id, persistence_actor.id, "Invalid", "<invalid/>")
    xml = builtin_style_xml("apa")
    assert xml is not None
    style = await service.install(workspace_id, persistence_actor.id, "  Local Style  ", xml)
    style_id = style.id
    assert style.name == "Local Style" and inspect(style).persistent
    async with async_session_factory() as observer:
        assert await observer.get(CitationStyle, style_id) is None
    await async_db.rollback()
    async with async_session_factory() as observer:
        assert await observer.get(CitationStyle, style_id) is None


@pytest.mark.anyio
async def test_citation_service_delete_rejects_foreign_workspace_identity(
    async_db, persistence_actor
):
    other = User(username="other-persistence-owner", password_hash="unused")
    async_db.add(other)
    await async_db.flush()
    await provision_initial_workspace(async_db, other)
    await async_db.commit()
    xml = builtin_style_xml("apa")
    assert xml is not None
    style = await create_custom_citation_style(
        async_db, persistence_actor, fixture_workspace_id(persistence_actor), "Local", xml
    )
    with pytest.raises(ResourceNotFound):
        await delete_custom_citation_style(async_db, other, fixture_workspace_id(other), style.id)
    assert await async_db.get(CitationStyle, style.id) is not None


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["tag_rename", "tag_delete", "citation_delete"])
async def test_service_mutations_translate_a_root_deleted_after_initial_loading(
    async_db, async_session_factory, persistence_actor, monkeypatch, operation
):
    workspace_id = fixture_workspace_id(persistence_actor)
    if operation == "citation_delete":
        xml = builtin_style_xml("apa")
        assert xml is not None
        root = await create_custom_citation_style(
            async_db, persistence_actor, workspace_id, "Vanishing", xml
        )
        repository_type, model, domain_error = (
            CitationStyleRepository,
            CitationStyle,
            ResourceNotFound,
        )
        mutation = delete_custom_citation_style(async_db, persistence_actor, workspace_id, root.id)
    else:
        root = await get_or_create_tag(async_db, persistence_actor, workspace_id, "Vanishing")
        await async_db.commit()
        repository_type, model, domain_error = TagRepository, Tag, ResourceUnavailable
        mutation = (
            rename_tag(async_db, persistence_actor, workspace_id, root.id, "New Name")
            if operation == "tag_rename"
            else delete_tag(async_db, persistence_actor, workspace_id, root.id)
        )
    root_id = root.id
    original_get = repository_type.get

    async def delete_before_get(self, *args, **kwargs):
        async with async_session_factory() as concurrent:
            await concurrent.execute(delete(model).where(model.id == root_id))
            await concurrent.commit()
        return await original_get(self, *args, **kwargs)

    monkeypatch.setattr(repository_type, "get", delete_before_get)
    with pytest.raises(domain_error, match="not found"):
        await mutation


@pytest.mark.anyio
@pytest.mark.parametrize("size", [2, 50])
async def test_import_batch_resolves_shared_authors_once_and_preserves_replay(
    async_db, persistence_actor, size
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
        async_db, persistence_actor, workspace_id, contents, "bibtex"
    )
    assert len(records) == size and errors == []
    batch_id = batch.id
    author_reads: list[str] = []

    def track_author_reads(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "FROM authors" in statement:
            author_reads.append(statement)

    engine = async_db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", track_author_reads)
    try:
        item_ids = await commit_import_batch(async_db, persistence_actor, workspace_id, batch_id)
    finally:
        event.remove(engine, "before_cursor_execute", track_author_reads)
    assert len(author_reads) == 1
    items = [await async_db.get(Item, item_id) for item_id in item_ids]
    assert [item.title for item in items] == [f"Batch item {index}" for index in range(size)]
    assert [item.doi for item in items] == [f"10.1000/{index}" for index in range(size)]
    assert await async_db.scalar(select(func.count()).select_from(Author)) == size + 1
    assert await async_db.scalar(select(func.count()).select_from(ItemAuthor)) == size * 3
    shared = await async_db.scalar(select(Author).where(Author.identity_key == "shared\x1fauthor"))
    assert (
        await async_db.scalar(
            select(func.count()).select_from(ItemAuthor).where(ItemAuthor.author_id == shared.id)
        )
        == size * 2
    )
    assert (
        await commit_import_batch(async_db, persistence_actor, workspace_id, batch_id) == item_ids
    )
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "bibliography.import")
        )
        == size
    )


@pytest.mark.anyio
async def test_item_service_merge_preserves_omissions_and_replacement_clears_links(
    async_db, persistence_actor
):
    from quirebase.library._item_service import ItemService

    service = ItemService(async_db)
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
    assert await async_db.scalar(select(func.count()).select_from(ItemAuthor)) == 2
    assert await async_db.scalar(select(func.count()).select_from(ItemIdentifier)) == 1

    assert (
        await service.replace_metadata(item, persistence_actor.id, 1, ItemMetadata("Replaced")) == 2
    )
    await async_db.refresh(item)
    assert item.title == "Replaced" and item.version == 2
    assert item.authors is None and item.editors is None
    assert item.doi is None and item.identifiers is None
    assert item.urls is None and item.keywords is None and item.bibtex_id is None
    assert await async_db.scalar(select(func.count()).select_from(ItemAuthor)) == 0
    assert await async_db.scalar(select(func.count()).select_from(ItemIdentifier)) == 0


@pytest.mark.anyio
async def test_bulk_candidate_aggregates_remain_inside_caller_rollback(
    async_db, async_session_factory, persistence_actor
):
    from quirebase.library._item_service import ItemService

    items = await ItemService(async_db).create_many_from_candidates(
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
    record_event(async_db, persistence_actor.id, "test.bulk", "item")
    await async_db.flush()
    await async_db.rollback()
    async with async_session_factory() as observer:
        for model in (Item, Author, ItemAuthor, ItemIdentifier):
            assert await observer.scalar(select(func.count()).select_from(model)) == 0
        assert (
            await observer.scalar(select(AuditEvent).where(AuditEvent.action == "test.bulk"))
            is None
        )
