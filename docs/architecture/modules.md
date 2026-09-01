# Module ownership and dependency policy

Quirebase is one bounded context implemented as a modular monolith. Top-level Python
packages are Modules with explicit roles and ownership; directory placement alone does not
make a seam. The enforceable dependency baseline lives in `tests/test_architecture.py`.

Planned deepening work is ordered in `docs/architecture/deep-module-roadmap.md`.

## Package roles and ownership

| Package | Role | Owns |
| --- | --- | --- |
| `accounts` | Business Module | User authentication, Invitations, Login Sessions, API Tokens and login throttling |
| `access` | Domain-policy Module | Authorization decisions over Items, Projects, Documents and Annotations |
| `audit` | Business Module | Audit Event construction, programmatic invocation provenance, detail serialization and administrative queries |
| `library` | Business Module | Items, Authors, Identifiers, Tags, Item Tag Recommendations, Discussion Messages, Import Batches and Citation Styles |
| `projects` | Business Module | Projects, Project membership and Item assignment |
| `documents` | Business Module | File Revisions, Attachments, Annotations, uploads, PDF inspection, thumbnails and annotation-export workflows |
| `operations` | Business Module | Runtime settings, health, backup, reconciliation and maintenance workflows |
| `search` | Outbound adapter Module | The Library Search port plus SQLite and PostgreSQL adapters |
| `web` | Inbound adapter Module | HTTP parsing, authentication dependencies and response formatting |
| `mcp` | Inbound adapter Module | MCP tool registration, API Token adaptation and protocol conversion |
| `programmatic` | Application Interface Module | Shared response contracts and pure projections used by the HTTP API and MCP adapters |
| `core` | Infrastructure Module | Configuration, database setup, UUID object storage, DBOS Adapter, cryptography, i18n and base errors |

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
callers select the configured implementation through `search_index`. DBOS registrations,
low-level document staging, ORM synchronization helpers and operational file utilities likewise
stay in their owning implementation modules rather than package facades.

Citation Style lookup and access control cross the Library Interface. Library delegates CSL
formatting to `inquiro`, but translates its declared engine-unavailable error into a typed domain
error at that seam. Callers therefore do not need to know whether citation formatting is backed by
an optional dependency, and unexpected Implementation failures are not misclassified as input
errors.

`inquiro.bibliography` is a package facade: the only supported import surface for neutral
records, bibliography interchange, Citation Key generation, Citation Style catalog access and CSL
rendering. Its internal modules (`records`, `options`, `keys`, `formats`, `styles`, `engine`) are private
implementation seams with a test-enforced layer order (records/options → keys →
formats/styles → engine); nothing inside the package may import a higher layer, and nothing
outside may bypass the facade. One options class (`BibliographyExportOptions`) carries every
export preference; validation is concentrated in `export_bibliography_records`. Shared payload
cleaning and reference-type normalization live in `inquiro.canonical`; Provider-specific payload
helpers stay private inside `inquiro.providers`. The Item-column dictionary encoding stored on
Import Batches belongs to the Library Module; Inquiro exchanges typed records only.

Scholarly inline Rich Text crosses the Inquiro Interface through one restricted conversion
operation. Its canonical application representation is sanitized HTML containing only `i`, `b`,
`sup` and `sub`, without attributes. The private Implementation maps the equivalent supported
LaTeX commands (`emph`, `mkbibemph`, `textit`, `textbf`, `textsuperscript` and `textsubscript`) to
Inquiro-owned nodes and renders canonical HTML, LaTeX or plaintext. Library stores canonical HTML
for Item titles and abstracts; Citation Key generation, Search, recommendations, archive names and
non-rich export formats explicitly request plaintext. Inline `$...$` formulae remain verbatim in
the canonical representation and bibliography round-trips. Only the Web output Adapter projects
them through `latex2mathml` into MathML, then rebuilds the result through a strict element and
attribute allowlist before marking it safe for template rendering. `pylatexenc`, `latex2mathml`
and bibliography implementation types do not cross the Interface.

Item metadata mutation crosses the Library interface through `create_item`,
`revise_item_metadata` and `regenerate_bibtex_key`. Creation and revision share one flat,
typed `ItemMetadata` value; Contributor, identifier and custom-field values are parsed before
crossing the seam. Permission, optimistic concurrency, persistence caches, Search
synchronization, Audit Event recording and commit order remain in the Library implementation.
These operations return an immutable Item identity and version, not a mutable ORM aggregate.
Their implementation lives in `library.item_metadata`; that internal Module owns writes to one
Item's bibliographic record, not unrelated Item operations.
`ItemMetadata` is a transport-neutral business command and may be used directly by inbound
Adapters that can derive their wire schema from dataclasses; they must not maintain mirrored input
models. Response contracts shared by both programmatic Adapters live in `programmatic`; HTML-only
or protocol-only projections remain owned by their Adapter.

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
workflow operations. Library owns assembly and cleaning of title, abstract and latest ready
File Revision text, generation fingerprints, persisted recommendation state and stale-workflow guards.
Its Implementation calls the reusable `rubrica` Interface for recommendation computation. Model
files for KeyBERT are local administrator-provided inputs; the Adapter never accepts a remote model
identifier. Library metadata writes enqueue generation transactionally through Core's DBOS
Adapter, and the Library-owned workflow invokes the Library operation.

Opening a Project crosses the Projects interface through `open_project_workspace`, which returns
a typed read model containing the Project, the caller's membership, members and assigned Items.
Membership authorization and the related queries remain coordinated behind that operation; only
the Web adapter maps the typed view to template context.

