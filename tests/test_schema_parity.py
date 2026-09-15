from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import CompileError

import quirebase.models  # ruff: ignore[unused-import]
from quirebase.core.config import get_settings
from quirebase.core.database import Base, async_database_url

if TYPE_CHECKING:
    from sqlalchemy import Engine, Inspector

UPGRADE_SCRIPT = """
from alembic import command
from alembic.config import Config

config = Config()
config.set_main_option("script_location", "migrations")
command.upgrade(config, "head")
"""

# Autogenerate ignores the dialect-specific search projections (see migrations/env.py), so
# the migrated schema legitimately contains them and SQLite's FTS5 shadow tables.
SEARCH_PROJECTION_TABLES = frozenset({"item_search", "revision_search"})
FTS5_SHADOW_SUFFIXES = (
    "_config",
    "_content",
    "_data",
    "_docsize",
    "_idx",
    "_segdir",
    "_segments",
    "_stat",
)
ALLOWED_EXTRA_TABLES = (
    {"alembic_version"}
    | {f"{table}{suffix}" for table in SEARCH_PROJECTION_TABLES for suffix in FTS5_SHADOW_SUFFIXES}
    | SEARCH_PROJECTION_TABLES
)


def _upgrade_database(database_url: str) -> None:
    environment = os.environ.copy()
    environment["QUIREBASE_DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-c", UPGRADE_SCRIPT],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def _metadata_schema(engine: Engine) -> dict[str, dict]:
    dialect = engine.dialect
    schema: dict[str, dict] = {}
    for table in Base.metadata.sorted_tables:
        schema[table.name] = {
            "columns": {
                column.name: (
                    str(column.type.compile(dialect=dialect)),
                    bool(column.nullable),
                    column.server_default is not None,
                )
                for column in table.columns
            },
            "primary_key": tuple(column.name for column in table.primary_key.columns),
            "foreign_keys": {
                (
                    tuple(sorted(element.parent.name for element in constraint.elements)),
                    constraint.elements[0].column.table.name,
                    tuple(sorted(element.column.name for element in constraint.elements)),
                    (constraint.ondelete or "").upper(),
                )
                for constraint in table.foreign_key_constraints
            },
            "unique": {
                tuple(sorted(column.name for column in constraint.columns))
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            },
            "indexes": {
                index.name: (bool(index.unique), tuple(column.name for column in index.columns))
                for index in table.indexes
            },
            "checks": {
                constraint.name
                for constraint in table.constraints
                if isinstance(constraint, CheckConstraint)
            },
        }
    return schema


def _type_name(column_type: object, engine: Engine) -> str:
    try:
        return str(column_type.compile(dialect=engine.dialect))
    except CompileError:
        return str(column_type)


def _reflected_schema(inspector: Inspector, engine: Engine) -> dict[str, dict]:
    schema: dict[str, dict] = {}
    for name in inspector.get_table_names():
        schema[name] = {
            "columns": {
                column["name"]: (
                    _type_name(column["type"], engine),
                    bool(column["nullable"]),
                    column.get("default") is not None,
                )
                for column in inspector.get_columns(name)
            },
            "primary_key": tuple(inspector.get_pk_constraint(name)["constrained_columns"] or ()),
            "foreign_keys": {
                (
                    tuple(sorted(constraint["constrained_columns"])),
                    constraint["referred_table"],
                    tuple(sorted(constraint["referred_columns"])),
                    (constraint["options"].get("ondelete") or "").upper(),
                )
                for constraint in inspector.get_foreign_keys(name)
            },
            "unique": {
                tuple(sorted(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(name)
            },
            "indexes": {
                index["name"]: (bool(index["unique"]), tuple(index["column_names"]))
                for index in inspector.get_indexes(name)
            },
            "checks": {constraint["name"] for constraint in inspector.get_check_constraints(name)},
        }
    return schema


def _assert_schema_matches_metadata(inspector: Inspector, engine: Engine) -> None:
    reflected = _reflected_schema(inspector, engine)
    expected = _metadata_schema(engine)
    extras = set(reflected) - set(expected) - ALLOWED_EXTRA_TABLES
    assert not extras, f"database-only tables are not tracked in metadata: {sorted(extras)}"
    for table, wanted in expected.items():
        assert table in reflected, f"migrated schema is missing table {table}"
        actual = reflected[table]
        assert actual["columns"] == wanted["columns"], f"column drift in {table}"
        assert actual["primary_key"] == wanted["primary_key"], f"primary key drift in {table}"
        assert wanted["foreign_keys"] <= actual["foreign_keys"], f"missing foreign key in {table}"
        assert wanted["unique"] <= actual["unique"], f"missing unique constraint in {table}"
        for index_name, index in wanted["indexes"].items():
            assert index_name in actual["indexes"], f"missing index {index_name} on {table}"
            assert actual["indexes"][index_name] == index, f"index drift in {index_name}"
        assert wanted["checks"] <= actual["checks"], f"missing check constraint in {table}"


def test_sqlite_schema_matches_metadata(tmp_path: Path):
    database = tmp_path / "parity.db"
    _upgrade_database(f"sqlite:///{database}")
    engine = create_engine(f"sqlite:///{database}")
    try:
        _assert_schema_matches_metadata(inspect(engine), engine)
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
)
def test_postgresql_schema_matches_metadata():
    url = make_url(async_database_url(os.environ["QUIREBASE_TEST_POSTGRES_URL"]))
    name = f"quirebase_parity_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(
        url.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    parity_url = url.set(database=name).render_as_string(hide_password=False)
    libpq_parity_url = url.set(database=name, drivername="postgresql").render_as_string(
        hide_password=False
    )
    try:
        _upgrade_database(libpq_parity_url)
        engine = create_engine(parity_url)
        try:
            _assert_schema_matches_metadata(inspect(engine), engine)
        finally:
            engine.dispose()
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin_engine.dispose()


def test_autogenerate_has_no_pending_schema_changes(tmp_path: Path, monkeypatch):
    database = tmp_path / "autogenerate.db"
    _upgrade_database(f"sqlite:///{database}")
    monkeypatch.setenv("QUIREBASE_DATABASE_URL", f"sqlite:///{database}")
    get_settings.cache_clear()
    script_location = tmp_path / "migrations"
    shutil.copytree("migrations", script_location, ignore=shutil.ignore_patterns("__pycache__"))
    config = Config()
    config.set_main_option("script_location", str(script_location))
    try:
        revision = command.revision(config, message="parity probe", autogenerate=True)
    finally:
        get_settings.cache_clear()
    source = Path(revision.path).read_text(encoding="utf-8")
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert "op." not in upgrade, f"autogenerate produced operations:\n{upgrade}"
    assert "item_search" not in source and "revision_search" not in source
