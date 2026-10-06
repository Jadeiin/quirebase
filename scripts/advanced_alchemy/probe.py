"""Throwaway persistence probe. Uses scratch SQLite, never the configured database.

Run from the prototype checkout:
uv run --frozen python scripts/advanced_alchemy/probe.py
"""

from __future__ import annotations

import asyncio
import json
import platform
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

import sqlalchemy
from advanced_alchemy.base import NanoIDBase, UUIDv7AuditBase
from advanced_alchemy.exceptions import NotFoundError
from advanced_alchemy.extensions.fastapi import AsyncSessionConfig, SQLAlchemyAsyncConfig
from advanced_alchemy.filters import LimitOffset
from advanced_alchemy.repository import SQLAlchemyAsyncQueryRepository, SQLAlchemyAsyncRepository
from advanced_alchemy.types import GUID, NANOID_INSTALLED
from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    and_,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError, MultipleResultsFound
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import CreateTable
from uuid_utils.compat import uuid7

from quirebase.access.context import resolve_workspace_context
from quirebase.access.project_scope import project_discovery_predicate
from quirebase.core.database import Base, make_async_engine
from quirebase.core.storage import ObjectSuffix, object_key
from quirebase.models import (
    AuditEvent,
    Item,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectParticipation,
    ProjectState,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)

HERE = Path(__file__).parent

if TYPE_CHECKING:
    from sqlalchemy import Table


class NativeBase(DeclarativeBase):
    pass


class NativeRecord(NativeBase):
    __tablename__ = "prototype_native_records"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AlchemyWorkspace(UUIDv7AuditBase):
    __tablename__ = "prototype_aa_workspaces"
    __bind_key__ = "prototype"
    name: Mapped[str] = mapped_column(String(100))


