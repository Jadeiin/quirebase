from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from dbos import AsyncSQLAlchemyDatasource
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quirebase.accounts.throttling import record_login_failure
from quirebase.core.database import Base, async_database_url, make_async_engine
from quirebase.core.errors import VersionConflict
from quirebase.core.workflows import ads
from quirebase.documents.workflows import commit_uploaded_attachment, commit_uploaded_revision
from quirebase.library.identifiers import rescan_pdf_doi
from quirebase.library.imports import commit_import_batch
from quirebase.library.item_metadata import ItemMetadata, revise_item_metadata
from quirebase.library.tags import add_tag_to_item, rename_tag
from quirebase.models import (
    FileRevision,
    FileRevisionProcessingState,
    ImportBatch,
    Item,
    ItemTag,
    LoginThrottle,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    Tag,
    User,
)
from quirebase.search import search_index

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
    ),
]


@pytest.fixture
async def postgres_sessions(monkeypatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ["QUIREBASE_TEST_POSTGRES_URL"]
    engine = make_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS revision_search"))
        await connection.execute(text("DROP TABLE IF EXISTS item_search"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "CREATE TABLE item_search ("
                "item_id varchar(36) PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,"
                "document tsvector NOT NULL)"
            )
        )
        await connection.execute(
            text("CREATE INDEX ix_item_search_document ON item_search USING gin(document)")
        )
        await connection.execute(
            text(
                "CREATE TABLE revision_search ("
                "revision_id varchar(36) PRIMARY KEY REFERENCES file_revisions(id) ON DELETE CASCADE,"
                "item_id varchar(36) NOT NULL, document tsvector NOT NULL)"
            )
        )
        await connection.execute(
            text("CREATE INDEX ix_revision_search_document ON revision_search USING gin(document)")
        )
        await connection.execute(
            text("CREATE INDEX ix_revision_search_item_id ON revision_search(item_id)")
        )

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    datasource = await AsyncSQLAlchemyDatasource.create(
        async_database_url(database_url), engine=engine
    )
    ads.set_instance(datasource)
    monkeypatch.setattr("quirebase.documents.workflows.AsyncSessionLocal", factory)
    try:
        yield factory
    finally:
        ads.set_instance(None)
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS revision_search"))
            await connection.execute(text("DROP TABLE IF EXISTS item_search"))
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def _start_together(
    *operations: Callable[[], Awaitable[object]],
) -> list[object]:
    ready = [asyncio.Event() for _ in operations]
    start = asyncio.Event()

    async def run(index: int, operation: Callable[[], Awaitable[object]]) -> object:
        ready[index].set()
        await start.wait()
        return await operation()

    tasks = [
        asyncio.create_task(run(index, operation)) for index, operation in enumerate(operations)
    ]
    await asyncio.gather(*(event.wait() for event in ready))
    start.set()
    return list(await asyncio.gather(*tasks, return_exceptions=True))


async def _create_user_and_item(
    factory: async_sessionmaker[AsyncSession], *, title: str
) -> tuple[str, str]:
    async with factory() as db:
        user = User(username=f"race-{uuid4()}", password_hash="hash")
        db.add(user)
        await db.flush()
        item = Item(title=title, created_by=user.id)
        db.add(item)
        await db.commit()
        return user.id, item.id


@pytest.mark.anyio
async def test_concurrent_import_confirmation_has_one_identity(postgres_sessions):
    async with postgres_sessions() as db:
        user = User(username=f"pg-import-race-{uuid4()}", password_hash="unused")
        db.add(user)
        await db.flush()
        batch = ImportBatch(
            owner_id=user.id,
            file_format="bibtex",
            records=json.dumps([{"title": "one identity"}]),
            errors="[]",
        )
        db.add(batch)
        await db.commit()
        user_id, batch_id = user.id, batch.id

    async def confirm() -> list[str]:
        async with postgres_sessions() as db:
            owner = await db.get(User, user_id)
            assert owner is not None
            return await commit_import_batch(db, owner, batch_id)

    first, second = await _start_together(confirm, confirm)
    assert first == second

    async with postgres_sessions() as db:
        assert await db.scalar(text("SELECT count(*) FROM items WHERE title = 'one identity'")) == 1
        stored = await db.get(ImportBatch, batch_id)
        assert stored is not None and stored.status == "committed"
        assert await db.get(Item, first[0]) is not None


@pytest.mark.parametrize("finalizer", ["revision", "attachment"])
async def test_item_delete_wins_against_upload_finalizer(postgres_sessions, finalizer):
    user_id, item_id = await _create_user_and_item(postgres_sessions, title="Delete race")
    deletion_db = postgres_sessions()
    item = await deletion_db.scalar(select(Item).where(Item.id == item_id).with_for_update())
    assert item is not None
    await deletion_db.delete(item)
    await deletion_db.flush()

    async def finish_upload() -> object:
        if finalizer == "revision":
            return await commit_uploaded_revision(
                item_id,
                user_id,
                "race.pdf",
                {
                    "revision_id": str(uuid4()),
                    "object_key": "race/revision.pdf",
                    "thumbnail_object_key": "race/revision.png",
                    "thumbnail_size": 10,
                    "size": 20,
                    "page_count": 1,
                    "full_text": "race",
                    "page_geometry": "[]",
                },
            )
        return await commit_uploaded_attachment(
            item_id,
            user_id,
            str(uuid4()),
            "race.bin",
            "application/octet-stream",
            None,
            {"object_key": "race/attachment.bin", "size": 20},
        )

    try:
        task = asyncio.create_task(finish_upload())
        await deletion_db.commit()
        result = await task
    except BaseException as error:
        result = error
    finally:
        await deletion_db.close()
    assert isinstance(result, ValueError)
    assert "no longer writable" in str(result)


async def test_project_member_revoke_wins_against_upload_finalizer(postgres_sessions):
    async with postgres_sessions() as db:
        owner = User(username=f"owner-{uuid4()}", password_hash="hash")
        editor = User(username=f"editor-{uuid4()}", password_hash="hash")
        db.add_all([owner, editor])
        await db.flush()
        item = Item(title="Permission race", created_by=owner.id)
        project = Project(name="Permission gate", created_by=owner.id)
        db.add_all([item, project])
        await db.flush()
        db.add_all([
            ProjectMember(project_id=project.id, user_id=owner.id, role=ProjectRole.owner),
            ProjectMember(project_id=project.id, user_id=editor.id, role=ProjectRole.editor),
            ProjectItem(project_id=project.id, item_id=item.id),
        ])
        await db.commit()
        editor_id, item_id, project_id = editor.id, item.id, project.id

    revoke_db = postgres_sessions()
    target = await revoke_db.get(ProjectMember, (project_id, editor_id))
    assert target is not None
    await revoke_db.delete(target)
    await revoke_db.flush()

    task = asyncio.create_task(
        commit_uploaded_attachment(
            item_id,
            editor_id,
            str(uuid4()),
            "revoked.bin",
            "application/octet-stream",
            None,
            {"object_key": "race/revoked.bin", "size": 20},
        )
    )
    try:
        await revoke_db.commit()
        result = await task
    except BaseException as error:
        result = error
    finally:
        await revoke_db.close()
    assert isinstance(result, ValueError)
    assert "no longer writable" in str(result)


async def test_metadata_cas_races_pdf_doi_rescan(postgres_sessions):
    user_id, item_id = await _create_user_and_item(postgres_sessions, title="Original")
    async with postgres_sessions() as db:
        db.add(
            FileRevision(
                item_id=item_id,
                object_key="race/doi.pdf",
                size=10,
                original_name="doi.pdf",
                processing_state=FileRevisionProcessingState.ready,
                full_text="doi: 10.1038/s41586-020-2649-2",
                created_by=user_id,
            )
        )
        await search_index(db).index_item(db, item_id)
        await db.commit()

    async def revise() -> object:
        async with postgres_sessions() as db:
            user = await db.get(User, user_id)
            assert user is not None
            return await revise_item_metadata(
                db, user, item_id, 1, ItemMetadata(title="Concurrent metadata")
            )

    async def rescan() -> object:
        async with postgres_sessions() as db:
            user = await db.get(User, user_id)
            assert user is not None
            return await rescan_pdf_doi(db, user, item_id)

    results = await _start_together(revise, rescan)
    conflicts = [result for result in results if isinstance(result, VersionConflict)]
    assert not any(
        isinstance(result, BaseException) and not isinstance(result, VersionConflict)
        for result in results
    ), results
    assert len(conflicts) <= 1, results
    async with postgres_sessions() as db:
        item = await db.get(Item, item_id)
        assert item is not None and item.version in {2, 3}
        assert (item.title, item.doi) in {
            ("Concurrent metadata", None),
            ("Original", "10.1038/s41586-020-2649-2"),
            ("Concurrent metadata", "10.1038/s41586-020-2649-2"),
        }


async def test_tag_rename_does_not_wait_on_item_gate(postgres_sessions):
    user_id, item_id = await _create_user_and_item(postgres_sessions, title="Tag rename race")
    async with postgres_sessions() as db:
        user = await db.get(User, user_id)
        assert user is not None
        tag = Tag(name="Before rename", created_by=user_id)
        db.add(tag)
        await db.flush()
        await add_tag_to_item(db, user, item_id, tag.name)
        tag_id = tag.id

    async with postgres_sessions() as blocker:
        await blocker.execute(select(Item).where(Item.id == item_id).with_for_update())

        async def rename() -> object:
            async with postgres_sessions() as db:
                user = await db.get(User, user_id)
                assert user is not None
                return await rename_tag(db, user, tag_id, "After rename")

        result = await asyncio.wait_for(rename(), timeout=1)
        assert not isinstance(result, BaseException)
        await blocker.commit()

    async with postgres_sessions() as db:
        renamed = await db.get(Tag, tag_id)
        assert renamed is not None and renamed.name == "After rename"
        assignment = await db.get(ItemTag, (item_id, tag_id))
        assert assignment is not None


async def test_login_throttle_concurrent_increment_is_atomic(postgres_sessions):
    identity = f"identity-{uuid4()}"

    async def increment() -> object:
        async with postgres_sessions() as db:
            await record_login_failure(db, identity)
        return None

    results = await _start_together(*(increment for _ in range(8)))
    assert not any(isinstance(result, BaseException) for result in results), results
    async with postgres_sessions() as db:
        throttle = await db.get(LoginThrottle, identity)
        assert throttle is not None and throttle.failures == 8
