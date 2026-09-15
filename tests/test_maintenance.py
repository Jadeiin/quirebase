import contextlib
import sqlite3

import pytest

from quirebase.core.config import get_settings
from quirebase.core.database import libpq_database_url
from quirebase.operations import create_backup, restore_backup, verify_backup


def test_libpq_database_url_strips_sqlalchemy_driver_suffixes():
    assert (
        libpq_database_url("postgresql+psycopg://user:pw@host:5432/db")
        == "postgresql://user:pw@host:5432/db"
    )
    assert libpq_database_url("postgresql+psycopg2://user@host/db") == "postgresql://user@host/db"
    assert libpq_database_url("postgresql://user@host/db") == "postgresql://user@host/db"
    assert libpq_database_url("sqlite:///./quirebase.db") == "sqlite:///./quirebase.db"


@pytest.mark.anyio
async def test_backup_contains_verified_sqlite_snapshot(tmp_path, monkeypatch):
    database = tmp_path / "source.db"
    with contextlib.closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE example(value text)")
        connection.execute("INSERT INTO example VALUES ('safe')")
    monkeypatch.setenv("QUIREBASE_DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("QUIREBASE_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        archive = await create_backup(tmp_path / "backup.zip")
        manifest = await verify_backup(archive)
        assert manifest["database_kind"] == "sqlite"
        assert len(manifest["database_sha256"]) == 64
        with contextlib.closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE example SET value='changed'")
        await restore_backup(archive, force=True)
        with contextlib.closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT value FROM example").fetchone()[0] == "safe"
    finally:
        get_settings.cache_clear()
