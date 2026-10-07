# Advanced Alchemy persistence, repositories and services

Status: accepted.

## Decision

Core owns Advanced Alchemy's `SQLAlchemyAsyncConfig` and `EngineConfig`, including its JSON
serializer, session factory and shared metadata. Each request or durable transaction continues
using its existing `AsyncSession`. This extends ADR 0006's persistence decision: Module-owned
repositories and services handle ordinary model reads and writes inside the caller's transaction.
They neither introduce a Unit of Work nor establish another authorization seam.

Core's `Repository`, `ReadService` and `Service` subclasses configure native AA behavior only:
no automatic commit, refresh or expunge, raw SQLAlchemy exceptions, and independent pagination
counts. They add no CRUD implementation. Models remain attached to the caller's Session, while
commands retain their existing commit/rollback boundaries and Audit Event, Search and durable
enqueue ordering. Constraint errors remain available to savepoint recovery and domain conflict
translation. AA not-found errors from repeated mutation reads translate into owned domain
errors when a concurrent deletion removes the root. Audit queries use a read service;
immutable Audit Events still join commands through
the synchronous `record_event` operation.

Core ensures a physical SQLite outer transaction before the first savepoint when sqlite3's
legacy driver has not begun one. Releasing that savepoint therefore cannot commit rows
independently of the caller's rollback. Ordinary reads keep the existing SQLite statement-level
behavior; eagerly beginning read snapshots would turn concurrent CAS conflicts into snapshot
upgrade failures instead of the expected domain conflict.

Repositories name each mapped model inside its owning Module; they are never exported through
business facades. Services provide native pagination, counts, conversion hooks and bulk writes.
Library's Tag service normalizes create/update values, and its Citation Style service validates
CSL and handles concurrent name installation. Operations' runtime-setting service validates the
whole batch before writing, reads existing keys once, and uses native batch create/update with
fresh identity-map values. Concurrent first creation retains a savepoint and bounded progress
through reloading conflicting keys; AA's select-then-write upsert is not an atomic database upsert.
Accounts, Workspaces, Projects, Items, Import Batches and durable Document creation reuse their
Module-owned repositories/services without changing public use-case interfaces.

Authorization and query scoping stay explicit. An authorized root statement may be passed to AA
for filtering and pagination, but its SELECT predicates do not automatically scope arbitrary
generic writes. Workspace lineage, command locks, fresh authority checks and version predicates
remain at the mutation point. CAS updates, membership/lifecycle commands, dialect-specific
`ON CONFLICT` associations, multi-column projections and reference-aware cleanup keep explicit
SQL. No new Session, implicit tenant filter, transaction interceptor or second retry framework is
introduced. Native `ResultConverter.to_schema` replaces attribute-only administrative DTO
mapping in Web; authorization and domain-choice projections remain explicitly authored there,
and Web DTOs never enter business services.

Entities use `UUIDv7AuditBase`; immutable identities use `UUIDv7Base`; natural/composite keys
use `DefaultBase`. All use native Python UUIDs and UTC timestamps. PostgreSQL stores native
UUIDs. The SQLite GUID compiler uses BLOB so UUID bytes and reflected schema have the same
storage type. Independently owned object keys continue using UUID4 for distributed prefixes.
Client-authored Annotation identities retain the UUID4 request protocol.

Structured persistent values use AA `JsonB`: Import Batch snapshots and results, Audit Event
metadata, Item custom fields and Tag Recommendation candidates, PDF geometry and payloads, and
integrity diagnostics. JSON UUID values reload as strings. Commands replace complete values;
AA MutableList does not support replacing dictionaries and does not track nested mutations.
Domain shape validation remains at the owning Module boundary. Bibliographic text/search caches
and canonical Item Identifier associations retain their existing purpose.

Attachment, File Revision PDF/thumbnail, Import Batch staged PDFs and Annotation Export Artifact files use `StoredObject`
and `FileObject`. File metadata has one persisted descriptor. Upload, range/download, copy,
statistics, reference collection and cleanup all read this descriptor. Cross-Workspace copying
captures complete descriptor values and compares them before writing; changes at an unchanged
path still invalidate the source snapshot. Integrity scanning captures values before releasing
its transaction. Thumbnail metadata repair checks the scanned path under a lock and uses an
explicit SQL update, because AA FileObject equality compares path/backend and ignores metadata.
Export downloads resolve the persisted artifact descriptor and enforce its expiry independently
of scheduled cleanup; workflow results retain the source and Project assignment lineage.

