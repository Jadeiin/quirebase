# Business concurrency contracts

This specification expands the [narrow business concurrency boundaries](../adr/0011-unified-business-concurrency.md).
[Module policy](modules.md) defines capability ownership and dependency direction.

Workspace authority and Project participation follow the
[Workspace governance contract](workspace-governance.md). PostgreSQL supports concurrent
multi-worker deployments; SQLite uses the single-host, single-worker deployment profile.

## Concurrency controls

Concurrency controls are selected by the invariant they protect:

1. **Snapshot replacement uses version CAS.**
   Bibliographic metadata and annotation edits carry an expected version. The mutation is one
   conditional `UPDATE ... WHERE version = expected RETURNING version`; a missing row is an
   explicit `VersionConflict`. Server commands such as Citation Key regeneration
   increment the Item version when changing its metadata without a client snapshot.

2. **Cross-row invariants use the owning root row.**
   A Workspace row protects governance and membership; a Project row protects participation/state
   transitions; an Item row protects destructive deletion and durable child finalization; an
   ImportBatch row protects confirmation/discard identity. The command that owns the invariant acquires the root lock internally. Callers never
   assemble a global `User -> Project -> Tag -> Item -> child` lock graph.

3. **Association mutations use database atomicity.**
   Item–Tag and Project–Item links are additive/delete operations backed by primary keys and
   foreign keys. Duplicate inserts use `ON CONFLICT DO NOTHING` (or an equivalent savepoint
   retry); a concurrent duplicate is success, not a second business event. Taxonomy rename/delete
   and Project rename do not touch Item rows or Library Search projections.

4. **Long-running finalizers re-lock and re-authorize canonical resources.**
   External I/O and expensive computation happen outside business transactions. Before committing,
   a finalizer re-reads User activity, Workspace authority and relevant Project facts, then acquires
   the canonical Item, File Revision, Attachment or ImportBatch root row with the narrowest required
   lock. Resource UUIDs are never reused; row existence plus foreign keys is the lifecycle boundary. A missing
   row rejects finalization.

   Ordinary mutating Workspace actions acquire a shared Workspace root guard and reload authority,
   keeping that guard through commit. Exclusive governance changes serialize with those admitted writes.
   Project-scoped commands choose their own Project guard and recheck discoverability after waiting.
   Durable finalizers establish these conditions again after external work rather than carrying a
   request-time decision across checkpoints.


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

## Login signing and credential revocation

Each login request verifies its captured password once, outside a database transaction. Before
signing, Accounts takes the User's `FOR NO KEY UPDATE` lock and reloads active status and the
password hash. A changed hash or inactive/missing User rejects the request without re-verification
or retry. A competing opportunistic rehash also invalidates the captured hash.

The same User lock serializes signing with administrator password reset/deactivation. A login
that signs first is removed by the subsequent revocation; a login waiting behind revocation
rechecks the committed state before signing. Session creation, any hash upgrade, failure-counter
clear and success Audit commit together. A failed login's counter and failure Audit also commit
together. Independent Session/Throttle commands retain their own transaction completion.

## Search projections

Library Search is derived state, not a business invariant. It has two synchronous projections:

- `item_search` contains bibliographic Item metadata only;
- `revision_search` contains extracted text owned by each File Revision.

Metadata writes update `item_search` in the same transaction. Ready/removed File Revisions update
`revision_search` in their own short transaction. Attachments, Tags and Projects never invalidate
Search. A full reindex is an explicit maintenance operation.

Any independent projection rebuild locks its canonical source row with a shared lock before
replacing the projection; generation counters are not required when rebuilds serialize with
canonical writes.

## Workspace ownership and Project participation

Workspace ownership is represented by its active owner membership. Transfer locks the Workspace
root and changes the old and new owner memberships atomically. A Project has no owner or role-bearing membership.
`ProjectParticipant` records explicit working-context selections. Participation changes lock the
Project root and recheck Workspace authority, Project discoverability and participation policy;
there is no minimum-participant invariant.

## Import confirmation

The ImportBatch ID is the confirmation identity. A batch is locked before status is read. A ready
batch creates Items and records their IDs, then transitions directly to `committed` in the same
transaction. Repeating confirmation returns the recorded Item IDs while that committed receipt
exists.

## Conflicts

- Concurrent requests may receive an explicit conflict when they target the same version or root
  transition; concurrency safety does not require every request to succeed transparently.
- Database constraints are the final safety boundary for uniqueness, association identity and
  referential integrity.
- Recommendation output is disposable and lower consistency; a newer generation may replace an
  older one without participating in Search ordering.
- Durable object cleanup remains a workflow concern, but Attachment metadata never triggers a
  Library Search rebuild.
