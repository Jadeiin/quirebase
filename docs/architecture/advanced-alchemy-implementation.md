# Advanced Alchemy implementation

This record describes the persistence tools in
[ADR 0014](../adr/0014-advanced-alchemy-persistence.md) and the native async runtime in
[ADR 0006](../adr/0006-async-runtime-and-persistence.md), including Module responsibilities,
database behavior and product contracts.

## Async runtime integration

`ProviderRuntime` supports `async with`, asynchronous `lookup`, `search` and `acquire_document`,
and explicit closure through `aclose`. PDF streams use asynchronous iteration and `aclose`.

Core uses `create_async_engine`, `async_sessionmaker` and the `AsyncSession` dependency. Each
request or Job owns one Session, and concurrent tasks use separate Sessions. SQLAlchemy queries
use explicit `await`; relationships use eager loading or explicit refresh. Provider access
completes short read transactions before external I/O, then starts a fresh write transaction and
rechecks authority and optimistic versions.

SQLite uses `sqlite+aiosqlite`; PostgreSQL uses `postgresql+psycopg` with psycopg's async driver.
The application depends on `sqlalchemy[asyncio,aiosqlite]`, and the `postgres` extra depends on
`sqlalchemy[postgresql-psycopgbinary]`. SQLite is the default single-worker deployment; PostgreSQL
worker claims use `FOR UPDATE SKIP LOCKED`.

Blocking File storage, FileLock, archive, backup, PyMuPDF and optional Rubrica/KeyBERT inference
run through `asyncio.to_thread`. PostgreSQL dump/restore uses asynchronous subprocesses. Typer
commands use synchronous shell entry points backed by `asyncio.run`.

Async test bindings are described in [Testing](../TESTING.md).

## Dependencies, sessions and schema

Quirebase uses Advanced Alchemy 1.11.0 with SQLAlchemy `>=2.0,<2.1` in the runtime and PostgreSQL extras.

Core uses `SQLAlchemyAsyncConfig`, `EngineConfig`, a shared metadata registry and
`AsyncSessionConfig(expire_on_commit=False)`. Commands and durable transactions pass their existing
Session to direct SQLAlchemy and reused Module mechanisms. Commands own transaction completion;
shared mechanisms flush prepared values inside the caller's transaction. SQLAlchemy constraint
errors support savepoint recovery. Locked root queries decide availability, and commands translate
missing rows into their domain errors.
`core.persistence` holds `conflict_insert` and `select_page` together. The former selects the
supported database's native INSERT builder; owning commands supply conflict targets and update
expressions. The latter applies AA statement filters, reads the filtered query's COUNT result and
fetches its page.

Core establishes a physical SQLite outer transaction before the first savepoint. Savepoint writes
participate in caller commit and rollback. Ordinary reads use statement-level snapshots. Core also
configures libpq URL validation, foreign-key enforcement and SQLite WAL.

PostgreSQL application connections explicitly select UTC. AA's `DateTimeUTC` normalizes bound
values and reads timezone-aware driver results in the connection's configured UTC timezone.

Entities use `UUIDv7AuditBase`; immutable identities use `UUIDv7Base`; natural/composite keys use
`DefaultBase`. PostgreSQL stores native UUIDs. SQLite compiles AA GUID to BLOB so stored UUID bytes
and reflected schema agree. Object keys use UUID4 for distributed prefixes, and client-authored
Annotation IDs use UUID4. `AuditColumns` defaults/onupdate manage ORM and Core timestamps,
including explicitly supplied timestamp values.

Structured persistent values use `JsonB`, including Import Batch snapshots/results, Audit detail,
Item custom fields, recommendation candidates, PDF geometry/payloads and integrity diagnostics.
JSON UUIDs reload as strings. Commands write complete values. Bibliographic text/search caches and
canonical Identifier associations provide the corresponding projections and relationships.

Argon2 inputs are prepared outside the event loop. The prepared password type provides a
reconstructable representation for Alembic. Alembic renders AA type representations and dialect
variants; its revision template imports the required type modules. Search DDL follows the database
dialect, and Alembic revisions define the schema.

## Module implementations

| Module | Persistence operations |
| --- | --- |
| Accounts | Direct User/Invitation queries and writes; Login Throttle commands own native upsert |
| Workspaces | Direct Workspace/Member writes; explicit directory queries |
| Projects | Direct Project writes; shared participation and Item assignment operations |
| Audit | Explicit filtered Audit Event query |
| Library | Direct Item/Tag/Citation Style commands; pure metadata plans and shared batch mechanisms |
| Documents | Direct prepared-value insertion and Annotation/Reply CAS in commands |
| Operations | Pure runtime-setting validation and native upsert directly in the command |

