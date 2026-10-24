# Module ownership and dependency policy

Quirebase is one bounded context implemented as a modular monolith. Top-level Python packages
have explicit roles and owners. `[tool.importlinter]` in `pyproject.toml` enforces import boundaries;
`tests/test_architecture.py` checks symbol-level facades, model ownership and command responsibilities.

## Package roles and ownership

| Package | Role | Owns |
| --- | --- | --- |
| `accounts` | Business Module | Users, authentication, instance Invitations, Login Sessions, API Tokens and login throttling |
| `workspaces` | Business Module | Workspace provisioning, membership, invitations, ownership and lifecycle governance |
| `access` | Domain-policy Module | System and Workspace resource-action authorization |
| `audit` | Business Module | Audit Event construction, invocation provenance, detail serialization and administrative queries |
| `library` | Business Module | Items and Work metadata, Tags, recommendations, Discussions, Import Batches, Citation Styles and Discovery orchestration |
| `projects` | Business Module | Projects, participation and Item assignment |
| `documents` | Business Module | File Revisions, Attachments, Annotations/Replies, PDF inspection, thumbnails, exports and reference-aware object cleanup |
| `operations` | Business Module | Runtime settings, health, backup, reconciliation and maintenance workflows |
| `search` | Outbound adapter Module | Library Search interface and SQLite/PostgreSQL projections |
| `web` | Inbound adapter Module | HTTP parsing, credential selection, Origin enforcement, API projections and static application delivery |
| `mcp` | Inbound adapter Module | Curated OpenAPI-to-MCP projection, API Token adaptation and trusted invocation provenance |
| `core` | Infrastructure Module | Configuration, database setup, object transport, DBOS adapter, cryptography and base errors |

`frontend/` is the Web UI adapter: a static Svelte application calling `/api/v1`. It owns routing,
remote-state presentation, localization, UI patterns, Rich Text rendering and EmbedPDF integration.
[Application and HTTP contracts](application-http-boundary.md) define that boundary.

`cli.py` is an inbound adapter and application bootstrap. It registers capability-owned workflows.
`models.py` is the shared persistence mapping; [ORM ownership](orm-ownership.md) assigns each mapped
concept to a business owner.

## Standalone workspace packages

`inquiro` owns scholarly Provider I/O, neutral Commonmeta Work values, bibliography interchange,
Citation Key generation and CSL rendering. Its asynchronous `ProviderRuntime` exposes `lookup`,
`lookup_many`, `search` and `acquire_document`, containing the fixed catalog, credentials,
validation, transport and resource lifetime. Providers are independent leaves below a private
catalog. Shared identifier parsing and bounded HTTP exchange belong inside the package. See the
[Inquiro interface](../../packages/inquiro/README.md) and
[Provider runtime decision](../adr/0005-deep-standalone-provider-runtime.md).

Identifier Import shares one runtime for its batch. Inquiro owns bounded lookup scheduling,
arXiv/PubMed native request merging and per-input results; Library owns Work write validation,
Import diagnostics, reauthorization and persistence. OpenAlex/Crossref retain singleton endpoints.
Durable PDF preparation extracts identifiers per file and calls `lookup_many` for each Provider group.
Library checkpoints group outcomes, retries only unavailable inputs with a bounded durable wait budget,
and retains deferred PDFs as optional basic candidates. Ready-preview retries preserve successful
siblings. Inquiro preserves rate-limit hints in exceptions and batch failure values.

`excerpo` owns keyword extraction and keyphrase ranking through YAKE and optional local KeyBERT.
Library supplies the source text and owns recommendation generation, stale-workflow guards and
persistence. KeyBERT loads administrator-provisioned local model files.

A standalone package is appropriate when reusable behavior is independent of Quirebase policy,
persistence and adapters, and it hides substantial dependency knowledge behind a useful interface.
It stays in the monorepo so package changes and application adapters can be verified together.
Package tests live under `packages/<name>/tests`; root tests own application integration and
cross-package contracts. Standalone packages are independent of Quirebase and its ORM.

## Business interfaces

Facades expose owned use cases, typed commands/results and domain errors. Implementations retain
transport conversion, query construction and adapter selection. Library callers use
`quirebase.library`; Library itself may use internal seams. Search callers resolve the configured
adapter through `quirebase.search.search_index`. Concrete adapters, DBOS registration helpers and
low-level file staging stay with their implementations.

Business commands own authorization, Audit, Search synchronization, durable enqueue and transaction
completion. Shared owner operations participate in the caller's Session and state explicitly
whether they complete that transaction. External I/O finishes outside business transactions;
durable finalizers reload authority and canonical resources before publishing. The
[concurrency contract](business-concurrency.md) defines CAS and root locking.

Workspace authority resolves into `access.WorkspaceContext` at request or workflow boundaries.
Read models reuse it; mutation commands reload current facts under their own guards. A command
that changes its actor's membership records the authorizing role captured before that change in
Audit; subsequent commands resolve fresh facts. Access owns
Casbin policy and validates the relation facts supplied to each action. Frontend views consume
server-authored decisions and concrete choices, such as permitted participation modes or roles.
The [governance contract](workspace-governance.md) defines those facts and the
[generated authorization matrix](authorization-matrix.md) records effective grants.

### Accounts and Workspace governance

