# Advanced Alchemy persistence boundaries

Status: accepted.

## 1. Context and decision

Quirebase uses SQLAlchemy as its persistence foundation. The multi-Workspace architecture adds
repeated persistence concerns around identifiers, timestamps, structured values, filtering,
pagination, relationship loading, batch writes and stored-object descriptions, while authorization,
Workspace isolation, lifecycle, concurrency, Audit Events and durable workflows retain
application-specific semantics.

Advanced Alchemy is adopted as Quirebase's **persistence implementation toolkit**.

It may provide reusable SQLAlchemy repositories, services, filters, pagination, model/value types,
conversion helpers and storage-related persistence types. It does not become Quirebase's
authorization framework, Workspace-isolation mechanism, transaction manager, concurrency
framework, workflow framework or public business-service architecture.

An AA capability is adopted when it reduces generic persistence maintenance without hiding a
domain invariant or transferring ownership of that invariant outside its Module.

The current verified baseline is Advanced Alchemy 1.11.0 with SQLAlchemy constrained below 2.1.
These versions describe the implementation verified at adoption time, not a permanent architectural
requirement. Behavior relied upon by Quirebase must be revalidated when either dependency changes.

## 2. Module ownership and Core defaults

Centralized ORM mapping does not imply centralized Repository ownership.

Core owns shared AA configuration, common Repository/Service defaults and reusable persistence
types. Concrete repositories and persistence services remain private to the Module that owns their
business capability, consistent with the existing Module and ORM ownership policies.

Core configures AA so persistence operations participate in the caller's existing `AsyncSession`:

- no automatic commit;
- no automatic refresh or expunge;
- raw SQLAlchemy exceptions remain available;
- no additional Unit of Work, transaction interceptor or retry framework is introduced.

Commands and durable workflow steps retain their existing commit and rollback boundaries.
Constraint errors remain available for savepoint recovery and domain conflict translation.

Database-specific compatibility handling remains explicit. Such handling is attributed to the
component that requires it; for example, SQLite transaction behavior is distinct from AA-specific
compatibility work.

## 3. Authorization, write scope and concurrency

An authorized or otherwise constrained `SELECT` may be supplied to an AA Repository for ordinary
reads, filtering, pagination and relationship loading.

That query scope is not a write boundary.

```text
Repository SELECT scope
    != Workspace authorization
    != Workspace write scope
    != concurrency protection
```

Generic Repository mutation methods may construct independent DML and are never assumed to inherit
the Repository's base `SELECT` predicates.

### Workspace mutation invariant

Every mutation of Workspace-owned state must establish, within its owning business transaction:

1. valid authority for the operation;
2. the intended target ownership or lineage;
3. concurrency protection appropriate to that operation.

Concurrency protection may use pessimistic locking, optimistic CAS/version checks, uniqueness or
other database constraints, or an appropriate combination.

Write scope does not require every SQL statement to contain a literal `workspace_id` predicate.
Scope may instead be proven through an already-authorized and concurrency-protected root object or
bounded root-object set.

Valid patterns therefore include:

- explicit DML containing the required lineage, identity and concurrency predicates;
- mutation of roots whose authority, ownership and relevant concurrent state were established by
  the command;
- child or association mutations restricted to identifiers derived from such protected roots,
  where Workspace ownership follows from the relationship.

For example, replacing Contributor or Identifier links for a bounded set of protected Item roots
does not require a redundant Workspace predicate on every association statement.

An attached ORM instance alone is not sufficient evidence. Session attachment does not establish
current authorization, stable lineage or expected version.

Where an operation requires optimistic replacement semantics, it keeps an explicit CAS such as:

```sql
WHERE workspace_id = :workspace_id
  AND id = :item_id
  AND version = :expected_version
```

Mapper versioning may replace application CAS for root mutations emitted by ORM flush only when
it is explicitly configured, the command validates the caller's expected version, and equivalent
concurrency semantics are verified. Authorization and lineage guarantees remain independently
required. Mapper versioning is not assumed to scope or version-check independent bulk DML.

Generic AA bulk mutations are not treated as Workspace-scoped primitives merely because they are
called through a scoped Repository. A Workspace-sensitive bulk mutation must instead use an
operation whose actual SQL supplies the required guarantee or derive its targets from an already
protected root set.

Explicit SQLAlchemy remains first-class where it expresses these guarantees more clearly,
including lock-sensitive commands, CAS updates, lifecycle or membership changes,
dialect-specific `ON CONFLICT`, uniqueness recovery, search queries and reference-aware cleanup.

Database constraints remain the final integrity boundary.

## 4. Private persistence services

AA Services may be used as private Module persistence components when they provide concrete value,
such as:

- conversion into normalized persistence values or write plans;
- coordination of one aggregate across multiple mapped tables;
- pagination and counting;
- batch persistence;
- reusable relationship loading;
- simple result conversion.

They are not Quirebase's public application-service layer.

A persistence Service must not take ownership of:

- authorization or discoverability;
- lifecycle policy;
- command lock ordering;
- Audit Events;
- Search synchronization;
- durable enqueue;
- commit or rollback boundaries.

Library's Item persistence service, for example, may coordinate Item metadata, Contributors,
Identifiers, Provider merge semantics and batch persistence while the surrounding command retains
authorization, locking or CAS, conflict translation, Audit, Search, workflow and transaction
responsibilities.

Thin Services are judged by actual reuse and maintenance benefit. Neither inheritance from an AA
Service nor a small implementation is by itself a reason to retain or remove one.

## 5. Model/value types and object lifecycle

AA model and value types may be adopted where they simplify persistence without weakening
Quirebase-owned constraints.

Entities with creation/update timestamps may use AA UUIDv7 timestamp bases; immutable identities
may use UUIDv7 identity bases; natural or composite-key tables retain an appropriate non-generated
base. Python values use native UUIDs and UTC timestamps where applicable.

UUIDv7 is an identity and index-locality choice, not a claimed application-level performance
guarantee. Protocols with different requirements may retain UUID4.

Structured persistent values may use AA `JsonB`. Domain shape validation remains with the owning
Module, and code must not rely on nested mutation tracking that the selected type does not provide.

Composite Workspace-lineage foreign keys and uniqueness constraints remain explicit schema
invariants.

### Stored objects

`FileObject` is used as a file-description value where its backend, path, size and metadata model
reduce duplicate representations.

`StoredObject` is the ORM column type used to persist those values.

Neither owns the physical object lifecycle.

AA file lifecycle listeners remain disabled. Quirebase application code and durable workflows
continue to own:

- upload ordering;
- ownership transfer;
- retries and idempotent completion;
- reference-safe cleanup;
- migration and reconciliation.

Before crossing a durable workflow boundary, `FileObject` values are converted into
Quirebase-owned serializable snapshots. Those snapshots, rather than AA ORM value objects, form the
durable replay protocol.

Code requiring complete descriptor identity must explicitly include every relevant persisted field.
It must not rely on AA equality semantics where those semantics omit metadata significant to
Quirebase.

AA transport helpers, including signed-object access, may be used only underneath Quirebase's
authorization and lineage checks.

## 6. Product contracts, verification and upgrades

Using an AA implementation primitive does not by itself justify a product or API change.

Directory pagination contracts, Project response shapes, signed-download behavior and similar
product decisions require their own product rationale even when AA helps implement them. Detailed
behavior such as page sizes, empty-page totals, download expiry semantics and initial-schema
cutover belongs in the corresponding Module/API documentation or implementation record rather
than this persistence-boundary ADR.

The current implementation record is [Advanced Alchemy implementation](../architecture/advanced-alchemy-implementation.md).

Verification distinguishes two kinds of tests.

### Dependency characterization

Characterization tests record behavior of the currently supported AA/SQLAlchemy combination where
that behavior affects implementation decisions.

Examples include:

- Repository query scope not constraining independent bulk DML;
- relevant `FileObject` equality or serialization behavior;
- UUID, JSON or Repository behavior on supported databases.

These tests are evidence about a dependency version, not Quirebase security guarantees. If an
upstream upgrade intentionally improves the behavior, the characterization test may change after
the implementation is reviewed.

### Quirebase contracts

Application tests verify guarantees Quirebase owns and must continue to preserve regardless of
dependency behavior.

Workspace mutation tests cover foreign-Workspace identifiers and verify both state and side
effects. Unauthorized operations do not modify target data, emit Audit Events representing
successful mutations, publish Search changes or enqueue mutation-related durable work. Rejected
attempts may be recorded under a separate security-auditing policy.

Concurrency tests verify the required locking, CAS, constraint recovery, rollback and replay
semantics on supported databases.

Object-lifecycle tests protect Quirebase's descriptor snapshot and durable ownership protocols,
including metadata-only descriptor changes where relevant.

Architecture tests may enforce dependency direction, Module ownership, transaction ownership and
known-dangerous call locations. They do not substitute for runtime authorization or concurrency
tests and should not require meaningless wrappers solely to hide inherited AA APIs.

Upgrading AA or SQLAlchemy requires reviewing the affected characterization tests and rerunning
the Quirebase contract suite. Architectural guarantees are preserved even when upstream
implementation details improve or change.

## 7. Consequences

Quirebase delegates common persistence mechanics to Advanced Alchemy while retaining explicit
control over authorization, Workspace isolation, transaction boundaries, concurrency and durable
side effects.

The main benefit is reduced maintenance of generic persistence infrastructure and more consistent
model, query and storage primitives.

The main cost is dependency on AA persistence semantics and corresponding compatibility work.
AA-specific adaptations, such as UUID storage or file-value behavior, remain visible and tested
rather than being mistaken for domain guarantees.

The central rule is therefore:

**Repository query scope is never assumed to be write scope. Every Workspace mutation must
establish valid authority, target lineage and use-case-appropriate concurrency protection. That
scope may be expressed directly by the mutation or derived from an already-authorized and
concurrency-protected root object set.**
