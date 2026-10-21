"""Offline compaction reclaims real SQLite pages without touching live installations."""

import contextlib
import sqlite3

import pytest
from typer.testing import CliRunner

from quirebase import cli
from quirebase.core.config import get_settings


@pytest.fixture(autouse=True)
def configured_database(tmp_path, monkeypatch):
    database = tmp_path / "compaction.db"
    monkeypatch.setenv("QUIREBASE_DATABASE_URL", f"sqlite:///{database}")
    get_settings.cache_clear()
    yield database
    get_settings.cache_clear()


def test_cli_compaction_reclaims_deleted_pages_and_preserves_wal_mode(configured_database):
    database = configured_database
    with contextlib.closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE example(id INTEGER PRIMARY KEY, payload BLOB)")
        connection.executemany("INSERT INTO example(payload) VALUES (?)", [(b"keep" * 2048,)] * 128)
        connection.commit()
        connection.execute("DELETE FROM example WHERE id > 1")
    before = database.stat().st_size

    result = CliRunner().invoke(cli.app, ["compact-sqlite"])

    assert result.exit_code == 0, result.output
    assert "SQLite compacted" in result.output
    assert database.stat().st_size < before
    with contextlib.closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT id, payload FROM example").fetchall() == [
            (1, b"keep" * 2048)
        ]
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA freelist_count").fetchone()[0] == 0


@pytest.mark.parametrize("mode", ["DELETE", "WAL"])
def test_cli_compaction_refuses_an_active_reader(configured_database, mode):
    with contextlib.closing(sqlite3.connect(configured_database)) as connection:
        connection.execute(f"PRAGMA journal_mode={mode}")
        connection.execute("CREATE TABLE example(value TEXT)")
        connection.execute("INSERT INTO example VALUES ('keep')")
        connection.commit()
        connection.execute("BEGIN")
        connection.execute("SELECT value FROM example").fetchall()

        result = CliRunner().invoke(cli.app, ["compact-sqlite"])

        assert result.exit_code == 1
        assert "Stop all serve and worker processes" in result.output
        assert connection.execute("SELECT value FROM example").fetchall() == [("keep",)]


@pytest.mark.parametrize("database_url", ["postgresql://local/unused", "sqlite:///:memory:"])
def test_cli_compaction_refuses_other_database_targets(monkeypatch, database_url):
    monkeypatch.setenv("QUIREBASE_DATABASE_URL", database_url)
    get_settings.cache_clear()
    result = CliRunner().invoke(cli.app, ["compact-sqlite"])
    assert result.exit_code == 2
    assert "file-backed SQLite" in result.output


def test_cli_compaction_does_not_create_a_missing_database(configured_database):
    result = CliRunner().invoke(cli.app, ["compact-sqlite"])
    assert result.exit_code == 2
    assert "does not exist" in result.output
    assert not configured_database.exists()
