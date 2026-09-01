from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from dbos import DBOS, AsyncSQLAlchemyDatasource, DBOSClient, DBOSConfig, EnqueueOptions
from dbos._error import DBOSNonExistentWorkflowError

from quirebase import __version__
from quirebase.core.config import get_settings
from quirebase.core.database import async_database_url, engine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

WorkflowState = Literal["pending", "running", "succeeded", "failed", "cancelled"]

UPLOAD_QUEUE = "documents.upload"
DOCUMENTS_QUEUE = "documents.revision"
LIBRARY_QUEUE = "library"
OPERATIONS_QUEUE = "operations"
UPLOAD_COMPLETE_TOPIC = "upload-complete"

_VISIBLE_STATE: dict[str, WorkflowState] = {
    "ENQUEUED": "pending",
    "DELAYED": "pending",
    "PENDING": "running",
    "SUCCESS": "succeeded",
    "ERROR": "failed",
    "MAX_RECOVERY_ATTEMPTS_EXCEEDED": "failed",
    "CANCELLED": "cancelled",
}


@dataclass(frozen=True)
class WorkflowSummary:
    id: str
    name: str
    state: WorkflowState
    raw_status: str
    queue_name: str | None
    executor_id: str | None
    created_at: datetime | None
    updated_at: datetime | None
    output: Any | None = None
    error: str | None = None
    attributes: dict[str, Any] | None = None
    authenticated_user: str | None = None