class AlchemyRecord(UUIDv7AuditBase):
    __tablename__ = "prototype_aa_records"
    __bind_key__ = "prototype"
    __table_args__ = (UniqueConstraint("workspace_id", "id"),)
    workspace_id: Mapped[UUID] = mapped_column(GUID, ForeignKey("prototype_aa_workspaces.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(100))


class AlchemyLink(NativeBase):
    __tablename__ = "prototype_aa_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "record_id"],
            [AlchemyRecord.__table__.c.workspace_id, AlchemyRecord.__table__.c.id],
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(GUID)
    record_id: Mapped[UUID] = mapped_column(GUID)


class NanoRecord(NanoIDBase):
    __tablename__ = "prototype_nano_records"
    __bind_key__ = "prototype_nano"


# BasicAttributes on the shared Base satisfies AA repository typing bounds.
class ProjectReadRepository(SQLAlchemyAsyncRepository[Project]):
    model_type = Project


class WorkspaceReadRepository(SQLAlchemyAsyncRepository[Workspace]):
    model_type = Workspace


async def probe() -> dict[str, Any]:
    engine = make_async_engine("sqlite+aiosqlite:///:memory:")
    config = SQLAlchemyAsyncConfig(
        engine_instance=engine,
        metadata=Base.metadata,
        session_config=AsyncSessionConfig(expire_on_commit=False),
        commit_mode="manual",
        enable_file_object_listener=False,
        enable_touch_updated_timestamp_listener=False,
    )
    report: dict[str, Any] = {
        "environment": {
            "python": platform.python_version(),
            "sqlalchemy": sqlalchemy.__version__,
            "advanced_alchemy": "1.11.0",
            "sqlite_runtime": True,
            "postgres_runtime": False,
        },
        "integration": {
            "existing_engine": config.get_engine() is engine,
            "existing_metadata": config.metadata is Base.metadata,
            "commit_mode": config.commit_mode,
        },
    }
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(AlchemyWorkspace.metadata.create_all)
        await connection.run_sync(NativeBase.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as db:
        native = NativeRecord()
        root = AlchemyWorkspace(name="UUID root")
        db.add_all([native, root])
        await db.flush()
        record = AlchemyRecord(workspace_id=root.id, name="Before")
        db.add(record)
        await db.flush()
        db.add(AlchemyLink(id=1, workspace_id=root.id, record_id=record.id))
        await db.commit()
        record_id, root_id, native_id = record.id, root.id, native.id
        db.expunge_all()
        reloaded = await db.get(AlchemyRecord, record_id)
        native_reloaded = await db.get(NativeRecord, native_id)
        if reloaded is None or native_reloaded is None:
            raise RuntimeError("Scratch PK roundtrip failed")
        report["uuid"] = {
            "native_version": native_reloaded.id.version,
            "alchemy_version": reloaded.id.version,
            "alchemy_python_type": type(reloaded.id).__name__,
            "alchemy_sqlite_utc_roundtrip": str(reloaded.created_at.tzinfo),
            "native_sqlite_utc_roundtrip": str(native_reloaded.created_at.tzinfo),
            "matching_composite_fk_accepted": True,
        }
        try:
            async with db.begin_nested():
                db.add(AlchemyLink(id=2, workspace_id=uuid7(), record_id=record_id))
                await db.flush()
        except IntegrityError:
            report["uuid"]["cross_workspace_composite_fk_rejected"] = True
        await db.rollback()

        cas = (
            update(AlchemyRecord)
            .where(
                AlchemyRecord.id == record_id,
                AlchemyRecord.workspace_id == root_id,
                AlchemyRecord.version == 1,
            )
            .values(name="After", version=AlchemyRecord.version + 1)
            .returning(AlchemyRecord.id)
        )
        report["transaction"] = {"cas_winner": await db.scalar(cas) is not None}
        report["transaction"]["cas_stale_rejected"] = await db.scalar(cas) is None
        db.add(
            AuditEvent(action="prototype.cas", target_type="prototype", target_id=str(record_id))
        )
        await db.flush()
        await db.rollback()
        restored = await db.get(AlchemyRecord, record_id, populate_existing=True)
        report["transaction"]["rollback_restores_record_and_audit"] = (
            restored is not None
            and restored.version == 1
            and restored.name == "Before"
            and await db.scalar(select(func.count()).select_from(AuditEvent)) == 0
        )
        report["postgres_sql"] = {
            "cas": str(cas.compile(dialect=postgresql.dialect())),
            "lock": str(
                select(AlchemyRecord)
                .with_for_update(read=True, of=AlchemyRecord)
                .compile(dialect=postgresql.dialect())
            ),
        }

        admin, editor, owner = (
            User(id=uuid7(), username=name, password_hash="scratch-only")
            for name in ("prototype-admin", "prototype-editor", "prototype-owner")
        )
        db.add_all([admin, editor, owner])
        await db.flush()
        roots = [
            Workspace(id=uuid7(), name=name, created_by=owner.id)
            for name in ("Alpha", "Beta", "Gamma")
        ]
        db.add_all(roots)
        await db.flush()
        for workspace in roots:
            db.add_all([
                WorkspaceMember(
                    workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.owner
                ),
                WorkspaceMember(
                    workspace_id=workspace.id, user_id=admin.id, role=WorkspaceRole.admin
                ),
            ])
        current = roots[-1]
        db.add(
            WorkspaceMember(workspace_id=current.id, user_id=editor.id, role=WorkspaceRole.editor)
        )
        start = datetime(2026, 1, 1, tzinfo=UTC)
        modes = (
            ("Workspace desk", ProjectParticipation.workspace),
            ("Open joined", ProjectParticipation.open),
            ("Open joinable", ProjectParticipation.open),
            ("Managed joined", ProjectParticipation.managed),
            ("Managed governance", ProjectParticipation.managed),
            ("Archived open", ProjectParticipation.open),
            ("Deleted project", ProjectParticipation.open),
        )
        projects = [
            Project(
                id=uuid7(),
                workspace_id=current.id,
                name=name,
                participation=mode,
                created_by=owner.id,
                created_at=start + timedelta(seconds=index // 2),
            )
            for index, (name, mode) in enumerate(modes)
        ]
        projects[-2].state, projects[-1].state = ProjectState.archived, ProjectState.deleted
        foreign = Project(id=uuid7(), workspace_id=roots[0].id, name="Foreign", created_by=owner.id)
        db.add_all([*projects, foreign])
        await db.flush()
        for project in (projects[1], projects[3]):
            for user in (admin, editor):
                db.add(
                    ProjectMember(workspace_id=current.id, project_id=project.id, user_id=user.id)
                )
        items = [
            Item(id=uuid7(), workspace_id=current.id, title=f"Item {index}", created_by=owner.id)
            for index in range(2)
        ]
        db.add_all(items)
        await db.flush()
        for project, item in (
            (projects[0], items[0]),
            (projects[0], items[1]),
            (projects[1], items[0]),
        ):
            db.add(
                ProjectItem(
                    workspace_id=current.id,
                    project_id=project.id,
                    item_id=item.id,
                    added_by=owner.id,
                )
            )
        await db.commit()
        foreign_id, current_id = foreign.id, current.id

        admin_ctx = await resolve_workspace_context(db, admin, current_id)
        editor_ctx = await resolve_workspace_context(db, editor, current_id)
        admin_query = (
            select(Project)
            .where(project_discovery_predicate(admin_ctx))
            .order_by(Project.created_at, Project.id)
        )
        repo = ProjectReadRepository(session=db, statement=admin_query, wrap_exceptions=False)
        first, total = await repo.get_many_and_count(
            LimitOffset(limit=2, offset=0), count_with_window_function=False
        )
        empty, window_total = await repo.get_many_and_count(LimitOffset(limit=2, offset=100))
        _, correct_total = await repo.get_many_and_count(
            LimitOffset(limit=2, offset=100), count_with_window_function=False
        )
        editor_repo = ProjectReadRepository(
            session=db, statement=select(Project).where(project_discovery_predicate(editor_ctx))
        )
        editor_rows, editor_total = await editor_repo.get_many_and_count(
            LimitOffset(limit=2, offset=0), count_with_window_function=False
        )
        members = select(ProjectMember.project_id).where(
            ProjectMember.workspace_id == current_id, ProjectMember.user_id == admin.id
        )
        mine, mine_total = await repo.get_many_and_count(
            or_(Project.participation == ProjectParticipation.workspace, Project.id.in_(members)),
            LimitOffset(limit=10, offset=0),
            count_with_window_function=False,
        )
        all_rows = await repo.get_many()
        editor_all = await editor_repo.get_many()
        # The real directory returns Project + Item count + participation, not just a model.
        projection = (
            select(
                Project,
                func.count(ProjectItem.id),
                or_(
                    Project.participation == ProjectParticipation.workspace, Project.id.in_(members)
                ),
            )
            .outerjoin(ProjectItem, ProjectItem.project_id == Project.id)
            .where(project_discovery_predicate(admin_ctx))
            .group_by(Project.id)
            .order_by(Project.created_at, Project.id)
        )
        query_repo = SQLAlchemyAsyncQueryRepository(session=db, wrap_exceptions=False)
        projected_rows = await query_repo.get_many(projection.limit(2))
        report["projection"] = {
            "raw_rows": [
                {"name": row[0].name, "item_count": row[1], "participating": row[2]}
                for row in projected_rows
            ],
        }
        try:
            await query_repo.get_many_and_count(projection.limit(2))
        except ValueError as error:
            report["projection"]["generic_window_error"] = f"{type(error).__name__}: {error}"
        try:
            # In 1.11.0 QueryRepository this flag selects the basic path when True.
            await query_repo.get_many_and_count(projection, count_with_window_function=True)
        except MultipleResultsFound as error:
            report["projection"]["generic_grouped_count_error"] = f"{type(error).__name__}: {error}"
        report["projection"]["explicit_subquery_total"] = await db.scalar(
            select(func.count()).select_from(projection.order_by(None).subquery())
        )
        report["pagination"] = {
            "admin_first_page": {"names": [row.name for row in first], "total": total},
            "editor_first_page": {
                "names": [row.name for row in editor_rows],
                "total": editor_total,
            },
            "empty_page": {
                "rows": len(empty),
                "window_total": window_total,
                "separate_count_total": correct_total,
            },
            "admin_mine": {"names": [row.name for row in mine], "total": mine_total},
            "governance_discovery_is_not_participation": projects[4] in all_rows
            and projects[4] not in mine,
            "deleted_and_foreign_excluded": projects[-1] not in all_rows
            and foreign not in all_rows,
        }
        try:
            await repo.get(foreign_id)
        except NotFoundError:
            report["pagination"]["scoped_get_rejects_foreign"] = True

        workspace_query = (
            select(Workspace)
            .where(
                Workspace.state != WorkspaceState.deleted,
                Workspace.id.in_(
                    select(WorkspaceMember.workspace_id).where(
                        WorkspaceMember.user_id == admin.id,
                        WorkspaceMember.state == WorkspaceMemberState.active,
                        WorkspaceMember.terminated_at.is_(None),
                    )
                ),
            )
            .order_by(Workspace.name, Workspace.id)
        )
        workspace_repo = WorkspaceReadRepository(session=db, statement=workspace_query)
        workspace_page, workspace_total = await workspace_repo.get_many_and_count(
            LimitOffset(limit=1, offset=0), count_with_window_function=False
        )
        direct = await resolve_workspace_context(db, admin, current_id)
        report["workspace_recovery"] = {
            "page_names": [row.name for row in workspace_page],
            "total": workspace_total,
            "current_on_first_page": any(row.id == current_id for row in workspace_page),
            "direct_resolution": direct.workspace.name,
        }
        report["demo_fixture"] = {
            "currentWorkspaceId": current_id,
            "workspaces": [{"id": row.id, "name": row.name} for row in roots],
            "workspaceAccess": {"admin": [row.id for row in roots], "editor": [current_id]},
            "projects": [
                {
                    "id": row.id,
                    "name": row.name,
                    "participation": row.participation.value,
                    "createdAt": row.created_at.isoformat(),
                    "state": row.state.value,
                    "discoverableFor": [
                        key
                        for key, rows in (("admin", all_rows), ("editor", editor_all))
                        if row in rows
                    ],
                    "participatingFor": ["admin", "editor"] if row in mine else [],
                }
                for row in all_rows
            ],
        }

        # The cursor carries immutable sort values, so its boundary row may disappear.
        boundary = first[-1]
        boundary_time, boundary_key = boundary.created_at, boundary.id
        await db.execute(delete(Project).where(Project.id == boundary_key))
        await db.execute(
            update(Project).where(Project.id == projects[2].id).values(name="Open renamed")
        )
        continuation = admin_query.where(
            or_(
                Project.created_at > boundary_time,
                and_(Project.created_at == boundary_time, Project.id > boundary_key),
            )
        )
        cursor_rows = await repo.get_many(LimitOffset(limit=2, offset=0), statement=continuation)
        offset_rows = await repo.get_many(LimitOffset(limit=2, offset=2))
        report["cursor"] = {
            "first_page": [row.name for row in first],
            "after_deleting_boundary_and_renaming_next": [row.name for row in cursor_rows],
            "offset_after_same_changes": [row.name for row in offset_rows],
            "cursor_preserves_next_record": bool(cursor_rows)
            and cursor_rows[0].id == projects[2].id,
            "offset_skips_next_record": bool(offset_rows) and offset_rows[0].id != projects[2].id,
        }
        await db.rollback()

        # Deliberate counterexample: a read statement is not a write authorization guard.
        result = await repo.update_many([Project(id=foreign_id, name="Changed outside read scope")])
        await db.commit()
        async with sessions() as fresh:
            changed = await fresh.get(Project, foreign_id)
            report["write_boundary"] = {
                "bulk_returned_rows": len(result),
                "foreign_record_changed": changed is not None
                and changed.name == "Changed outside read scope",
            }

    uuids = [uuid7() for _ in range(256)]
    report["uuid"]["object_key_prefixes_in_burst"] = {
        "uuid7": len({
            "/".join(object_key(value, ObjectSuffix.PDF).split("/")[:2]) for value in uuids
        }),
        "uuid4": len({
            "/".join(object_key(uuid4(), ObjectSuffix.PDF).split("/")[:2]) for _ in range(256)
        }),
        "samples": [object_key(uuids[0], ObjectSuffix.PDF)],
    }
    report["nanoid"] = {
        "native_extra_installed": bool(NANOID_INSTALLED),
        "runtime_validated": False,
    }
    report["ddl"] = {
        dialect.name: {
            model.__tablename__: str(
                CreateTable(cast("Table", model.__table__)).compile(dialect=dialect)
            )
            for model in (NativeRecord, AlchemyWorkspace, AlchemyRecord, AlchemyLink, NanoRecord)
        }
        for dialect in (sqlite.dialect(), postgresql.dialect())
    }
    await engine.dispose()
    return report


if __name__ == "__main__":
    result = asyncio.run(probe())
    evidence_path = HERE / "evidence.json"
    evidence_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n")
    demo_path = HERE / "demo.html"
    if demo_path.exists():
        demo = demo_path.read_text()
        start_marker = '<script type="application/json" id="backend-evidence">'
        end_marker = "</script><!-- END BACKEND EVIDENCE -->"
        before, rest = demo.split(start_marker, 1)
        _, after = rest.split(end_marker, 1)
        demo_path.write_text(
            before
            + start_marker
            + "\n"
            + json.dumps(
                {key: value for key, value in result.items() if key != "ddl"},
                ensure_ascii=False,
                default=str,
            ).replace("</", "<\\/")
            + "\n"
            + end_marker
            + after
        )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key not in ("ddl", "demo_fixture")},
            indent=2,
            default=str,
        )
    )
    print(f"Full dialect DDL and observations: {evidence_path}")