`inquiro` presents one asynchronous `ProviderRuntime` as its reusable Provider Interface. Callers
use `async with` and await its operations; `lookup` and `search` return immutable Candidate Record values, while
`acquire_document` returns a managed `AcquiredDocument` stream and immutable receipt metadata.
The runtime owns the fixed Provider catalog and ordering, identifier parsing, document-source
classification, capability dispatch, typed credentials, input and result validation, error
normalization and transport lifecycle. Callers do not select Provider Implementations or inspect
registrations.

Identifier parsing shared by Crossref, DataCite and other Providers belongs to Inquiro's
`identifiers` Module. Each Provider is a leaf Implementation: it may depend on neutral value
types, shared parsing and the private Provider contract, but never on a peer Provider, the runtime
or catalog. One bounded transport Implementation applies timeout, response-size, rate-limit and
HTTP-error rules before dispatching through the production HTTP Adapter or test Mock Adapter.
Metadata requests reject redirects; PDF acquisition follows a bounded redirect chain, streams into
a managed temporary file, enforces the document-size limit and validates the PDF header. Lookup
maps an upstream 404 to Candidate-not-found; Search maps it to an empty page.

Provider discovery and dynamic registration are not part of the Interface. The fixed catalog is
private because Quirebase's Provider allowlist, automatic-detection order and credential policy
are product and security invariants. A public extension seam may be extracted only after a second
real ecosystem consumer demonstrates one.

Quirebase owns the business behaviour around Inquiro results. For lookup and Search, Library
constructs and closes the runtime within each operation, explicitly maps Candidate Records to its
write/read models, translates package failures to typed domain errors and owns Discovery auditing.
Document acquisition is currently a standalone Inquiro capability; any Quirebase workflow that
adopts it must cross the Library Interface rather than importing Inquiro from Web.

Batch PDF Import crosses the Library Interface through `stage_pdf_import_batch` and
`commit_import_batch`. Staging validates at most 50 PDFs, extracts and de-duplicates DOI values,
retrieves Candidate Records and retains only successful staged files. Diagnostics for individual
PDFs do not block confirmation of the remaining candidates. Confirmation creates each Item and
attaches its staged PDF as a File Revision in one transaction. Confirmation revalidates Candidate
Record DOIs against currently accessible Items before writing, and cleanup preserves staged files
still referenced by another pending Import Batch.

The Core Infrastructure Module owns one thin `ObjectStore` facade over obstore's Local and S3
data planes. Business Modules operate on object keys, metadata and asynchronous byte streams;
obstore types and backend configuration do not cross that seam. Components that require a local
`Path`, including PyMuPDF, use the facade's scoped materialization operation. HTTP adapters pass
the returned obstore-backed byte stream directly to `StreamingResponse`; streaming ZIP assembly
uses one unbuffered async-generator bridge and selects `ZIP_AUTO` from each member's known size.

All physical Document deletion crosses the Documents interface. Every logical upload owns one
preallocated UUID object, so rollback and terminal workflow cleanup can delete that key without a
reservation or local lock. The workflow-first upload interface creates a DBOS execution, streams
the object, and sends a durable completion message; retryable Documents steps validate and derive
content before a short idempotent database commit. File Revision changes enqueue the
Library-owned `FileRevisionChanged` workflow rather than creating a reverse dependency. Operations
reconciliation only deletes old managed UUID objects after excluding database references and
active workflow ownership twice. Unknown keys and doctor probes are never managed.

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
| `library` | `access`, `audit`, `core`, `documents`, `models`, `operations`, `search` | Authorization, persistence and auditing; selected-Item document assembly; runtime Provider/import settings; Library-owned workflows and search-index synchronization |
| `projects` | `access`, `audit`, `core`, `models`, `search` | Authorization, Project persistence, audit recording and Item index synchronization |
| `documents` | `access`, `audit`, `core`, `models`, `operations` | Authorization, owned-object persistence, auditing, runtime settings and Documents workflows |
| `operations` | `audit`, `core`, `library`, `models`, `search` | Infrastructure access, operational persistence, maintenance workflows, global rebuild coordination and audit recording |
| `search` | `models` | Build and query the derived search representation |
| `web` | Business Modules, `access`, `core`, `mcp`, `models`, `programmatic` | Invoke use cases, expose the Bearer-authenticated HTTP API with API Token provenance, format views and compose the MCP HTTP mount into the application |
| `mcp` | `accounts`, `audit`, `core`, `documents`, `library`, `programmatic`, `projects` | Resolve a verified token subject, bind invocation provenance for business Audit Events, manage request persistence lifetime, invoke ordinary User use cases and format protocol results without owning their authorization or transactions |
| `programmatic` | `documents`, `library` | Define shared programmatic response contracts and pure projections without owning authentication, transactions or business authorization |
| `core` | Nothing above infrastructure | Infrastructure must not know business concepts |

Dependencies on standalone workspace packages are also explicit:

| Source | May depend on | Ownership reason |
| --- | --- | --- |
| `documents` | `inquiro` | Render canonical scholarly Rich Text as plaintext for archive filenames and manifests |
| `library` | `inquiro`, `rubrica` | Adapt reusable metadata, bibliography, citation and recommendation computation to Library business operations and typed domain errors |
| `search` | `inquiro` | Project canonical scholarly Rich Text into the plaintext derived search representation |
| `web` | `inquiro` | Sanitize and render canonical scholarly Rich Text at the HTML output Adapter |

The `documents`, `search` and `web` edges are restricted to `inquiro.richtext`; they do not permit
those Modules to call Provider, bibliography or citation operations. Those business workflows
still cross Library.

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
