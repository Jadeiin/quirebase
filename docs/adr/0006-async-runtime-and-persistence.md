# ADR 0006: native async runtime and persistence

Status: accepted.

This decision supersedes the synchronous `ProviderRuntime` lifecycle in ADR 0005 and applies to
the complete Quirebase/Inquiro runtime path: Provider access, SQLAlchemy persistence, Library
Search, Web/API, MCP and Pipeline workers.

## Decision

`ProviderRuntime` is an asynchronous deep Interface. Callers use `async with` and `await` its
`lookup`, `search` and `acquire_document` operations, and close it with `aclose`. Provider
Implementations, Context, Exchange and Transport contracts are asynchronous as well. PDF streams
are consumed with asynchronous iteration and closed with `aclose`; their immutable receipt
metadata and ownership semantics are unchanged.

Quirebase uses SQLAlchemy's native asyncio extension throughout runtime persistence. The database
module owns `create_async_engine`, `async_sessionmaker` and the `AsyncSession` dependency. SQLite
uses `sqlite+aiosqlite`; PostgreSQL keeps the supported `postgresql+psycopg` URL and uses
psycopg's async implementation. SQLAlchemy optional dependency groups provide the runtime pieces:
the application depends on `sqlalchemy[asyncio,aiosqlite]`, while the `postgres` extra depends on
`sqlalchemy[postgresql-asyncpg,postgresql-psycopgbinary]`. Drivers are not imported or installed
through an independent persistence abstraction, and no synchronous Session/engine compatibility
seam remains.

Every request or Job owns one `AsyncSession`; sessions are never shared by concurrent tasks. ORM
queries are explicit `await` operations, and relationship data needed after a query is loaded with
explicit eager options or an explicit refresh. Implicit lazy I/O is forbidden in async code.
Provider calls do not hold database transactions: short reads are completed and rolled back before
external I/O, then writes begin a fresh transaction and revalidate permissions or optimistic
versions before recording Audit Events.

Blocking local work remains synchronous only at a named thread boundary. File storage, FileLock,
archive and backup operations, PyMuPDF, and optional Rubrica/KeyBERT inference use
`asyncio.to_thread`. PostgreSQL dump/restore uses asynchronous subprocesses. Pure validation,
normalization and projection functions remain synchronous. Typer commands remain synchronous
shell entry points and call one `asyncio.run`-driven implementation.

## Consequences

- HTTP wire contracts, CLI commands, database schema, Provider allowlists, error categories and
  domain rules remain unchanged.
- Inquiro's Python async API is intentionally a breaking change; callers migrate atomically and
  no synchronous aliases are provided.
- SQLite remains the default single-worker deployment; PostgreSQL retains concurrent worker
  claims with `FOR UPDATE SKIP LOCKED`.
- Tests use async engines/sessions and `httpx2.AsyncClient` with `ASGITransport`; Provider
  contracts verify async streaming, cancellation, redirects, limits, errors and closure.

## Rejected alternatives

- A synchronous SQLAlchemy Session behind a thread bridge was rejected because it hides blocking
  database work and permits accidental event-loop stalls.
- A Repository/Unit-of-Work or dual sync/async seam was rejected because it duplicates ownership
  and leaves transaction boundaries ambiguous.
- A synchronous Provider compatibility layer was rejected because it would preserve the old
  blocking contract and complicate cancellation and resource ownership.
