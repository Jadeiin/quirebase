# Advanced Alchemy persistence implementation

[ADR 0014](../adr/0014-advanced-alchemy-persistence.md) defines the toolkit's role;
[ADR 0006](../adr/0006-async-runtime-and-persistence.md) defines the async runtime. Dependency
versions are declared in `pyproject.toml` and locked in `uv.lock`.

## Sessions and transactions

Core configures `SQLAlchemyAsyncConfig`, `EngineConfig`, shared metadata and
`AsyncSessionConfig(expire_on_commit=False)`. Each request or workflow transaction owns its
AsyncSession; concurrent tasks use separate sessions. Relationships are eagerly loaded or
explicitly refreshed. Business commands retain authorization, state changes, side effects and
transaction completion. Reused owner operations flush within the caller's transaction.

Provider I/O follows completed read transactions and precedes a fresh write transaction that
rechecks authority and versions. PyMuPDF, archive/backup work and local inference use explicit
thread boundaries; PostgreSQL dump/restore uses asynchronous subprocesses. Typer entry points
run async commands through `asyncio.run`.

`core.persistence` provides three database mechanisms:

- `conflict_insert` selects SQLite/PostgreSQL native INSERT; commands supply conflict targets
  and update expressions.
- `select_page` applies statement filters and counts the filtered roots independently of slicing,
  preserving totals on empty pages.
- `delete_page` retains an owner's predicate while deleting a bounded, ordered set of primary keys
  inside the caller's transaction.

Commands express CAS, lineage predicates and root locks directly through SQLAlchemy. Savepoints
contain constraint failures so the surrounding transaction remains usable. The
[business concurrency contract](business-concurrency.md) defines the protected invariants.

## Database configuration and values

SQLite uses `sqlite+aiosqlite`, foreign-key enforcement and WAL. Core starts a physical outer
transaction before a first savepoint, so releasing that savepoint cannot commit independently of
the caller. Ordinary reads use statement-level snapshots.

PostgreSQL uses psycopg's async implementation. Application, DBOS and dump/restore share a libpq
URL; [Deployment](../DEPLOYMENT.md#supported-platforms) describes accepted configuration.
Connections explicitly select UTC because AA's `DateTimeUTC` preserves timezone-aware driver
results in the connection timezone.

Entity mappings use `UUIDv7AuditBase`, immutable identities use `UUIDv7Base`, and natural/composite
keys use `DefaultBase`. PostgreSQL stores native UUIDs. SQLite compiles AA GUID as BLOB so UUID
bytes and reflected schema agree. Object keys and client-authored Annotation/Reply IDs use UUID4.
`AuditColumns` supplies defaults/onupdate for ORM and SQL DML while preserving explicit timestamps;
AA's additional timestamp-touch listener is disabled.

`JsonB` stores Work snapshots, Import records/results, Audit details, recommendations, PDF geometry,
Annotation payloads and diagnostics. JSON UUIDs reload as strings; commands replace complete
values. Domain state columns use non-native enums with explicit CHECK constraints.

Argon2 inputs are prepared outside the event loop. The application password type represents its
physical Text column for Alembic. Migration metadata loads directly from the
[central mapping](orm-ownership.md), with dialect-specific Search DDL and autogenerate exclusions
in the migration environment. [Migration authoring](../../migrations/README) documents the CLI,
template and fresh-database checks.

## File descriptors

File Revision PDFs/thumbnails, Attachments and Annotation Export Artifacts use AA `StoredObject`
and `FileObject`. Import Batch staging uses `StoredObject(backend="documents", multiple=True)`;
each descriptor retains its source UUID and original filename. Durable inputs use serializable
receipt snapshots, preserving input meaning across recovery.

Core disables AA's automatic file-object listener. Commands and workflows own transfers,
transactional ownership changes and reference-aware cleanup. Descriptor equality matters for
copy and repair: changing metadata as well as the path invalidates a captured source snapshot.
Object I/O happens outside the snapshot transaction; finalization locks and compares current
values. The [object lifecycle contract](object-lifecycle.md) defines these operations.

Authorized native S3 signing uses `FileObject.sign_async`; the application streams by default.
[Deployment](../DEPLOYMENT.md#object-storage) defines expiry, endpoint and CORS requirements.
Web uses AA result conversion for attribute-only administrative/API Token DTOs; computed status,
authorization and domain choices remain explicit projections beside their capability routes.

## Verification

Dependency characterization in `tests/test_persistence_dependencies.py` is separate from
Quirebase behavior. `test_persistence_operations.py` and `test_persistence_values.py` cover caller
rollback, constraint recovery, UUID identity, JSON and timestamps on SQLite/PostgreSQL.
`test_persistence_boundaries.py` covers copy, metadata, cleanup and durable receipt snapshots.

[Concurrency testing](../testing/concurrency.md) documents controlled PostgreSQL schedules and
real DBOS process-death recovery. [Application contracts](application-http-boundary.md) define
collection pagination and frontend consumers.
