from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_domain_states import assert_closed_state_constraints
from workspace_helpers import provision_initial_workspace

from quirebase.core.database import Base, async_database_url, make_async_engine
from quirebase.models import Item, User
from quirebase.search import search_index

pytestmark = pytest.mark.shared_postgres


@pytest.mark.skipif(
    not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
)
@pytest.mark.anyio
async def test_postgresql_connections_return_utc_despite_server_timezone_options():
    from datetime import timedelta

    from sqlalchemy.engine import make_url

    url = make_url(async_database_url(os.environ["QUIREBASE_TEST_POSTGRES_URL"]))
    url = url.set(drivername="postgresql").update_query_dict({"options": "-c timezone=Asia/Tokyo"})
    engine = make_async_engine(url.render_as_string(hide_password=False))
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("SHOW TIME ZONE")) == "UTC"
            timestamp = await connection.scalar(text("SELECT CURRENT_TIMESTAMP"))
            assert timestamp.utcoffset() == timedelta(0)
        # Connection initialization must not leave an unrelated open transaction.
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
)
@pytest.mark.anyio
async def test_postgresql_search_contract():
    engine = make_async_engine(os.environ["QUIREBASE_TEST_POSTGRES_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "CREATE TABLE item_search ("
                "item_id uuid PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,"
                "document tsvector NOT NULL)"
            )
        )
        await connection.execute(
            text("CREATE INDEX ix_item_search_document ON item_search USING gin(document)")
        )
        await connection.execute(
            text(
                "CREATE TABLE revision_search ("
                "revision_id uuid PRIMARY KEY REFERENCES file_revisions(id) ON DELETE CASCADE,"
                "item_id uuid NOT NULL,"
                "document tsvector NOT NULL)"
            )
        )
        await connection.execute(
            text("CREATE INDEX ix_revision_search_document ON revision_search USING gin(document)")
        )
        await connection.execute(
            text("CREATE INDEX ix_revision_search_item_id ON revision_search(item_id)")
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    username = f"contract-{uuid.uuid4()}"
    try:
        async with factory() as db:
            user = User(username=username, password_hash="unused")
            db.add(user)
            await db.flush()
            workspace = await provision_initial_workspace(db, user)
            item = Item(
                workspace_id=workspace.id,
                title="Spectral graph methods",
                abstract="Topological signal",
                created_by=user.id,
            )
            db.add(item)
            await db.flush()
            await search_index(db).index_item(db, item.id)
            assert await search_index(db).search(db, "topological") == [item.id]
            await db.rollback()
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS revision_search"))
            await connection.execute(text("DROP TABLE IF EXISTS item_search"))
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.mark.skipif(
    not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
)
@pytest.mark.anyio
async def test_postgresql_domain_state_constraints():
    engine = make_async_engine(os.environ["QUIREBASE_TEST_POSTGRES_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as db:
            await assert_closed_state_constraints(db)
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()
