---
status: accepted
---

# Narrow business concurrency boundaries

Quirebase must protect concurrent commands and durable finalizers without coupling every operation
to a global lock protocol. We use version compare-and-swap for snapshot replacement, owning-root
locks for cross-row invariants, atomic database operations for associations, and renewed authorization
at durable finalization. This keeps concurrency protection with the Module that owns the invariant
while database constraints provide the final integrity boundary.

Lock strengths, ordering, Search projections, Import confirmation and cutover requirements are defined
in the [business concurrency contracts](../architecture/business-concurrency.md).

## Considered options

- A universal lock graph was rejected because it serializes unrelated aggregates and leaks
  authorization mechanics through the business layer.
- Search-owned generation/fence state was rejected because synchronous canonical projections make
  metadata and revision ordering local to their owning rows.
- Soft lifecycle states and lifecycle tokens were rejected because immutable UUID identity plus a
  final Item row lock and foreign keys provide the required deletion boundary.
- Transparent retries of every deadlock/serialization failure were rejected; commands expose a
  retryable conflict where the invariant cannot be made atomic in one statement.

## Consequences

- Conflicting requests may receive explicit version or retryable transaction conflicts; safe
  concurrency does not require every request to succeed transparently.
- Search projections follow their canonical Item or File Revision transaction, while Recommendation
  output remains disposable and may be replaced by a newer generation.
- PostgreSQL supports concurrent multi-worker deployments. SQLite remains a single-process
  development profile without a promise of concurrent business results.
- [ADR 0013](0013-workspaces-as-data-governance-and-acl-boundaries.md) supersedes the original Project
  ownership and role assumptions; Workspace authority and Project participation follow that decision.
- The alpha cutover is forward-only; removed APIs, stored columns and durable workflow parameters
  have no compatibility shim.
