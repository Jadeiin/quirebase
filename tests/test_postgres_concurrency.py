from __future__ import annotations

import asyncio
import json
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quirebase.core.database import Base, make_async_engine
from quirebase.library.imports import commit_import_batch
from quirebase.models import ImportBatch, Item, User

pytestmark = pytest.mark.skipif(
    not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
)


@pytest.mark.anyio
async def test_concurrent_import_confirmation_has_one_identity():
    engine = make_async_engine(os.environ["QUIREBASE_TEST_POSTGRES_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS item_search ("
                "item_id varchar(36) PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,"
                "document tsvector NOT NULL)"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS revision_search ("
                "revision_id varchar(36) PRIMARY KEY REFERENCES file_revisions(id) ON DELETE CASCADE,"
                "item_id varchar(36) NOT NULL, document tsvector NOT NULL)"
            )
        )

    try:
        async with factory() as db:
            user = User(username="pg-import-race", password_hash="unused")
            batch = ImportBatch(
                owner_id=user.id,
                file_format="bibtex",
                records=json.dumps([{"title": "one identity"}]),
                errors="[]",
            )
            db.add_all([user, batch])
            await db.commit()
            batch_id = batch.id

        async def confirm() -> list[str]:
            async with factory() as db:
                return await commit_import_batch(db, user, batch_id)

        first, second = await asyncio.gather(confirm(), confirm())
        assert first == second

        async with factory() as db:
            assert (
                await db.scalar(text("SELECT count(*) FROM items WHERE title = 'one identity'"))
                == 1
            )
            stored = await db.get(ImportBatch, batch_id)
            assert stored is not None and stored.status == "committed"
            assert await db.get(Item, first[0]) is not None
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS revision_search"))
            await connection.execute(text("DROP TABLE IF EXISTS item_search"))
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()
