from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quirebase.core.config import get_settings
from quirebase.core.database import Base, make_async_engine
from quirebase.core.storage import get_object_store


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def async_session_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIREBASE_DATA_DIR", str(tmp_path / "async-data"))
    get_settings.cache_clear()
    get_object_store.cache_clear()
    engine = make_async_engine(f"sqlite:///{tmp_path / 'async-test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()
        get_settings.cache_clear()
        get_object_store.cache_clear()


@pytest.fixture
async def async_db(async_session_factory):
    async with async_session_factory() as session:
        yield session
