from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from advanced_alchemy.alembic.commands import AlembicCommands
from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import CompileError, IntegrityError
from sqlalchemy.orm import Session

import quirebase.models  # ruff: ignore[unused-import]
from quirebase.core.config import get_settings
from quirebase.core.database import Base, _make_database_config, async_database_url
from quirebase.models import (
    AuditEvent,
    Project,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)

if TYPE_CHECKING:
    from sqlalchemy import Engine, Inspector

MIGRATION_SCRIPT = """
import sys
from advanced_alchemy.alembic.commands import AlembicCommands
from quirebase.core.database import database_config

getattr(AlembicCommands(database_config), sys.argv[1])(sys.argv[2])
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


def _migrate_database(
    database_url: str, revision: str = "head", *, downgrade: bool = False
) -> None:
    environment = os.environ.copy()
    environment["QUIREBASE_DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-c", MIGRATION_SCRIPT, "downgrade" if downgrade else "upgrade", revision],
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
                and constraint._should_create_for_compiler(dialect.ddl_compiler(dialect, None))
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
        assert wanted["foreign_keys"] == actual["foreign_keys"], f"foreign key drift in {table}"
        assert wanted["unique"] <= actual["unique"], f"missing unique constraint in {table}"
        for index_name, index in wanted["indexes"].items():
            assert index_name in actual["indexes"], f"missing index {index_name} on {table}"
            assert actual["indexes"][index_name] == index, f"index drift in {index_name}"
        assert wanted["checks"] <= actual["checks"], f"missing check constraint in {table}"


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
            ),
        ),
    ]
)
def migration_database(request, tmp_path):
    if request.param == "sqlite":
        database_url = f"sqlite:///{tmp_path / 'parity.db'}"
        engine = create_engine(database_url)

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        try:
            yield database_url, engine
        finally:
            engine.dispose()
        return
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
        engine = create_engine(parity_url)
        try:
            yield libpq_parity_url, engine
        finally:
            engine.dispose()
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin_engine.dispose()


def test_schema_matches_metadata(migration_database):
    database_url, engine = migration_database
    _migrate_database(database_url)
    _assert_schema_matches_metadata(inspect(engine), engine)


def test_initial_schema_retains_audit_history_and_rejects_inactive_owners(migration_database):
    database_url, engine = migration_database
    _migrate_database(database_url)
    with Session(engine) as db:
        user = User(username="migration-owner", password_hash="unused")
        db.add(user)
        db.flush()
        workspace = Workspace(name="Migration Workspace", created_by=user.id)
        db.add(workspace)
        db.flush()
        owner = WorkspaceMember(
            workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner
        )
        db.add(owner)
        project = Project(workspace_id=workspace.id, name="Migration Project", created_by=user.id)
        db.add(project)
        db.flush()
        event = AuditEvent(
            action="project.history",
            target_type="project",
            workspace_id=workspace.id,
            project_id=project.id,
        )
        db.add(event)
        db.commit()
        workspace_id, project_id, event_id, owner_id = workspace.id, project.id, event.id, owner.id
        for values in (
            {"state": "suspended"},
            {"terminated_at": datetime.now(UTC)},
        ):
            with pytest.raises(IntegrityError), db.begin_nested():
                db.execute(
                    WorkspaceMember.__table__
                    .update()
                    .where(WorkspaceMember.id == owner_id)
                    .values(**values)
                )
    with engine.begin() as connection:
        assert (
            connection.scalar(
                select(AuditEvent.project_id).where(AuditEvent.id == event_id), {"id": event_id}
            )
            == project_id
        )
        connection.execute(
            Workspace.__table__.delete().where(Workspace.id == workspace_id), {"id": workspace_id}
        )
        assert (
            connection.scalar(
                select(Project.id).where(Project.id == project_id), {"id": project_id}
            )
            is None
        )
        assert (
            connection.scalar(
                select(AuditEvent.project_id).where(AuditEvent.id == event_id), {"id": event_id}
            )
            == project_id
        )

        assert (
            connection.scalar(
                select(AuditEvent.workspace_id).where(AuditEvent.id == event_id), {"id": event_id}
            )
            == workspace_id
        )


def test_initial_schema_upgrade_downgrade_roundtrip(migration_database):
    database_url, engine = migration_database
    _migrate_database(database_url)
    _migrate_database(database_url, "base", downgrade=True)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    _migrate_database(database_url)
    _assert_schema_matches_metadata(inspect(engine), engine)


def test_autogenerate_has_no_pending_schema_changes(
    migration_database, tmp_path: Path, monkeypatch
):
    database_url, _ = migration_database
    _migrate_database(database_url)
    monkeypatch.setenv("QUIREBASE_DATABASE_URL", database_url)
    get_settings.cache_clear()
    script_location = tmp_path / "migrations"
    shutil.copytree("migrations", script_location, ignore=shutil.ignore_patterns("__pycache__"))
    commands = AlembicCommands(_make_database_config(database_url))
    commands.config.set_main_option("script_location", str(script_location))
    try:
        revision = commands.revision(message="parity probe", autogenerate=True)
    finally:
        get_settings.cache_clear()
    source = Path(revision.path).read_text(encoding="utf-8")
    upgrade = source.split("def schema_upgrades()", 1)[1].split("def schema_downgrades()", 1)[0]
    assert "op." not in upgrade, f"autogenerate produced operations:\n{upgrade}"
    assert "item_search" not in source and "revision_search" not in source


def test_native_type_rendering_generates_an_executable_initial_schema(
    migration_database, tmp_path: Path, monkeypatch
):
    database_url, engine = migration_database
    monkeypatch.setenv("QUIREBASE_DATABASE_URL", database_url)
    get_settings.cache_clear()
    script_location = tmp_path / "migrations"
    script_location.mkdir()
    (script_location / "versions").mkdir()
    for name in ("env.py", "script.py.mako"):
        shutil.copyfile(Path("migrations") / name, script_location / name)
    commands = AlembicCommands(_make_database_config(database_url))
    commands.config.set_main_option("script_location", str(script_location))
    try:
        commands.revision(message="native AA types", autogenerate=True)
        commands.upgrade()
        _assert_schema_matches_metadata(inspect(engine), engine)
        commands.downgrade("base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()
        get_settings.cache_clear()
