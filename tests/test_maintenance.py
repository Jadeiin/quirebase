import asyncio
import contextlib
import hashlib
import json
import sqlite3
import sys
import zipfile

import pytest

from quirebase.core.config import get_settings
from quirebase.operations import create_backup, restore_backup, verify_backup
from quirebase.operations.maintenance import _restore_sqlite_and_objects


@pytest.mark.anyio
@pytest.mark.parametrize("target_state", ["clean", "abandoned-wal", "corrupt", "corrupt-with-wal"])
async def test_backup_verifies_and_restores_sqlite_snapshot_with_bounded_reads(
    tmp_path, monkeypatch, target_state
):
    database = tmp_path / "source.db"
    with contextlib.closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE example(value text)")
        connection.execute("INSERT INTO example VALUES ('safe')")
    monkeypatch.setenv("QUIREBASE_DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("QUIREBASE_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        archive = await create_backup(tmp_path / "backup.zip")
        read = zipfile.ZipExtFile.read

        def bounded_database_read(stream, size=-1):
            if stream.name == "database.sqlite3":
                assert 0 <= size <= 1024 * 1024, "database payload must use bounded reads"
            return read(stream, size)

        monkeypatch.setattr(zipfile.ZipExtFile, "read", bounded_database_read)
        manifest = await verify_backup(archive)
        assert manifest["database_kind"] == "sqlite"
        assert len(manifest["database_sha256"]) == 64
        if target_state in {"abandoned-wal", "corrupt-with-wal"}:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                """
import os
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute("PRAGMA journal_mode=WAL")
connection.execute("PRAGMA wal_autocheckpoint=0")
connection.execute("UPDATE example SET value='changed'")
connection.commit()
os._exit(0)
""",
                str(database),
            )
            assert await process.wait() == 0
            assert database.with_name(f"{database.name}-wal").is_file()
        if target_state.startswith("corrupt"):
            database.write_bytes(b"not a SQLite database")
        elif target_state == "clean":
            with contextlib.closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("UPDATE example SET value='changed'")
        await restore_backup(archive, force=True)
        with contextlib.closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT value FROM example").fetchone()[0] == "safe"
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_backup_restores_over_wal_target_with_different_page_size(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    for database, page_size, value in ((source, 1024, "safe"), (target, 4096, "changed")):
        with contextlib.closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(f"PRAGMA page_size={page_size}")
            connection.execute("CREATE TABLE example(value text)")
            connection.execute("INSERT INTO example VALUES (?)", (value,))
            connection.commit()
            connection.execute("PRAGMA journal_mode=WAL")
    monkeypatch.setenv("QUIREBASE_DATABASE_URL", f"sqlite:///{source}")
    monkeypatch.setenv("QUIREBASE_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        archive = await create_backup(tmp_path / "backup.zip")
        monkeypatch.setenv("QUIREBASE_DATABASE_URL", f"sqlite:///{target}")
        get_settings.cache_clear()

        await restore_backup(archive, force=True)

        with contextlib.closing(sqlite3.connect(target)) as connection:
            assert connection.execute("SELECT value FROM example").fetchone()[0] == "safe"
            assert connection.execute("PRAGMA page_size").fetchone()[0] == 1024
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_backup_verification_reports_changed_database_payload(tmp_path):
    archive = tmp_path / "backup.zip"
    manifest = {
        "format": 1,
        "database_kind": "sqlite",
        "database_file": "database.sqlite3",
        "database_sha256": hashlib.sha256(b"original database").hexdigest(),
    }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as backup:
        backup.writestr("manifest.json", json.dumps(manifest))
        backup.writestr("database.sqlite3", b"changed database")

    with pytest.raises(ValueError, match="database checksum mismatch"):
        await verify_backup(archive)


def test_restore_leaves_corrupt_target_and_sidecars_when_replacement_fails(tmp_path, monkeypatch):
    database_file = tmp_path / "backup.db"
    with contextlib.closing(sqlite3.connect(database_file)) as connection, connection:
        connection.execute("CREATE TABLE example(value text)")
        connection.execute("INSERT INTO example VALUES ('safe')")
    target = tmp_path / "target.db"
    files = {
        target: b"not a SQLite database",
        target.with_name(f"{target.name}-wal"): b"old WAL",
        target.with_name(f"{target.name}-shm"): b"old shared memory",
        target.with_name(f"{target.name}-journal"): b"old journal",
    }
    for path, content in files.items():
        path.write_bytes(content)

    def fail_replace(source, destination):
        assert destination == target
        raise PermissionError("cannot replace restore target")

    monkeypatch.setattr("os.replace", fail_replace)
    with pytest.raises(PermissionError, match="cannot replace restore target"):
        _restore_sqlite_and_objects(
            database_file, target, tmp_path / "restored-objects", tmp_path / "objects"
        )

    for path, content in files.items():
        assert path.read_bytes() == content
    assert set(tmp_path.iterdir()) == {database_file, *files}


def test_restore_does_not_replace_corrupt_target_with_an_invalid_source(tmp_path):
    database_file = tmp_path / "backup.db"
    database_file.write_bytes(b"invalid backup database")
    target = tmp_path / "target.db"
    target.write_bytes(b"original corrupt database")
    wal = target.with_name(f"{target.name}-wal")
    wal.write_bytes(b"original WAL")

    with pytest.raises(sqlite3.DatabaseError, match="not a database"):
        _restore_sqlite_and_objects(
            database_file, target, tmp_path / "restored-objects", tmp_path / "objects"
        )

    assert target.read_bytes() == b"original corrupt database"
    assert wal.read_bytes() == b"original WAL"
    assert set(tmp_path.iterdir()) == {database_file, target, wal}