Accounts owns instance Invitation acceptance, revocation and reissue. Revocation preserves its
record and token hash; reissue creates a new Invitation and revokes the old one. Only an
unaccepted, unrevoked Invitation reserves its username. Creation retires an expired reservation
transactionally. Conditional writes arbitrate acceptance/revocation/reissue, with provisioning and
Audit committed atomically. Tokens appear in one-time creation responses, not history or Audit.

Workspaces owns membership generations, invitation invalidation, root lifecycle and ownership
reassignment. Accounts locks the target User before invoking the Workspace deactivation guard;
Accounts retains account status, session revocation, Audit and commit. The focused
[deactivation and reassignment contract](account-deactivation-and-owner-reassignment.md) defines
User-before-Workspace coordination.

### Library and document composition

Library owns validation, merging, Item version CAS, duplicate suggestions and Import recovery;
Inquiro owns the external Work contract and neutral conversion. Search uses neutral projections.
The frontend consumes generated HTTP types and Library's authorized schema endpoint. The
[Work contract](item-metadata-json.md) defines metadata writes, comparison and interchange limits.

`open_item_section` coordinates access, reading history and typed Overview, Metadata, Files,
Organize, Annotations and Discussion read models. Library composes Documents-owned summaries and
Projects-owned discoverable choices; Web maps the resulting section to HTTP. `bulk_items` owns
selected-set validation, concrete action checks, one Audit Event and the bulk transaction. It may
call Documents for archive assembly or Projects for assignment inside that transaction.

Projects owns participation and assignment mutations under its root guards. Documents owns
Annotation/Reply validation, versions, audience coordination and export. The
[canonical Annotation and viewer contract](../adr/0010-canonical-annotations-and-embedpdf-adapter.md)
keeps EmbedPDF values in the frontend adapter.

Documents owns object references, final cleanup checks, descriptor retirement and physical deletion.
Library supplies retained PDF staging facts; Operations supplies inventory, scheduling and reporting.
[Object lifecycle contracts](object-lifecycle.md) define these cross-module operations, copy,
Workspace teardown and durable cleanup checkpoints.

## Allowed dependency directions

Every top-level dependency has an ownership reason and a matching import contract.

| Source | May depend on | Ownership reason |
| --- | --- | --- |
| `access` | `core`, `models` | Policy facts, identities and domain errors |
| `accounts` | `access`, `audit`, `core`, `models`, `operations`, `workspaces` | Authentication, registration policy, provisioning and deactivation guard |
| `audit` | `access`, `core`, `models` | Authorization and Audit persistence |
| `library` | `access`, `audit`, `core`, `documents`, `models`, `operations`, `projects`, `search` | Item use cases, file assembly, organization, runtime settings and projections |
| `projects` | `access`, `audit`, `core`, `documents`, `models` | Project use cases and Annotation cleanup on detachment |
| `documents` | `access`, `audit`, `core`, `library`, `models`, `operations`, `search` | Documents, staging-reference facts, runtime settings and revision projections |
| `operations` | `access`, `accounts`, `audit`, `core`, `documents`, `library`, `models`, `search`, `workspaces` | Operational use cases and owner-provided maintenance operations |
| `search` | `models` | Derived Search representation |
| `workspaces` | `access`, `audit`, `core`, `documents`, `library`, `models`, `operations`, `search` | Governance, creation policy and Workspace teardown |
| `web` | `access`, `accounts`, `audit`, `core`, `documents`, `library`, `mcp`, `models`, `operations`, `projects`, `search`, `workspaces` | HTTP adapters, projections and application composition |
| `mcp` | `accounts`, `audit`, `core` | Verify tokens, bind provenance and invoke the API in-process |
| `models` | `core` | Shared persistence value types and metadata |
| `cli` | `accounts`, `core`, `documents`, `library`, `models`, `operations`, `projects`, `search`, `workspaces` | Bootstrap and operator commands |
| `core` | Infrastructure dependencies | Shared runtime mechanisms |

The Documents → Library edge consumes only `import_staging_object_keys` through the Library facade,
imported at execution time to avoid initialization cycles. Workspaces consumes the same fact.
Operations uses owner-provided object protection/deletion, export retirement, Annotation purge,
Import Batch expiration and account/membership retention operations. Owners supply predicates;
Operations supplies cutoffs, batching and commits. Business callers of Operations implementation
modules use runtime settings only. Symbol-level architecture tests constrain these surfaces.

Dependencies on standalone packages are explicit:

| Source | May depend on | Boundary |
| --- | --- | --- |
| `library` | `inquiro`, `excerpo` | Adapt metadata, bibliography, citations and recommendations to business operations |
| `documents` | `inquiro.richtext` | Plaintext archive names and manifests |
| `search` | `inquiro.richtext`, `inquiro.work` | Plaintext and neutral Work projections |
| `models` | `inquiro` | Neutral generated Work value type |

Provider orchestration crosses Library. Business modules are independent of HTTP/MCP frameworks
and vendor AI SDKs; inbound adapters invoke owned commands rather than writing persistence or
Search themselves. True external systems have production/test adapters; local dependencies
remain concrete until another implementation is needed.

Run `uv run lint-imports` or `make lint-architecture`. Protected contracts include type-checking
imports, and layer/independence contracts cover Bibliography, Providers and Search adapters.
Architecture and behavior tests cover the symbol and transaction responsibilities beyond imports.
New modules need an owner, role and enforced dependency boundary; tests use the seams described in
[Testing](../TESTING.md).
