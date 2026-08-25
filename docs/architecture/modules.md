# Module ownership and dependency policy

Quirebase is one bounded context implemented as a modular monolith. Top-level Python
packages are Modules with explicit roles and ownership; directory placement alone does not
make a seam. The enforceable dependency baseline lives in `tests/test_architecture.py`.

Planned deepening work is ordered in `docs/architecture/deep-module-roadmap.md`.

## Package roles and ownership

| Package | Role | Owns |
| --- | --- | --- |
| `accounts` | Business Module | User authentication, Invitations, Login Sessions and login throttling |
| `access` | Domain-policy Module | Authorization decisions over Items, Projects, Documents and Annotations |
| `audit` | Business Module | Audit Event construction, detail serialization and administrative queries |
| `library` | Business Module | Items, Authors, Identifiers, Tags, Item Tag Recommendations, Discussion Messages, Import Batches and Citation Styles |
| `projects` | Business Module | Projects, Project membership and Item assignment |
| `documents` | Business Module | File Revisions, Attachments, Annotations and annotation exports |
| `pipeline` | Business Module | Jobs, leases, retries and PDF inspection handlers |
| `operations` | Business Module | Runtime settings, health, backup and maintenance operations |
| `search` | Outbound adapter Module | The Library Search port plus SQLite and PostgreSQL adapters |
| `web` | Inbound adapter Module | HTTP parsing, authentication dependencies and response formatting |
| `core` | Infrastructure Module | Configuration, database setup, storage, cryptography, i18n and base errors |

## Standalone workspace packages

A deep Module may be split into an independently installable package under `packages/` when all
of these conditions hold:

- its Interface and Implementation are independent of Quirebase business concepts, policy,
  persistence, transactions and application Adapters;
- it concentrates several or heavyweight third-party dependencies whose lifecycle should not
  widen the business Modules' Interface;
- its Interface provides useful Leverage in more than one application scenario or software
  ecosystem; and
- extraction improves Locality by keeping that reusable behaviour and its dependency knowledge
  together, rather than creating a shallow pass-through package.

External-dependency count alone is not sufficient. Business capabilities and their domain errors
remain in Quirebase, and generic helpers that fail the deletion test remain with their owner. A
standalone workspace package must not import `quirebase` or its ORM. When package behaviour enters
a business operation, Quirebase translates package errors into typed domain errors at that seam,
so callers of the business Interface do not learn package-specific error modes. The packages stay
in this monorepo so Interface changes, application Adapters and contract tests can be versioned
and verified atomically.

Current standalone workspace packages are:

- `inquiro`: metadata Provider Search/Lookup, bibliography interchange and CSL citation
  formatting; it isolates HTTP, bibliography-format and optional citation-engine dependencies.
- `rubrica`: keyword extraction, keyphrase ranking and Tag Recommendation computation; it
  isolates YAKE and optional local-model dependencies.

Each standalone workspace package owns tests of its Interface and internal seams under
`packages/<name>/tests`. Root `tests/` owns Quirebase behaviour, application-to-package integration
and cross-workspace architecture and release contracts. The root pytest configuration discovers
all of these test roots so the complete monorepo remains verifiable with one command.

`cli.py` is an inbound adapter. `models.py` is a shared persistence mapping, not a business Module
and not the owner of the concepts it maps. The prototype and decision in
`docs/architecture/orm-ownership.md` retain the centralized mapping: splitting it across
capability packages would distribute SQLAlchemy relationship and import-order knowledge without
deepening business interfaces. Architecture tests enforce one conceptual owner for every mapped
class.

## Interfaces

A Module interface is the smallest surface callers need to exercise a business capability.
For business Modules, prefer use-case operations, typed commands/results and domain errors.
Transport types, ORM query construction, adapter selection and synchronization details stay in
the implementation.

Package `__init__.py` files are convenience entry points, not a published compatibility ABI.
Add exports only for caller-facing use cases, results or errors. Do not re-export concrete
adapters or another Module's interface: callers resolve Library Search through
`quirebase.search.search_index`, never through `quirebase.operations`.

