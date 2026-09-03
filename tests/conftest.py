from __future__ import annotations

from datetime import UTC, datetime

import pytest
from dbos import AsyncSQLAlchemyDatasource
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quirebase.core.config import get_settings
from quirebase.core.database import Base, make_async_engine
from quirebase.core.storage import get_object_store
from quirebase.core.workflows import DBOSAdapter, WorkflowSummary, ads, durable_operations


class InMemoryDurableOperations:
    """A transaction-neutral DBOS client double for ordinary unit tests."""

    def __init__(self) -> None:
        self.workflows: dict[str, WorkflowSummary] = {}
        self.messages: list[tuple[str, object, str, str]] = []
        self.enqueues: list[dict[str, object]] = []

    async def enqueue(
        self,
        workflow_name: str,
        *args: object,
        queue_name: str,
        workflow_id: str,
        partition_key: str | None = None,
        attributes: dict[str, object] | None = None,
    ) -> str:
        self.enqueues.append({
            "workflow_name": workflow_name,
            "args": args,
            "queue_name": queue_name,
            "workflow_id": workflow_id,
            "partition_key": partition_key,
            "attributes": attributes,
        })
        now = datetime.now(UTC)
        self.workflows.setdefault(
            workflow_id,
            WorkflowSummary(
                id=workflow_id,
                name=workflow_name,
                state="pending",
                raw_status="ENQUEUED",
                queue_name=queue_name,
                executor_id=None,
                created_at=now,
                updated_at=now,
                attributes=attributes,
            ),
        )
        return workflow_id

    async def enqueue_in_transaction(self, db, workflow_name: str, *args: object, **kwargs):
        del db
        return await self.enqueue(workflow_name, *args, **kwargs)

    async def send(
        self,
        workflow_id: str,
        message: object,
        *,
        topic: str,
        idempotency_key: str,
    ) -> None:
        self.messages.append((workflow_id, message, topic, idempotency_key))

    async def get(self, workflow_id: str) -> WorkflowSummary | None:
        return self.workflows.get(workflow_id)

    async def list(
        self, *, status: str = "", limit: int = 100, offset: int = 0, name: str | None = None
    ):
        rows = tuple(reversed(tuple(self.workflows.values())))
        return tuple(
            row
            for row in rows
            if (not status or row.state == status) and (name is None or row.name == name)
        )[offset : offset + limit]

    async def list_active(self, *, limit: int = 100, offset: int = 0, name: str | None = None):
        rows = tuple(reversed(tuple(self.workflows.values())))
        return tuple(
            row
            for row in rows
            if row.state in {"pending", "running"} and (name is None or row.name == name)
        )[offset : offset + limit]

    async def state_counts(self):
        counts = {}
        for workflow in self.workflows.values():
            counts[workflow.state] = counts.get(workflow.state, 0) + 1
        return counts


@pytest.fixture(autouse=True)
def fake_durable_operations(monkeypatch):
    fake = InMemoryDurableOperations()
    monkeypatch.setattr(DBOSAdapter, "from_settings", classmethod(lambda cls: fake))
    durable_operations.cache_clear()
    yield fake
    durable_operations.cache_clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def async_session_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIREBASE_DATA_DIR", str(tmp_path / "async-data"))
    get_settings.cache_clear()
    get_object_store.cache_clear()
    engine = make_async_engine(f"sqlite:///{tmp_path / 'async-test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    ds = await AsyncSQLAlchemyDatasource.create(
        f"sqlite+aiosqlite:///{tmp_path / 'async-test.db'}",
        engine=engine,
    )
    ads.set_instance(ds)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        ads.set_instance(None)
        await engine.dispose()
        get_settings.cache_clear()
        get_object_store.cache_clear()


@pytest.fixture
async def async_db(async_session_factory):
    async with async_session_factory() as session:
        yield session