PDF Import Batches use `StoredObject(backend="documents", multiple=True)` for staged files.
Each descriptor carries its original name, upload row and stable source UUID; Candidate Records
retain only the source UUID. Durable preparation receives serializable receipt snapshots rather
than ORM file values. Failed preparation retains its reservations for retry. Successful preparation
releases rejected source references; confirmation transfers accepted files to File Revisions and
clears staged ownership in the same transaction as its idempotent Item result. Discard, Workspace
purge, object migration and maintenance read the native descriptor field. File listeners cannot
model this ownership transfer and remain disabled.

S3 PDF and Annotation Export content routes can return a non-cacheable 307 redirect after current
authorization, lineage and physical existence checks. Core delegates signing to
`FileObject.sign_async`, with a configurable 60-second default and 300-second maximum. Export
signatures end before the persisted artifact's expiry. `QUIREBASE_SIGNED_DOWNLOADS=true` enables
this transport after deployment has a browser-reachable S3 endpoint and bucket CORS; the default
streams through the application, supporting private container endpoints. Local storage always
streams. The reader retains its authorized API content URL for subsequent range requests, so each
new request rechecks authority; an already issued URL remains usable until expiry after revocation.

AA file listeners remain disabled: durable workflows own upload-before-commit ordering,
idempotent completion and reference-aware cleanup. The timestamp listener remains disabled:
AuditColumns defaults/onupdate cover ORM and Core writes while preserving explicit timestamps.
Business Audit Events remain in the same mutation transaction. Argon2 inputs are prepared outside
the event loop; the prepared password type exposes a reconstructable representation for Alembic.

Alembic uses its native rendering of AA type representations and dialect variants, without a
custom `render_item` function. The revision template imports the type modules needed by those
representations. Search projections remain dialect-specific DDL. This alpha redesign retains one
autogenerated initial schema and provides no previous-schema conversion path.

## Directory contract and product behavior

Workspace, Project, Workspace member, Library Item and administrative User/Audit directories expose AA `OffsetPagination` (`items`, `total`, `limit`,
`offset`), with a maximum limit of 100. Workspace/Project/member/Library defaults are 25;
administrative User and Audit defaults are 20 and 50. Search and authorization/discovery
predicates precede both root counting and slicing. Ordering includes identity as a tie breaker;
independent counts preserve totals on empty pages. Projection data is loaded for page roots only;
Project Item joins never multiply the paginated root count.

Workspace/Project chooser screens provide search and page controls. Menu and selector lists load
additional pages on demand. Current and preferred Workspaces resolve directly by identity;
absence from a directory page does not establish unavailability. Recovery clears a preference
only after a direct resolution returns `workspace_unavailable`; transient failures preserve it.
Library Project filters also resolve selected identities outside the loaded directory pages.
Managed Project governance discovery remains independent of participation and the `mine` view.
The dashboard loads ten participating Projects and reports the complete participating count.

Project detail returns `item_count` instead of embedding all assigned Items. Its Item section uses
Library Search's authorized Project filter with search and independent pages; archived Project
reading remains available. Member selectors fetch additional pages and retain the selected identity
independently of search results. Governance tables search usernames and recover their page after
removing the last member. Library Search supports an allowlisted updated/created/title sort and
native `ExistsFilter`/`NotExistsFilter` for file presence without multiplying Item counts. Annotation
review/cursor pages and external Provider pages retain their purpose-specific protocols.

API Token conversion uses native `schema_dump` and `ResultConverter.to_schema` for stored fields;
computed token status, session identity, authorization and domain choices remain explicit Web
projections. Bibliography export uses native nested repository `load=` for Item Contributors.

Aggregate-specific Item read models that require a complete choice projection continue explicitly
requesting that projection. They are distinct from the paginated directory API.

Disposable prototype drivers and captured evidence are removed. Application HTTP, workflow,
concurrency, browser and schema tests own the continuing verification.