Library-owned Import, Citation Style and Item Tag Recommendation use cases, results and domain
errors are exported through `quirebase.library`. Inbound adapters and other business Modules use
that facade rather than importing Library implementation submodules; Library's own implementation
may use its internal seams directly.

Concrete Search adapters and the Search port remain internal to the outbound adapter Module;
callers select the configured implementation through `search_index`. Mutable Job registries,
low-level document staging, ORM synchronization helpers and operational file utilities likewise
stay in their owning implementation modules rather than package facades.

Citation Style lookup and access control cross the Library Interface. Library delegates CSL
formatting to `inquiro`, but translates its declared engine-unavailable error into a typed domain
error at that seam. Callers therefore do not need to know whether citation formatting is backed by
an optional dependency, and unexpected Implementation failures are not misclassified as input
errors.

Item metadata mutation crosses the Library interface through `create_item`,
`revise_item_metadata` and `regenerate_bibtex_key`. Creation and revision share one flat,
typed `ItemMetadata` value; Contributor, identifier and custom-field values are parsed before
crossing the seam. Permission, optimistic concurrency, persistence caches, Search
synchronization, Audit Event recording and commit order remain in the Library implementation.
These operations return an immutable Item identity and version, not a mutable ORM aggregate.
Their implementation lives in `library.item_metadata`; that internal Module owns writes to one
Item's bibliographic record, not unrelated Item operations.

Operations over a user-selected set of Items live in `library.bulk_items`. This Module owns the
bulk-operation transaction, all-selected authorization rule, audit event and post-commit file
cleanup. Multi-Item document download crosses this Library seam; its implementation may call the
Documents assembly interface for archive construction after selection authorization. Library does
not define single-Item metadata behaviour or Item workspace queries.

Opening an Item crosses the Library interface through `open_item_workspace` with a typed
`WorkspaceSection`. Summary, Metadata, Files, Organize, Annotations and Discussion each return a
section-specific read model; only the Web adapter maps those views to template context. Access
validation, section query selection and recent-reading persistence remain coordinated behind the
same operation seam. The implementation lives in `library.item_workspace`, which owns reads for
one opened Item and no Item mutation or bulk behaviour.

Tag selection is presented by the Item Workspace and committed through `set_item_tags`. Existing
Tags may be matched case-insensitively against an Item Tag Recommendation, while candidates absent
from the taxonomy are returned as suggested names and remain uncommitted until selected by the User. Taxonomy
maintenance crosses the Library interface through rename, delete and `merge_tags`; merging moves
Item associations, refreshes Library Search and deletes the source Tag atomically.

Item Tag Recommendation generation crosses the Library Interface through generation-request and
Job-handler operations. Library owns assembly and cleaning of title, abstract and latest ready
File Revision text, generation fingerprints, persisted recommendation state and stale-Job guards.
Its Implementation calls the reusable `rubrica` Interface for recommendation computation. Model
files for KeyBERT are local administrator-provided inputs; the Adapter never accepts a remote model
identifier. Library metadata writes enqueue generation without committing independently, and
Pipeline invokes the Library-owned durable Job handler.

Opening a Project crosses the Projects interface through `open_project_workspace`, which returns
a typed read model containing the Project, the caller's membership, members and assigned Items.
Membership authorization and the related queries remain coordinated behind that operation; only
the Web adapter maps the typed view to template context.

`inquiro` presents one synchronous `ProviderRuntime` as its reusable Provider Interface. Its two
operations, `lookup` and `search`, return immutable Candidate Record values through a narrow
package facade. The runtime owns the fixed Provider catalog and ordering, identifier parsing,
capability dispatch, typed credentials, input and result validation, error normalization and
transport lifecycle. Callers do not select Provider Implementations or inspect registrations.

Identifier parsing shared by Crossref, DataCite and other Providers belongs to Inquiro's
`identifiers` Module. Each Provider is a leaf Implementation: it may depend on neutral value
types, shared parsing and the private Provider contract, but never on a peer Provider, the runtime
or catalog. One bounded transport Implementation applies timeout, redirect, response-size,
rate-limit and HTTP-error rules before dispatching through the production HTTP Adapter or test
Mock Adapter. Lookup maps an upstream 404 to Candidate-not-found; Search maps it to an empty page.

