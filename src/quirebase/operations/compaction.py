"""Explicit offline physical space reclamation for SQLite installations."""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url

from quirebase.core.config import get_settings


@dataclass(frozen=True, slots=True)
class SQLiteCompactionResult:
    database: Path
    bytes_before: int
    bytes_after: int


def _database_bytes(database: Path) -> int:
    total = 0
    for file in (database, database.with_name(f"{database.name}-wal")):
        with contextlib.suppress(FileNotFoundError):
            total += file.stat().st_size
    return total


def compact_sqlite_database() -> SQLiteCompactionResult:
    """Compact an existing SQLite file after every web and worker process has stopped.

    The exclusive connection fails immediately on contention and retains its lock
    across checkpoint and VACUUM. It cannot prove that idle application processes
    have stopped; stopping them is an explicit operator prerequisite.
    """
    url = make_url(get_settings().database_url)
    if (
        url.drivername not in {"sqlite", "sqlite+aiosqlite"}
        or not url.database
        or url.database == ":memory:"
        or url.database.startswith("file:")
    ):
        raise ValueError("compaction requires a file-backed SQLite database")
    database = Path(url.database).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {database}")
    before = _database_bytes(database)
    try:
        # mode=rw prevents a typo or concurrent file removal from creating an
        # empty database; autocommit keeps VACUUM outside an explicit transaction.
        with contextlib.closing(
            sqlite3.connect(
                f"{database.as_uri()}?mode=rw", uri=True, timeout=0, isolation_level=None
            )
        ) as connection:
            connection.execute("PRAGMA locking_mode=EXCLUSIVE")
            connection.execute("BEGIN EXCLUSIVE")
            connection.execute("COMMIT")
            for statement in (
                "PRAGMA wal_checkpoint(TRUNCATE)",
                "VACUUM",
                "PRAGMA wal_checkpoint(TRUNCATE)",
            ):
                result = connection.execute(statement)
                if statement != "VACUUM" and result.fetchone()[0]:
                    raise sqlite3.OperationalError("SQLite checkpoint is busy")
    except sqlite3.Error as error:
        raise RuntimeError(
            f"SQLite compaction failed: {error}. Stop all serve and worker processes first."
        ) from error
    return SQLiteCompactionResult(database, before, _database_bytes(database))