class DurableOperations(Protocol):
    async def enqueue(
        self,
        workflow_name: str,
        *args: Any,
        queue_name: str,
        workflow_id: str,
        partition_key: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str: ...

    async def enqueue_in_transaction(
        self,
        db: AsyncSession,
        workflow_name: str,
        *args: Any,
        queue_name: str,
        workflow_id: str,
        partition_key: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str: ...

    async def send(
        self,
        workflow_id: str,
        message: Any,
        *,
        topic: str,
        idempotency_key: str,
    ) -> None: ...

    async def get(self, workflow_id: str) -> WorkflowSummary | None: ...

    async def list(
        self, *, status: str = "", limit: int = 100, offset: int = 0, name: str | None = None
    ) -> tuple[WorkflowSummary, ...]: ...


def _sync_database_url() -> str:
    url = async_database_url()
    return url.replace("sqlite+aiosqlite:///", "sqlite:///")


def _options(
    workflow_name: str,
    queue_name: str,
    workflow_id: str,
    partition_key: str | None,
    attributes: dict[str, Any] | None,
) -> EnqueueOptions:
    options: dict[str, Any] = {
        "workflow_name": workflow_name,
        "queue_name": queue_name,
        "workflow_id": workflow_id,
        "application_name": "quirebase",
    }
    if partition_key is not None:
        options["queue_partition_key"] = partition_key
    if attributes:
        options["attributes"] = attributes
    return cast("EnqueueOptions", options)


def _timestamp(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, UTC) if value is not None else None


def _summary(status: Any) -> WorkflowSummary:
    raw = str(status.status)
    return WorkflowSummary(
        id=status.workflow_id,
        name=status.name,
        state=_VISIBLE_STATE[raw],
        raw_status=raw,
        queue_name=status.queue_name,
        executor_id=status.executor_id,
        created_at=_timestamp(status.created_at),
        updated_at=_timestamp(status.updated_at),
        output=status.output,
        error=str(status.error) if status.error is not None else None,
        attributes=status.attributes,
        authenticated_user=status.authenticated_user,
    )


class DBOSAdapter:
    """The sole DBOS Client adapter exposed to business Modules and inbound adapters."""

    def __init__(self, client: DBOSClient):
        self._client = client

    @classmethod
    def from_settings(cls) -> DBOSAdapter:
        return cls(
            DBOSClient(
                system_database_url=_sync_database_url(),
                application_name="quirebase",
                use_listen_notify=False,
                lazy=True,
            )
        )

    async def enqueue(
        self,
        workflow_name: str,
        *args: Any,
        queue_name: str,
        workflow_id: str,
        partition_key: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        handle: Any = await self._client.enqueue_async(
            _options(workflow_name, queue_name, workflow_id, partition_key, attributes), *args
        )
        return handle.get_workflow_id()

    async def enqueue_in_transaction(
        self,
        db: AsyncSession,
        workflow_name: str,
        *args: Any,
        queue_name: str,
        workflow_id: str,
        partition_key: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        connection = await db.connection()
        options = _options(workflow_name, queue_name, workflow_id, partition_key, attributes)
        handle: Any = await connection.run_sync(
            lambda sync_connection: self._client.enqueue_in_transaction(
                sync_connection, options, *args
            )
        )
        return handle.get_workflow_id()

    async def send(
        self,
        workflow_id: str,
        message: Any,
        *,
        topic: str,
        idempotency_key: str,
    ) -> None:
        await self._client.send_async(
            workflow_id, message, topic, idempotency_key=idempotency_key
        )

    async def get(self, workflow_id: str) -> WorkflowSummary | None:
        try:
            handle: Any = await self._client.retrieve_workflow_async(workflow_id)
            status = await handle.get_status()
        except DBOSNonExistentWorkflowError:
            return None
        return _summary(status) if status is not None else None

    async def list(
        self, *, status: str = "", limit: int = 100, offset: int = 0, name: str | None = None
    ) -> tuple[WorkflowSummary, ...]:
        raw_status: str | list[str] | None = None
        if status:
            requested = status.strip().casefold()
            matching = [raw for raw, visible in _VISIBLE_STATE.items() if visible == requested]
            if not matching:
                raise ValueError(f"unknown workflow state: {status}")
            raw_status = matching
        rows = await self._client.list_workflows_async(
            status=raw_status,
            name=name,
            limit=limit,
            offset=offset,
            sort_desc=True,
            load_input=False,
            application_name="quirebase",
        )
        return tuple(_summary(row) for row in rows)


async def list_all_workflows(*, status: str = "", name: str | None = None):
    """Read the complete workflow history in bounded DBOS pages."""
    page_size = 10_000
    offset = 0
    result: list[WorkflowSummary] = []
    while True:
        page = await durable_operations().list(
            status=status, name=name, limit=page_size, offset=offset
        )
        result.extend(page)
        if len(page) < page_size:
            return tuple(result)
        offset += len(page)


@lru_cache
def durable_operations() -> DBOSAdapter:
    return DBOSAdapter.from_settings()


async def verify_durable_operations() -> None:
    """Verify the DBOS system schema and client without mutating workflow state."""
    await durable_operations().list(limit=1)


async def _launch_runtime(executor_id: str) -> None:
    DBOS(
        config=DBOSConfig(
            name="quirebase",
            application_version=__version__,
            system_database_url=_sync_database_url(),
            executor_id=executor_id,
            use_listen_notify=False,
            run_admin_server=False,
        )
    )
    await AsyncSQLAlchemyDatasource.create(async_database_url(), engine=engine, schema="dbos")
    DBOS.launch()
    await DBOS.register_queue_async(UPLOAD_QUEUE)
    await DBOS.register_queue_async(
        DOCUMENTS_QUEUE,
        partition_concurrency=1,
    )
    await DBOS.register_queue_async(LIBRARY_QUEUE, global_concurrency=1)
    await DBOS.register_queue_async(OPERATIONS_QUEUE, global_concurrency=1)


async def initialize_durable_operations() -> None:
    """Create or migrate DBOS infrastructure state during `init-db`."""
    await _launch_runtime("quirebase-initializer")
    await asyncio.to_thread(DBOS.destroy, destroy_registry=True)
    durable_operations.cache_clear()


async def launch_worker() -> None:
    """Launch the dedicated workflow executor and wait until cancelled."""
    await _launch_runtime(get_settings().workflow_executor_id)
    try:
        await asyncio.Event().wait()
    finally:
        await asyncio.to_thread(DBOS.destroy, workflow_completion_timeout_sec=30)


async def recover_workflows(executor_id: str, *, apply: bool) -> Sequence[str]:
    rows = await durable_operations().list(status="running", limit=10_000)
    candidates = tuple(row.id for row in rows if row.executor_id == executor_id)
    if not apply or not candidates:
        return candidates
    await _launch_runtime(f"quirebase-recovery-{executor_id}")
    try:
        handles = DBOS._recover_pending_workflows([executor_id])
        await asyncio.gather(*(asyncio.to_thread(handle.get_result) for handle in handles))
        return tuple(handle.get_workflow_id() for handle in handles)
    finally:
        await asyncio.to_thread(DBOS.destroy, workflow_completion_timeout_sec=30)
