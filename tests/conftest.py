from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from quirebase.core.config import get_settings
from quirebase.core.database import Base


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIREBASE_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()
    get_settings.cache_clear()
