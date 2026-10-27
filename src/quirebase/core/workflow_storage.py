"""DBOS system storage metrics and retention of non-cascading payloads.

Keep vendor table knowledge here. Retention uses the caller's short transaction;
adapter queries use the SDK's schema-bound system engine. Neither changes SDK execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from dbos._schemas import SCHEMA_PLACEHOLDER
from dbos._schemas.datasource_database import datasource_outputs_table
from dbos._schemas.system_database import SystemSchema
from sqlalchemy import delete, func, inspect, or_, select, tuple_

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Engine
    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession

_TERMINAL_STATUSES = ("SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED")
_DATASOURCE_OUTPUTS = datasource_outputs_table(SCHEMA_PLACEHOLDER)


def workflow_status_counts(engine: Engine, *, name: str | None = None) -> dict[str | None, int]:
    """Count raw statuses with the same application visibility as DBOS Client listing."""
    status = SystemSchema.workflow_status
    statement = (
        select(status.c.status, func.count())
        .where(or_(status.c.application_name == "quirebase", status.c.application_name.is_(None)))
        .group_by(status.c.status)
    )
    if name is not None:
        statement = statement.where(status.c.name == name)
    with engine.connect() as connection:
        return dict(connection.execute(statement).tuples().all())


async def _connection(db: AsyncSession):
    connection = await db.connection()
    schema = None if connection.dialect.name == "sqlite" else "dbos"
    return await connection.execution_options(schema_translate_map={SCHEMA_PLACEHOLDER: schema})


async def purge_workflow_history(
    db: AsyncSession, *, before: datetime, limit: int = 100
) -> dict[str, int]:
    """Retire expired parents before children, preserving every retained parent's receipts.

    Child IDs belong to their unique producing parent. The SDK writes native parent
    identity with child creation, before recording the enqueue operation. Neither
    workflow IDs nor their recovery eligibility survive the retention horizon.
    """
    await _connection(db)
    status = SystemSchema.workflow_status
    operations = SystemSchema.operation_outputs
    parent = status.alias("retained_parent")
    has_parent = (
        select(parent.c.workflow_uuid)
        .where(parent.c.workflow_uuid == status.c.parent_workflow_id)
        .correlate(status)
        .exists()
    )
    referenced_children = (
        select(operations.c.child_workflow_id)
        .select_from(operations.join(parent, operations.c.workflow_uuid == parent.c.workflow_uuid))
        .where(operations.c.child_workflow_id.is_not(None))
    )
    eligible = (
        status.c.application_name == "quirebase",
        status.c.status.in_(_TERMINAL_STATUSES),
        status.c.completed_at < int(before.timestamp() * 1000),
        ~has_parent,
        # An uncorrelated set avoids rescanning the unindexed child ID column
        # once per candidate on SQLite. NULL must never enter a NOT IN set.
        status.c.workflow_uuid.not_in(referenced_children),
    )
    candidates = (
        select(status.c.workflow_uuid)
        .where(*eligible)
        .order_by(status.c.completed_at, status.c.workflow_uuid)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    # DELETE's predicate is rechecked after concurrent resume. Delete status first:
    # SQLite does not implement FOR UPDATE, so clearing receipts before this CAS
    # could erase the checkpoints of a concurrently resumed execution.
    retired = tuple(
        await db.scalars(
            delete(status)
            .where(status.c.workflow_uuid.in_(candidates), *eligible)
            .returning(status.c.workflow_uuid)
        )
    )
    removed = 0
    if retired:
        # DBOS 3 payload tables have no status FK. Retire them only after the
        # guarded status delete, in the same transaction as datasource receipts.
        for table in (
            SystemSchema.operation_outputs,
            SystemSchema.workflow_input,
            SystemSchema.workflow_output,
        ):
            await db.execute(delete(table).where(table.c.workflow_uuid.in_(retired)))
        result = await db.execute(
            delete(_DATASOURCE_OUTPUTS).where(_DATASOURCE_OUTPUTS.c.workflow_id.in_(retired))
        )
        removed = cast("CursorResult", result).rowcount
    return {"workflow_history": len(retired), "datasource_checkpoints": removed}


async def purge_orphan_datasource_outputs(
    db: AsyncSession, *, before: datetime, limit: int = 100
) -> int:
    """Revisit all orphan IDs every maintenance round, including late SDK error writes.

    Datasource results have no status FK. A cancelled step or its independent error
    recorder may commit after history retirement; the next round collects it.
    """
    await _connection(db)
    outputs = _DATASOURCE_OUTPUTS
    status = SystemSchema.workflow_status
    orphan = ~(
        select(status.c.workflow_uuid)
        .where(status.c.workflow_uuid == outputs.c.workflow_id)
        .correlate(outputs)
        .exists()
    )
    candidates = (
        select(outputs.c.workflow_id, outputs.c.step_id)
        .where(orphan, outputs.c.created_at <= int(before.timestamp() * 1000))
        .order_by(outputs.c.workflow_id, outputs.c.step_id)
        .limit(limit)
    )
    result = await db.execute(
        delete(outputs).where(
            tuple_(outputs.c.workflow_id, outputs.c.step_id).in_(candidates), orphan
        )
    )
    return cast("CursorResult", result).rowcount


async def workflow_storage_counts(db: AsyncSession) -> dict[str, int | None]:
    """Read SQL counts without loading serialized arguments or checkpoint payloads."""
    connection = await _connection(db)
    schema = None if connection.dialect.name == "sqlite" else "dbos"
    tables = {
        "workflow_history_count": SystemSchema.workflow_status,
        "workflow_checkpoint_count": SystemSchema.operation_outputs,
        "datasource_checkpoint_count": _DATASOURCE_OUTPUTS,
    }
    existing = await connection.run_sync(
        lambda sync: set(inspect(sync).get_table_names(schema=schema))
    )
    return {
        key: await db.scalar(select(func.count()).select_from(table))
        if table.name in existing
        else None
        for key, table in tables.items()
    }
