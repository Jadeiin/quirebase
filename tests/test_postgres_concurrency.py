from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from dbos import AsyncSQLAlchemyDatasource
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quirebase.accounts.throttling import record_login_failure
from quirebase.core.database import Base, async_database_url, make_async_engine
from quirebase.core.errors import VersionConflict
from quirebase.core.workflows import ads
from quirebase.documents.workflows import commit_uploaded_attachment, commit_uploaded_revision
from quirebase.library.imports import commit_import_batch
from quirebase.library.item_lifecycle import begin_item_deletion
from quirebase.library.item_metadata import ItemMetadata, revise_item_metadata
from quirebase.library.tags import add_tag_to_item, set_item_tags
from quirebase.library.workflows import (
    commit_item_tag_recommendation_step,
    request_item_tag_recommendation,
)
from quirebase.models import (
    ImportBatch,
    Item,
    ItemTag,
    ItemTagRecommendation,
    LoginThrottle,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    Tag,
    User,
)
from quirebase.projects import remove_project_member, require_project_write_gate
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
        await connection.execute(text("DROP TABLE IF EXISTS item_search"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    datasource = await AsyncSQLAlchemyDatasource.create(
        async_database_url(database_url), engine=engine
    )
    ads.set_instance(datasource)
    monkeypatch.setattr("quirebase.documents.workflows.AsyncSessionLocal", factory)
    monkeypatch.setattr("quirebase.library.workflows.AsyncSessionLocal", factory)
    async with factory() as db:
        await search_index(db).ensure_schema(db)
        await db.commit()
    try:
        yield factory
    finally:
        ads.set_instance(None)
        async with engine.begin() as connection:
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


@pytest.mark.parametrize("finalizer", ["revision", "attachment"])
async def test_item_delete_wins_against_upload_finalizer(postgres_sessions, finalizer):
    user_id, item_id = await _create_user_and_item(postgres_sessions, title="Delete race")
    deletion_locked = asyncio.Event()
    finalizer_started = asyncio.Event()

    async def delete_item() -> None:
        async with postgres_sessions() as db:
            await begin_item_deletion(db, item_id, commit=False)
            deletion_locked.set()
            await finalizer_started.wait()
            await db.commit()

    async def finish_upload() -> object:
        await deletion_locked.wait()
        finalizer_started.set()
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
                1,
            )
        return await commit_uploaded_attachment(
            item_id,
            user_id,
            str(uuid4()),
            "race.bin",
            "application/octet-stream",
            None,
            {"object_key": "race/attachment.bin", "size": 20},
            1,
        )

    results = await asyncio.gather(delete_item(), finish_upload(), return_exceptions=True)
    assert results[0] is None
    assert isinstance(results[1], ValueError)
    assert "lifecycle changed" in str(results[1])


async def test_permission_revoke_wins_against_workflow_final_commit(postgres_sessions):
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
        owner_id, editor_id, item_id, project_id = owner.id, editor.id, item.id, project.id

    finalizer_started = asyncio.Event()
    async with postgres_sessions() as revocation_db:
        owner = await revocation_db.get(User, owner_id)
        assert owner is not None
        await require_project_write_gate(revocation_db, project_id)

        async def finish_upload() -> object:
            finalizer_started.set()
            return await commit_uploaded_attachment(
                item_id,
                editor_id,
                str(uuid4()),
                "revoked.bin",
                "application/octet-stream",
                None,
                {"object_key": "race/revoked.bin", "size": 20},
                1,
            )

        task = asyncio.create_task(finish_upload())
        await finalizer_started.wait()
        await remove_project_member(revocation_db, owner, project_id, editor_id)
        result = await asyncio.gather(task, return_exceptions=True)

    assert isinstance(result[0], ValueError)
    assert "no longer writable" in str(result[0])


async def test_metadata_cas_races_pdf_doi_rescan(postgres_sessions):
    from quirebase.library.identifiers import rescan_pdf_doi
    from quirebase.models import FileRevision

    user_id, item_id = await _create_user_and_item(postgres_sessions, title="Original")
    async with postgres_sessions() as db:
        db.add(
            FileRevision(
                item_id=item_id,
                object_key="race/doi.pdf",
                size=10,
                original_name="doi.pdf",
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
            return await rescan_pdf_doi(db, user, item_id, expected_version=1)

    results = await _start_together(revise, rescan)
    assert sum(isinstance(result, VersionConflict) for result in results) == 1
    async with postgres_sessions() as db:
        item = await db.get(Item, item_id)
        assert item is not None and item.version == 2
        assert (item.title, item.doi) in {
            ("Concurrent metadata", None),
            ("Original", "10.1038/s41586-020-2649-2"),
        }


async def test_tag_delta_races_whole_collection_replacement(postgres_sessions):
    user_id, item_id = await _create_user_and_item(postgres_sessions, title="Tag race")
    async with postgres_sessions() as db:
        await search_index(db).index_item(db, item_id)
        await db.commit()

    async def add_delta() -> object:
        async with postgres_sessions() as db:
            user = await db.get(User, user_id)
            assert user is not None
            return await add_tag_to_item(db, user, item_id, "Concurrent")

    async def replace_collection() -> object:
        async with postgres_sessions() as db:
            user = await db.get(User, user_id)
            assert user is not None
            return await set_item_tags(db, user, item_id, [], expected_collection_version=1)

    results = await _start_together(add_delta, replace_collection)
    assert not isinstance(results[0], BaseException)
    assert results[1] is None or isinstance(results[1], VersionConflict)
    async with postgres_sessions() as db:
        assigned = await db.scalar(select(Tag.name).join(ItemTag).where(ItemTag.item_id == item_id))
        item = await db.get(Item, item_id)
        assert assigned == "Concurrent"
        assert item is not None and item.version == 1
        assert item.tag_collection_version in {2, 3}


async def test_concurrent_import_batch_commit_returns_one_result(postgres_sessions):
    async with postgres_sessions() as db:
        user = User(username=f"import-{uuid4()}", password_hash="hash")
        db.add(user)
        await db.flush()
        batch = ImportBatch(
            created_by=user.id,
            file_format="bibtex",
            status="ready",
            records=json.dumps([{"title": "Imported once"}]),
            errors="[]",
        )
        db.add(batch)
        await db.commit()
        user_id, batch_id = user.id, batch.id

    async def commit() -> object:
        async with postgres_sessions() as db:
            user = await db.get(User, user_id)
            assert user is not None
            return await commit_import_batch(db, user, batch_id, "same-operation")

    results = await _start_together(commit, commit)
    assert not any(isinstance(result, BaseException) for result in results)
    assert results[0] == results[1]
    async with postgres_sessions() as db:
        assert len((await db.scalars(select(Item).where(Item.title == "Imported once"))).all()) == 1


async def test_stale_recommendation_and_search_commits_cannot_regress_state(postgres_sessions):
    user_id, item_id = await _create_user_and_item(postgres_sessions, title="Current search")
    async with postgres_sessions() as db:
        await search_index(db).index_item(db, item_id, source_sequence=1)
        await request_item_tag_recommendation(db, item_id, owner_id=user_id)
        await db.commit()
        recommendation = await db.scalar(
            select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
        )
        assert recommendation is not None
        token = recommendation.generation_token
        workflow_id = recommendation.workflow_id

    stale_started = asyncio.Event()
    async with postgres_sessions() as mutation_db:
        await mutation_db.execute(
            update(Item)
            .where(Item.id == item_id)
            .values(
                title="Newer search",
                aggregate_sequence=Item.aggregate_sequence + 1,
                recommendation_sequence=Item.recommendation_sequence + 1,
            )
        )

        async def commit_stale_recommendation() -> object:
            stale_started.set()
            return await commit_item_tag_recommendation_step(
                item_id,
                token,
                workflow_id,
                {"single_words": ["stale"], "phrases": []},
                1,
            )

        task = asyncio.create_task(commit_stale_recommendation())
        await stale_started.wait()
        await mutation_db.commit()
        recommendation_result = (await asyncio.gather(task, return_exceptions=True))[0]

    assert recommendation_result == {"stale": True}
    async with postgres_sessions() as fresh_db:
        await search_index(fresh_db).index_item(fresh_db, item_id, source_sequence=2)
        await fresh_db.commit()
    async with postgres_sessions() as stale_db:
        await search_index(stale_db).index_item(stale_db, item_id, source_sequence=1)
        await stale_db.commit()
        stored_sequence = await stale_db.scalar(
            text("SELECT source_sequence FROM item_search WHERE item_id = :item_id"),
            {"item_id": item_id},
        )
        assert stored_sequence == 2
        assert await search_index(stale_db).search(stale_db, "Newer") == [item_id]


async def test_login_throttle_concurrent_increment_is_atomic(postgres_sessions):
    identity = f"identity-{uuid4()}"

    async def increment() -> object:
        async with postgres_sessions() as db:
            await record_login_failure(db, identity)
            return None

    results = await _start_together(*(increment for _ in range(8)))
    assert not any(isinstance(result, BaseException) for result in results)
    async with postgres_sessions() as db:
        throttle = await db.get(LoginThrottle, identity)
        assert throttle is not None and throttle.failures == 8