Provider discovery and dynamic registration are not part of the Interface. The fixed catalog is
private because Quirebase's Provider allowlist, automatic-detection order and credential policy
are product and security invariants. A public extension seam may be extracted only after a second
real ecosystem consumer demonstrates one.

Quirebase owns the business behaviour around Inquiro results. Library constructs and closes the
runtime within each operation, explicitly maps Candidate Records to its write/read models,
translates package failures to typed domain errors and owns Discovery auditing. Web calls the
Library Interface and never imports Inquiro.

Batch PDF Import crosses the Library Interface through `stage_pdf_import_batch` and
`commit_import_batch`. Staging validates at most 50 PDFs, extracts and de-duplicates DOI values,
retrieves Candidate Records and retains only successful staged files. Diagnostics for individual
PDFs do not block confirmation of the remaining candidates. Confirmation creates each Item and
attaches its staged PDF as a File Revision in one transaction. Confirmation revalidates Candidate
Record DOIs against currently accessible Items before writing, and cleanup preserves staged files
still referenced by another pending Import Batch.

All physical Document deletion crosses the Documents interface through
`delete_unreferenced_objects`, which checks File Revisions, Attachments and pending PDF Import
Batches after the caller's transaction commits. In-flight PDF staging holds an object lease until
its reference commits; cleanup coordinates on the same object key and treats active leases as
references. Library never duplicates object reference rules before deleting
content-addressed storage.

An internal helper imported across Modules is an architectural pressure point. Repeated use is
a signal to move the concept to its owner or deepen the owning interface; it is not a reason to
create a generic shared-utilities package.

A zero direct-call count is not sufficient evidence that a business capability is obsolete.
Remove an operation only after its behavior is covered by a deeper interface or an explicit
product decision retires it; test-only use cases require the same review.

## Allowed dependency directions

Every new top-level dependency must be added to the policy test and justified here. Existing
directions are:

| Source | May depend on | Ownership reason |
| --- | --- | --- |
| `access` | `core`, `models` | Evaluate policies using persisted identities and domain errors |
| `accounts` | `audit`, `core`, `models` | Authentication persistence and Audit Event recording |
| `audit` | `core`, `models` | Authorization errors and Audit Event persistence |
| `library` | `access`, `audit`, `core`, `documents`, `models`, `operations`, `pipeline`, `search` | Authorization, persistence and auditing; selected-Item document assembly; runtime Provider/import settings; durable PDF inspection and Tag Recommendation work; search-index synchronization |
| `projects` | `access`, `audit`, `core`, `models`, `search` | Authorization, Project persistence, audit recording and Item index synchronization |
| `documents` | `access`, `audit`, `core`, `models`, `operations`, `pipeline` | Authorization, file persistence, auditing, runtime settings and durable export/inspection jobs |
| `pipeline` | `audit`, `core`, `library`, `models`, `operations`, `search` | Durable execution, audit recording, maintenance and index updates; dispatch of Library-owned Tag Recommendation jobs |
| `operations` | `audit`, `core`, `models` | Infrastructure access, operational persistence and audit recording |
| `search` | `models` | Build and query the derived search representation |
| `web` | Business Modules, `access`, `core`, `models` | Invoke use cases and format their returned ORM-backed views during the current persistence phase |
| `core` | Nothing above infrastructure | Infrastructure must not know business concepts |

Dependencies on standalone workspace packages are also explicit:

| Source | May depend on | Ownership reason |
| --- | --- | --- |
| `library` | `inquiro`, `rubrica` | Adapt reusable metadata, bibliography, citation and recommendation computation to Library business operations and typed domain errors |

Standalone workspace packages never depend back on Quirebase. Audit Event construction and
administrative queries cross only the `quirebase.audit` Interface.

Business Modules never import FastAPI, MCP transports or vendor AI SDKs. Inbound adapters do
not own transactions, ORM persistence, audit recording, object storage or search-index writes.
True external systems receive a port and production/test adapters; local concrete dependencies
remain concrete until a second adapter is justified.

## Change completion criterion

An architecture change is complete when every affected concept has one owner, every new
cross-package dependency is documented and enforced, tests exercise an agreed seam, and the
architecture suite fails if the old violation is reintroduced.