AA provides models, value types, file descriptors, configuration, filters, pagination DTOs,
password hashing and serialization/result-conversion utilities. Business Module Interfaces expose
their use cases, with authorization, integrity and recovery defined by the owning Module.

## Persistence use cases

Library's `normalize_tag_name` supplies the pure normalization used by `get_or_create_tag`, which
directly inserts and recovers scoped uniqueness races. Tag rename/delete use the locked root.
`create_custom_citation_style` validates CSL and inserts under a savepoint, translating an already
installed name into `ValidationFailure`.
Operations' `update_runtime_settings` validates an entire runtime-setting batch before one ordered
native upsert, refreshing loaded values through `RETURNING`. A savepoint preserves the caller
transaction on a constraint failure.

Library's `open_item_section` directly uses one native upsert, storing the latest reading timestamp
on conflict. Both insert and update validate the supplied Workspace lineage through the composite
foreign key. A savepoint preserves the caller transaction on an invalid lineage. The Item section
command owns authorization and the outer commit/rollback.

Library's `_assign_item_tags` and Projects' `_add_missing_project_items` share single and bulk
association write paths within their owning Modules. Native `ON CONFLICT DO NOTHING` inserts use
stable identity order and batches of at most 500 links. `RETURNING item_id` reports the current
call's new links as scalar identities. A surrounding savepoint rolls back all inserted chunks on
an unrelated constraint failure. Single Item–Tag commands load their result after insertion and
report a conflict if a skipped duplicate disappears before that
read. A concurrent delete after a bulk insert skips a duplicate determines that link's final state.
Tag merge uses the same writer after its command locks both Tag roots.

Projects' participation commands directly write explicit selections. The shared
`_add_participant` operation combines insertion, recovery, Audit and commit for Join and curated Add.
Insertion uses one savepoint; a duplicate reread returns the existing selection. Audit Events
represent newly inserted selections. If a competing Leave deletes the selection before the locked
reread, the command returns `ProjectParticipationConflict` (HTTP 409). Each Join checks authority
and participation policy. Commands own Workspace/Project guards, authorization, Audit and
transaction completion.

Accounts' `record_login_failure` directly uses one native upsert to increment the counter or reset an
expired window atomically, refreshing loaded counter values. A clear committed before the upsert
allows the failure to start a new window. Expiry cleanup targets windows at or before the observed
cutoff. Authentication owns credential checks, Audit Events and Login Session creation.

Documents' Annotation and Reply commands directly execute scoped version CAS for editing, soft
deletion, restoration and Annotation moderation. Author restoration requires a deleted Annotation
with `deleted_by_moderation=False`. Commands own payload validation, authorization, root locking,
version-conflict translation, Audit and transaction completion.

Library's Item metadata commands directly insert roots and replace them through scoped version CAS.
Provider merge logic lives in `identifiers`; shared relationship writing lives in `item_metadata`,
and the reused batch candidate mechanism lives in `identifiers`. Metadata inputs become explicit
write plans: replacement clears omitted associations; Provider merges preserve missing fields,
merge URLs/keywords and retain citation
keys. Shared bounded-column validation accepts domain values. The Item replacement command
uses Workspace, identity and expected-version predicates in its SQL. `Item.version` is an
application CAS field.
Provider synchronization directly advances the version through Workspace, identity and version CAS;
the command owns external I/O, authority rechecks, merge decisions, conflicts, Audit and Search.

Import confirmation batches Item roots and Contributor/Identifier links, resolves shared Authors
across both roles through `_resolve_authors` in bounded chunks and inserts missing identities
in stable order. Uniqueness conflicts roll back only the insertion savepoint, reload installed
identities and retry the pending set, progressing on every retry. The locked Import Batch establishes
result ordering and replay identity. The confirmation command owns File ownership transfer, Search,
Audit and enqueue.
Import Batch creation adds and flushes prepared ORM roots directly in the caller Session.
Bibliography export uses explicit `selectinload` for Contributors and a deterministic Item order.

Documents persists prepared File Revision, Attachment, Export Artifact, Annotation and Reply
instances directly through the caller Session. Versioned mutations use explicit CAS.
Client-authored Annotation/Reply UUID4 values use native UUIDs through insertion and rereads,
including their shared Annotation Object identity.

Web uses native result conversion for attribute-only administrative and API Token DTO fields.
Business Modules explicitly project computed status, identity, authorization and domain choices.

## File descriptors and durable ownership

