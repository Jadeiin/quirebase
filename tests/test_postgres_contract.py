import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_domain_states import assert_closed_state_constraints

from quirebase.core.database import Base, make_async_engine
from quirebase.models import Item, User
from quirebase.search import search_index


@pytest.mark.skipif(
    not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
)
@pytest.mark.anyio
async def test_postgresql_search_contract():
    engine = make_async_engine(os.environ["QUIREBASE_TEST_POSTGRES_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    username = f"contract-{uuid.uuid4()}"
    try:
        async with factory() as db:
            user = User(username=username, password_hash="unused")
            db.add(user)
            await db.flush()
            item = Item(
                title="Spectral graph methods", abstract="Topological signal", created_by=user.id
            )
            db.add(item)
            await db.flush()
            await search_index(db).index_item(db, item.id)
            assert await search_index(db).search(db, "topological") == [item.id]
            await db.rollback()
    finally:
        async with engine.begin() as connection:
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
