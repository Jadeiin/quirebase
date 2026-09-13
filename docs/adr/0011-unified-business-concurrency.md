# ADR 0011: narrow business concurrency boundaries

Status: accepted.

## Context

Quirebase serves short Web/API/MCP commands and durable DBOS workflows. PostgreSQL is the only
supported multi-worker deployment; SQLite is a single-process development profile and does not
promise concurrent business results. Concurrency protection must preserve canonical data without
turning every business function into a global lock protocol.

## Decision

Concurrency controls are selected by the invariant they protect:

1. **Snapshot replacement uses version CAS.**
   Bibliographic metadata and annotation edits carry an expected version. The mutation is one
   conditional `UPDATE ... WHERE version = expected RETURNING version`; a missing row is an
   explicit `VersionConflict`. Server commands (DOI rescan, citation-key regeneration and PDF
   inspection) do not consume a client snapshot, but must increment the version when they change
   the Item or annotation.

2. **Cross-row invariants use the owning root row.**
   A Project row protects ownership/state transitions; an Item row protects destructive Item
   deletion and durable child finalization; an ImportBatch row protects confirmation/discard
   identity. The command that owns the invariant acquires the root lock internally. Callers never
   assemble a global `User -> Project -> Tag -> Item -> child` lock graph.

3. **Association mutations use database atomicity.**
   Item–Tag and Project–Item links are additive/delete operations backed by primary keys and
   foreign keys. Duplicate inserts use `ON CONFLICT DO NOTHING` (or an equivalent savepoint
   retry); a concurrent duplicate is success, not a second business event. Taxonomy rename/delete
   and Project rename do not touch Item rows or Library Search projections.

4. **Long-running finalizers re-lock and re-authorize canonical resources.**
   External I/O and expensive computation happen outside business transactions. Before committing,
   a finalizer re-reads the captured User/Project authorization and acquires the canonical Item,
   File Revision, Attachment or ImportBatch root row with the narrowest required lock. Resource
   UUIDs are never reused; row existence plus foreign keys is the lifecycle boundary. A missing
   row is a normal rejected finalization, not a stale lifecycle-token protocol.

5. **Lock only the row that owns the invariant.**
   A command may take a row lock only at its linearization point. Authorization and existence
   checks that merely need to prevent a concurrent delete use a shared lock; ordinary reads remain
   unlocked. No helper may acquire a child lock and then reach back to its parent, and no caller
   may compose locks from unrelated modules.

## Lock strength and ordering

Locks are an implementation detail of the owning command and are held only for the short
transaction that mutates canonical state:

- Plain reads use no row lock.
- A read that must remain present while a related row is inspected uses PostgreSQL `FOR SHARE`
  (`SQLAlchemy.with_for_update(read=True)`). This is the default for non-mutating authorization
  or existence checks that must serialize with a delete.
- A root row that will be mutated without deleting it or changing an FK-referenced key uses
  PostgreSQL `FOR NO KEY UPDATE` (`with_for_update(key_share=True)`). This serializes writers
  while allowing FK checks and child inserts to proceed.
- A root row that may be deleted, or whose FK-referenced key is changing, uses the stronger
  `FOR UPDATE` (`with_for_update()`). Call sites using this stronger lock must document why the
  weaker no-key lock is insufficient.
- A shared lock is never a substitute for a write lock: it protects a read set while allowing
  other readers to proceed, but the owning command must still take `FOR NO KEY UPDATE` or
  `FOR UPDATE` before changing that root row.
- Multiple rows of one aggregate are acquired in stable ID order. No command acquires a child
  row and then goes back to lock its parent.

Queries that include joins must scope the lock to the owning table (SQLAlchemy's `of=` option)
unless locking the joined row is itself part of the invariant. Transactions stay short after a
lock is acquired; external I/O and expensive computation never run while holding a database lock.

SQLite may map these calls to its ordinary transaction semantics; no SQLite-only writer gate or
process lock is required.

## Search projections

Library Search is derived state, not a business invariant. It has two synchronous projections:

- `item_search` contains bibliographic Item metadata only;
- `revision_search` contains extracted text owned by each File Revision.

Metadata writes update `item_search` in the same transaction. Ready/removed File Revisions update
`revision_search` in their own short transaction. Attachments, Tags and Projects never invalidate
Search. There is no Item aggregate sequence, SearchProjectionState, projection generation token or
Search DBOS ordering protocol. A full reindex is an explicit maintenance operation.

Any independent projection rebuild locks its canonical source row with a shared lock before
replacing the projection; generation counters are not required when rebuilds serialize with
canonical writes.

The supported schema-upgrade command is `quirebase init-db`, which runs the forward migration and
then rebuilds both projections before the application is served. Running Alembic directly is an
advanced maintenance operation; after a schema-only upgrade, operators must run the equivalent
full reindex before relying on Search results.

## Project ownership

Project ownership is represented by `Project.owner_id`. The owner is also a ProjectMember with the
`owner` role for presentation and authorization joins. Ownership transfer locks the Project row,
updates `owner_id` and the two membership rows atomically. Removing or leaving the owner is
rejected; no owner-count scan or multi-owner race is needed.

## Import confirmation

The ImportBatch ID is the confirmation identity. A batch is locked before status is read. A ready
batch creates Items and records their IDs, then transitions directly to `committed` in the same
transaction. Repeating confirmation with the same Batch ID returns the recorded IDs; a committed
batch cannot be confirmed with a different payload. There is no `committing` state, commit operation
ID, per-child operation ID or deterministic child-key derivation.

## Consequences

- Concurrent requests may receive an explicit conflict when they target the same version or root
  transition; concurrency safety does not require every request to succeed transparently.
- Database constraints are the final safety boundary for uniqueness, association identity and
  referential integrity.
- Recommendation output is disposable and lower consistency; a newer generation may replace an
  older one without participating in Search ordering.
- Durable object cleanup remains a workflow concern, but Attachment metadata never triggers a
  Library Search rebuild.
- This is an alpha, forward-only cutover. No compatibility shim is provided for removed APIs,
  stored columns or persisted workflow parameters.

The schema cutover is intentionally delivered as one revision after the current head. The
revision may rebuild SQLite tables as needed, but must preserve all child rows while doing so; it
does not retain transitional columns or aliases for older application contracts.

## Rejected alternatives

- A universal lock graph was rejected because it serializes unrelated aggregates and leaks
  authorization mechanics through the business layer.
- Search-owned generation/fence state was rejected because synchronous canonical projections make
  metadata and revision ordering local to their owning rows.
- Soft lifecycle states and lifecycle tokens were rejected because immutable UUID identity plus a
  final Item row lock and foreign keys provide the required deletion boundary.
- Transparent retries of every deadlock/serialization failure were rejected; commands expose a
  retryable conflict where the invariant cannot be made atomic in one statement.
