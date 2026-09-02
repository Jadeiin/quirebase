from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_domain_states import assert_closed_state_constraints

from quirebase.core.database import Base, make_async_engine
from quirebase.models import Item, User
from quirebase.search import search_index

if TYPE_CHECKING:
    from types import ModuleType


def _load_dbos_migration() -> ModuleType:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0019_dbos_workflows_and_uuid_objects.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0019", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


@pytest.mark.skipif(
    not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
)
def test_postgresql_dbos_migration_drops_reflected_job_foreign_key(monkeypatch):
    engine = sa.create_engine(os.environ["QUIREBASE_TEST_POSTGRES_URL"])
    table_names = (
        "item_tag_recommendations",
        "file_revisions",
        "attachments",
        "jobs",
    )
    try:
        with engine.begin() as connection:
            for table_name in table_names:
                connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))

            metadata = sa.MetaData()
            jobs = sa.Table("jobs", metadata, sa.Column("id", sa.String(36), primary_key=True))
            recommendations = sa.Table(
                "item_tag_recommendations",
                metadata,
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column(
                    "job_id",
                    sa.String(36),
                    sa.ForeignKey(jobs.c.id, ondelete="SET NULL"),
                ),
            )
            sa.Index("ix_item_tag_recommendations_job_id", recommendations.c.job_id)
            file_revisions = sa.Table(
                "file_revisions",
                metadata,
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("sha256", sa.String(64)),
            )
            sa.Index("ix_file_revisions_sha256", file_revisions.c.sha256)
            attachments = sa.Table(
                "attachments",
                metadata,
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("sha256", sa.String(64)),
            )
            sa.Index("ix_attachments_sha256", attachments.c.sha256)
            metadata.create_all(connection)

            foreign_key = sa.inspect(connection).get_foreign_keys("item_tag_recommendations")[0]
            assert foreign_key["name"] == "item_tag_recommendations_job_id_fkey"

            migration = _load_dbos_migration()
            monkeypatch.setattr(
                migration,
                "op",
                Operations(MigrationContext.configure(connection)),
            )
            migration.upgrade()

            inspector = sa.inspect(connection)
            assert "jobs" not in inspector.get_table_names()
            assert "job_id" not in {
                column["name"] for column in inspector.get_columns("item_tag_recommendations")
            }
    finally:
        with engine.begin() as connection:
            for table_name in table_names:
                connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
        engine.dispose()


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
