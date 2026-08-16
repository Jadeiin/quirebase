# ADR 0002: organize the modular monolith by business capability

Status: accepted.

Quirebase will remain a single deployable Python application, but its internal
code will be organized around Account, Access, Library, Item, Project,
Document, Annotation, Discovery and Job capabilities. Web routes are adapters:
they parse transport input, invoke one business operation and format the
result. Business operations own permissions, database transactions, audit
events and search-index synchronization.

The existing database schema, HTML routes, form routes, JSON responses and PDF
content routes remain compatible. Quirebase will not introduce a versioned
external interface during this refactor, consistent with ADR 0001. Internal
Python import paths are not compatibility commitments and may change without
re-export shims.

`models.py` remains unified during this refactor. Model-file decomposition may
be reconsidered only after business Module seams are stable.

## Considered options

- Horizontal `models/schemas/services/providers` layering was rejected because
  common feature changes would still require traversal across many shallow
  Modules.
- Immediate frontend/backend separation was rejected because it would add a
  long-lived external Interface without resolving transaction and permission
  coupling.
- Long-term legacy import shims were rejected because the project has no
  published plugin ABI and the shims would become shallow Modules.

## Consequences

- The application is merged only after the full branch passes compatibility
  and architecture tests.
- Intermediate checkpoints remain available for review and rollback.
- Business Modules must not depend on FastAPI.
- Existing Alembic revisions retain their IDs and schema behaviour, but imports
  are updated to the new database Module.

## Implementation notes

Recorded from the completed refactor plan (retired once fully implemented):

- Business failures are raised as typed exceptions
  (`quirebase.core.errors`) and converted to HTTP responses by the Web layer
  and to job statuses by the Job runner, never rendered inside Modules.
- Job handlers are registered through an explicit mapping; decorator-based
  registration via import side effects is not used.
- `LocalObjectStore` remains a concrete implementation until a second storage
  adapter exists; no storage interface is introduced speculatively.
