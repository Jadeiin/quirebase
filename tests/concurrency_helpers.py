"""Controlled PostgreSQL interleavings; never share a Session between actors."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import event, text

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class PostgresRace:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        node_id: str,
        evidence_dir: Path,
    ) -> None:
        self.sessions = sessions
        self.engine = sessions.kw["bind"]
        self.node_id = node_id
        self.evidence_dir = evidence_dir
        self.pids: dict[str, int] = {}
        self.connections: dict[object, str] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.joined: set[str] = set()
        self.trace: deque[dict] = deque(maxlen=1000)
        self.started = time.monotonic()
        self.snapshot: dict | None = None
        self.failure: dict | None = None
        self.capture_lock = asyncio.Lock()
        self.evidence_path: Path | None = None
        self.closed = False
        self.listeners = {
            "before_cursor_execute": self._sql,
            "begin": self._begin,
            "commit": self._commit,
            "rollback": self._rollback,
        }
        for name, listener in self.listeners.items():
            event.listen(self.engine.sync_engine, name, listener)

    def note(self, action: str, **detail) -> None:
        self.trace.append({
            "elapsed": round(time.monotonic() - self.started, 6),
            "action": action,
            **detail,
        })

    def _sql(self, connection, _cursor, statement, _parameters, _context, _many):
        actor = self.connections.get(connection)
        if actor is not None:
            # Never record bound values, URLs, or exception messages containing
            # SQLAlchemy's parameter dump.
            self.note("sql", actor=actor, statement=statement[:2000])

    def _transaction(self, connection, action):
        actor = self.connections.get(connection)
        if actor is not None:
            self.note(f"transaction.{action}", actor=actor)

    def _begin(self, connection):
        self._transaction(connection, "begin")

    def _commit(self, connection):
        self._transaction(connection, "commit")

    def _rollback(self, connection):
        self._transaction(connection, "rollback")

    @asynccontextmanager
    async def session(self, name: str):
        if name in self.pids:
            raise ValueError(f"Actor name already used: {name}")
        # Keep the connection checked out across business-operation commits so
        # the backend PID remains a reliable actor identity.
        async with self.engine.connect() as connection:
            self.connections[connection.sync_connection] = name
            try:
                self.pids[name] = await connection.scalar(text("SELECT pg_backend_pid()"))
                await connection.execute(
                    text(
                        "SELECT set_config('lock_timeout', '8s', false), "
                        "set_config('statement_timeout', '12s', false), "
                        "set_config('idle_in_transaction_session_timeout', '20s', false)"
                    )
                )
                # Finish connection setup before binding the Session, otherwise
                # its commits would only join the setup transaction.
                await connection.commit()
                self.note("session.open", actor=name, pid=self.pids[name])
                async with self.sessions(bind=connection) as db:
                    try:
                        yield db
                    except BaseException as error:
                        if not isinstance(error, asyncio.CancelledError):
                            await self.capture(error)
                        raise
            finally:
                self.connections.pop(connection.sync_connection, None)
                self.note("session.close", actor=name)
                await connection.rollback()
                if not connection.invalidated:
                    await connection.execute(
                        text(
                            "RESET lock_timeout; RESET statement_timeout; "
                            "RESET idle_in_transaction_session_timeout"
                        )
                    )
                    await connection.commit()

    def start(self, name: str, operation: Coroutine) -> None:
        if name in self.tasks:
            operation.close()
            raise ValueError(f"Task name already used: {name}")
        self.tasks[name] = asyncio.create_task(operation, name=name)
        self.note("task.start", task=name)

    async def join(self, name: str, *, wait_seconds: float = 5):
        self.joined.add(name)
        try:
            async with asyncio.timeout(wait_seconds):
                result = await asyncio.shield(self.tasks[name])
            self.note("task.join", task=name)
            return result
        except BaseException as error:
            if not isinstance(error, asyncio.CancelledError):
                await self.capture(error)
            raise

    async def wait_blocked(self, waiter: str, holder: str, *, wait_seconds: float = 5) -> None:
        # Poll for evidence of a specific wait edge, rather than assuming that a
        # task has reached SQL after an arbitrary sleep.
        try:
            async with asyncio.timeout(wait_seconds), self.engine.connect() as observer:
                while True:
                    if waiter in self.pids and holder in self.pids:
                        blockers = await observer.scalar(
                            text("SELECT pg_blocking_pids(:pid)"), {"pid": self.pids[waiter]}
                        )
                        if self.pids[holder] in blockers:
                            self.note(
                                "blocked",
                                waiter=waiter,
                                holder=holder,
                                waiter_pid=self.pids[waiter],
                                blockers=blockers,
                            )
                            return
                    await asyncio.sleep(0.01)
        except BaseException as error:
            if not isinstance(error, asyncio.CancelledError):
                await self.capture(error)
            raise

    async def capture(self, error: BaseException) -> None:
        """Capture before releasing actors; diagnostics must not mask the failure."""
        # Multiple participants can fail together. Serialize collection and file
        # writes so the first snapshot cannot be overwritten by a later actor.
        async with self.capture_lock:
            await self._capture(error)

    async def _capture(self, error: BaseException) -> None:
        failure = {"type": type(error).__name__, "sqlstate": _sqlstate(error)}
        if self.failure is None:
            self.failure = failure
        self.note("failure", **failure)
        try:
            if self.snapshot is None:
                async with asyncio.timeout(2), self.engine.connect() as observer:
                    pids = list(self.pids.values())
                    activity = await observer.execute(
                        text(
                            "SELECT pid, state, wait_event_type, wait_event, xact_start, query, "
                            "pg_blocking_pids(pid) AS blockers FROM pg_stat_activity "
                            "WHERE pid = ANY(:pids) ORDER BY pid"
                        ),
                        {"pids": pids},
                    )
                    locks = await observer.execute(
                        text(
                            "SELECT pid, locktype, relation::regclass::text AS relation, "
                            "transactionid, virtualxid, mode, granted, waitstart "
                            "FROM pg_locks WHERE pid = ANY(:pids) ORDER BY pid, locktype, mode"
                        ),
                        {"pids": pids},
                    )
                    self.snapshot = {
                        "server_version": await observer.scalar(text("SHOW server_version")),
                        "isolation": await observer.scalar(text("SHOW transaction_isolation")),
                        "activity": [dict(row) for row in activity.mappings()],
                        "locks": [dict(row) for row in locks.mappings()],
                    }
        except Exception as diagnostic_error:
            self.snapshot = {"diagnostic_error": type(diagnostic_error).__name__}
        try:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(self.node_id.encode()).hexdigest()[:16]
            worker = os.getenv("PYTEST_XDIST_WORKER", "main")
            self.evidence_path = self.evidence_dir / f"{digest}-{worker}.json"
            self.evidence_path.write_text(
                json.dumps(
                    {
                        "node_id": self.node_id,
                        "actors": self.pids,
                        "failure": self.failure,
                        "snapshot": self.snapshot,
                        "trace": list(self.trace),
                    },
                    indent=2,
                    default=str,
                )
                + "\n"
            )
        except OSError as diagnostic_error:
            self.note("evidence.write_failed", type=type(diagnostic_error).__name__)

    async def close(self, *, failed: bool = False) -> None:
        if self.closed:
            return
        unjoined = self.tasks.keys() - self.joined
        if unjoined and not failed:
            await self.capture(AssertionError("Race tasks were not joined"))
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        for name, listener in self.listeners.items():
            event.remove(self.engine.sync_engine, name, listener)
        self.closed = True
        if unjoined and not failed:
            raise AssertionError(f"Race tasks were not joined: {sorted(unjoined)}")


def _sqlstate(error: BaseException) -> str | None:
    original = getattr(error, "orig", error)
    return getattr(original, "sqlstate", None)