Attachment, File Revision PDF/thumbnail and Annotation Export Artifact columns use AA
`StoredObject` and `FileObject`. Upload, range/download, copy, statistics, reference scanning and
cleanup read the persisted descriptor. Cross-Workspace copying snapshots complete descriptor
values and compares them before finalization; descriptor metadata changes invalidate the copy.
Integrity scanning releases its transaction before object I/O. Thumbnail repair locks the current
row, checks the scanned path and compares descriptor metadata through explicit SQL.
Export download resolves the persisted artifact and checks its expiry independently of cleanup.

PDF Import Batches use `StoredObject(backend="documents", multiple=True)` for staged files.
Each descriptor carries its original name, upload row and stable source UUID. Candidates retain
the source UUID; durable preparation receives Quirebase-owned serializable receipt snapshots.
Failed preparation retains reservations for retry, rejected sources release their references, and
confirmation transfers accepted objects to File Revisions and clears staged ownership atomically.
Discard, Workspace purge, object migration and maintenance read the same descriptor field.
Commands and durable workflows manage file lifecycle.

## Signed downloads

`QUIREBASE_SIGNED_DOWNLOADS=true` enables authorized S3 PDF/export routes to return a non-cacheable
307 redirect after current authorization, lineage and physical-existence checks. It requires a
browser-reachable endpoint and bucket CORS. Default transport streams through the application;
local storage always streams. The reader retains its API content URL so subsequent requests
recheck authority.

Core delegates signing to `FileObject.sign_async`, with a configurable 60-second default and
300-second maximum. Export signatures end before artifact expiry. An issued URL remains usable
until expiry after revocation. Core supplies signed transport; commands and workflows manage ownership.

## Directory and product contracts

Workspace, Project, Workspace member, Library Item and administrative User/Audit directories use
`OffsetPagination` with `items`, `total`, `limit` and `offset`. Maximum limit is 100. Workspace,
Project, member and Library defaults are 25; administrative User and Audit defaults are 20 and 50.
Authorization/discovery and search predicates precede counting and slicing. Identity breaks sort
ties, independent counts preserve totals on empty pages, and projections load only page roots.
Project Item joins never multiply the root count. These contracts bound response size and preserve
complete counts as Workspaces grow.

Chooser screens provide search/page controls; menus/selectors load more pages on demand. Selected
and preferred Workspaces resolve directly by identity, because absence from a page does not prove
unavailability. Recovery clears a preference only after `workspace_unavailable`; transient errors
preserve it. Library Project filters resolve selected identities outside loaded pages. Managed
Project governance discovery remains independent of participation and the `mine` view. Dashboard
loads ten participating Projects and reports the full participating count.

Project detail returns `item_count` for assigned Items. Its Item section uses Library's authorized
Project filter with search and independent pages; archived Projects support reading.
Member selectors load more pages and retain selected
identity independently of search results. Governance tables search usernames and recover when
the last row on a page is deleted. Library Search allows updated/created/title sorts and uses native
`ExistsFilter`/`NotExistsFilter` for file presence while counting Item roots. Annotation cursors
and external Provider pages keep their purpose-specific protocols. Item read models that need a
complete choice projection request it explicitly.

Application, workflow, concurrency, browser and schema tests verify these contracts.
Dependency characterization tests document the installed AA behavior separately from application
safety guarantees.

`tests/test_persistence_dependencies.py` characterizes persisted file-descriptor equality.
`tests/test_persistence_boundaries.py` verifies rejected metadata writes, metadata-only copy races,
cleanup and replayable PDF input snapshots on SQLite and PostgreSQL. Architecture checks verify
Module dependencies, model ownership and command responsibilities for side effects and transaction
completion. Single-use SQL executes directly in commands; helper extraction requires actual reuse
and independent complexity.

`tests/test_persistence_operations.py` and
`tests/test_persistence_values.py` exercise caller rollback, constraint recovery, batch/replay
semantics, native UUID identity maps, JSON values and timestamps on both databases. Missing-root
mutation tests verify domain errors without successful Audit Events; controlled PostgreSQL
schedules establish concurrent deletion and locking safety. Schedule injection holds Session
statement execution or commit boundaries.

`tests/test_durable_recovery.py` launches actual DBOS executors in separate processes against
freshly migrated, isolated SQLite/PostgreSQL databases. It kills an executor after completed PDF
extraction and database checkpoints, changes live descriptor metadata, and invokes the production
recovery operation in a fresh process. Replay preserves the original diagnostic filename and does
not repeat checkpointed PDF extraction. It also kills a confirmer after the canonical commit and
replays confirmation from a fresh process, checking Item identity, single Audit/Search/enqueue
effects, atomic file ownership transfer and reference-safe rejected-object cleanup.
