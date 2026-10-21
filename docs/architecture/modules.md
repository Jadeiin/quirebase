# Module ownership and dependency policy

Quirebase is one bounded context implemented as a modular monolith. Top-level Python
packages are Modules with explicit roles and ownership; directory placement alone does not
make a seam. Import boundaries are declared under `[tool.importlinter]` in `pyproject.toml`.
`tests/test_architecture.py` enforces ownership, facade exports and command responsibilities
that cannot be expressed through module imports.

Planned deepening work is ordered in `docs/architecture/deep-module-roadmap.md`.

## Package roles and ownership

Workspace commands are implemented by `creation` (including provisioning), `directory`,
`invitations`, `membership`, `lifecycle` and `governance` inside `workspaces/`.
`workspaces.__init__` exports their owned operations directly. The private `_locking` module
owns exclusive Workspace-root acquisition and fresh target-member loading; callers recheck
authority and state while retaining that root lock. Invitation invalidation stays owned by
`invitations`; `workflows` requires an absent Workspace before calling Documents for
reference-aware physical cleanup. Authorization, root deletion and cleanup enqueue are atomic;
cleanup does not depend on retained Audit Events. `membership.guard_user_deactivation` locks current membership Workspace roots in stable
UUID order after Accounts has locked the target User. It allows inactive ownership while retaining
those locks without committing. Accounts retains account
status, session revocation, Audit and commit. These are implementation files within one Business Module, rather than additional service or repository layers.
`governance.reassign_workspace_owner` owns explicit reason-bound owner reassignment, User-before-root
coordination, receiving membership admission/reactivation and the atomic Audit Event.

Frontend principal-role comparisons cannot select behavior; ESLint guards direct comparisons
and `includes` checks, while backend architecture tests guard direct WorkspaceContext role
branches outside Access. Role labels and target-role form values remain presentation facts. Access validates typed Workspace
actions against their accepted relation facts before invoking policy; malformed facts are programming
errors, while valid facts without a grant remain permission denials.
The [generated capability matrix](authorization-matrix.md) makes effective policy changes
reviewable without maintaining another grant table.

The GitHub Actions [`postgres` job](../../.github/workflows/ci.yml) runs on pushes, pull requests,
manual dispatches and scheduled CI runs. It checks database and JSON query contracts, controlled
concurrency, migrations and durable recovery, followed by fresh database initialization and
durable-workflow diagnostics. Direct pushes to `main` do not require this check to have completed
on a separate branch.

| Package | Role | Owns |
| --- | --- | --- |
| `accounts` | Business Module | User authentication, Invitations, Login Sessions, API Tokens and login throttling |
| `workspaces` | Business Module | Workspace provisioning, membership, invitations, ownership and lifecycle governance |
| `access` | Domain-policy Module | Authorization decisions over Items, Tags, Projects, Documents and Annotations |
| `audit` | Business Module | Audit Event construction, programmatic invocation provenance, detail serialization and administrative queries |
| `library` | Business Module | Items and their Contributors, Identifiers, Tags, Item Tag Recommendations, Discussion Messages, Import Batches and Citation Styles |
| `projects` | Business Module | Projects, Project participation and Item assignment |
| `documents` | Business Module | File Revisions, Attachments, Annotations, uploads, PDF inspection, thumbnails, annotation-export workflows and Annotation Export Artifacts |
| `operations` | Business Module | Runtime settings, health, backup, reconciliation and maintenance workflows |
| `search` | Outbound adapter Module | The Library Search port plus SQLite and PostgreSQL adapters |
| `web` | Inbound adapter Module | HTTP parsing, Login Session/API Token credential selection, Origin enforcement, API routing, response formatting and static application delivery |
| `mcp` | Inbound adapter Module | Curated OpenAPI-to-MCP projection, API Token adaptation, trusted invocation provenance and protocol conversion |
| `core` | Infrastructure Module | Configuration, database setup, UUID object storage, DBOS Adapter, cryptography and base errors |

The TypeScript workspace under `frontend/` is the Web UI adapter. It owns responsive application
composition, client-side routing, remote-state caching, frontend localization, semantic design
tokens, Web Rich Text projection and the EmbedPDF Svelte integration. Inline `$...$` formulae are
rendered through Temml, then rebuilt through a strict MathML element and attribute allowlist before
entering the sole raw-HTML rendering seam. Gettext PO files under `frontend/src/lib/locales` are
the only manually edited translation catalogs; Lingui extracts English message IDs from Svelte
and compiles ignored TypeScript runtime catalogs during checks and builds. It calls `/api/v1` and
does not import or reproduce Python business behavior. Its generated output stays in
`frontend/build`; FastAPI serves that directory directly in source checkouts, while the wheel
builder includes it as frontend data without writing generated files into `src/quirebase`. It is
not a separately deployed server.

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
  formatting; it isolates HTTP, bibliography-format, citation-engine and optional style-catalog dependencies.
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

The CLI also owns application bootstrap: its import contracts explicitly permit Accounts, Core,
Documents, Library, Models, Operations, Projects, Search and Workspaces. Bootstrap registers owned
durable workflows through their implementation modules; ordinary Library callers use its facade.
The persistence mapping may import Core, and no other Module may import the CLI.

## Commonmeta capability boundary

Inquiro owns the external Work schema, generated neutral types, bounded Provider transport,
reader/writer orchestration and comparison normalization. Quirebase Library owns Item title/size
and Citation Key limits, authorized Workspace lookup, partial merge policy, duplicate suggestions,
CAS, persistence and ImportBatch recovery. Search uses neutral Work projections only. Frontend
uses generated HTTP types and the authorized official-schema endpoint. The Web UI Adapter owns
schema-renderer configuration, localized controls, complete Work drafts and field-error/conflict
presentation. Its Draft-07 rendering conversion never replaces original-schema validation or
Library's write policy. Inquiro selects active Contributor entities only in neutral projections
and temporary writer inputs, preserving complete Work snapshots for persistence and Commonmeta
export. Neither Inquiro nor commonmeta-py knows Workspace, Item UUID or database identity. See
[ADR 0015](../adr/0015-commonmeta-work-and-duplicate-suggestions.md).

## Interfaces

Accounts owns the instance Invitation lifecycle. Revocation preserves the record and hashed
token; reissue revokes the old Invitation and creates a new one with the same username and
System Role. Only an unaccepted, unrevoked Invitation reserves its username. Creating another
Invitation retires an expired reservation in the same transaction; User usernames remain unique.
Accept, revoke and reissue use conditional writes to arbitrate concurrent requests, with User
provisioning and Audit committed atomically. Repeated revocation preserves its original timestamp
and event; repeating reissue against the old record fails rather than creating another link.
Creation, revocation and reissue record the administrator and Invitation identity; acceptance
records its source Invitation. Tokens appear only in creation/reissue responses, never in Audit
or history. The Web adapter owns the independently paginated, state-filtered administrative
history and one-time link presentation under `/admin/invitations`. User administration lives
under `/admin/users`; each route owns one resource list, its queries and one pagination control.
A schema downgrade refuses duplicate historical
usernames instead of deleting Invitation history to restore the old unique constraint.

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

Workspace authorization is resolved once at an inbound request or workflow boundary into an
`access.WorkspaceContext`. Read models reuse that context and project decisions from loaded facts.
Mutation commands retain actor/Workspace identifiers, acquire their transaction locks and reload
authority; a request-time context must not replace those checks or cross durable checkpoints.
The context captures the role used for authorization: a command that changes its actor's
membership records the original role in its Audit Event, then later commands resolve fresh facts.
The HTTP boundary returns the same `workspace_unavailable` 404 for a missing Workspace and an
absent, suspended or terminated membership. An admitted member lacking a capability still
receives `permission_denied` 403; authentication failures remain 401.
Business operations may use the thin `access.workspace_select()`
lineage primitive and Module-owned aggregate loaders (`get_item`, `get_project`,
`get_project_item`, and document loaders). The primitive only adds the Workspace lineage
predicate; one concrete resource-action decision remains an explicit Access gate while Project
participation contributes fixed domain discovery rules and concrete command facts, and mutation
statements express their Workspace and CAS predicates at the linearization point. Module-owned
commands apply pure normalization and directly execute SQLAlchemy reads/writes after authorization;
transaction ownership stays with the use-case command or durable datasource transaction.
Only actually reused, independent and sufficiently complex mechanisms are extracted into private
functions in the owning business modules. Business Module Interfaces expose the owned use cases.
AA's native schema converter runs in Web, and business operations receive domain values.
Core owns AA configuration, shared value types, native dialect INSERT
selection and filtered pagination together in `core.persistence`, as described in ADRs 0006 and 0014.
Commands express CAS predicates, lock order, lineage checks, idempotent association SQL and
reference-aware cleanup through their SQLAlchemy operations.

Architecture checks verify dependency direction, model ownership and command responsibilities for
authorization, Audit, Search, durable enqueue and transaction completion.
Internal write functions derive association targets from protected roots and preserve explicit
scope/concurrency predicates. Application and database tests establish the actual guarantees,
as required by ADRs 0006 and 0014.

The Access Module owns one immutable Casbin model and policy bundle packaged with the application.
Casbin is the sole Workspace/System resource-action capability policy evaluator. System and Workspace requests
both use `subject + resource + action + lifecycle + relation`; there is no separate capability
namespace or preliminary coarse-grained gate. Relations such as author/other, Workspace-member class and
command participation variants are inputs to that decision. Ordinary Project discovery remains
fixed domain behavior; only the additional `project_governance.read` privilege is decided by Casbin.
Business Modules still load canonical User, membership, lifecycle, lineage, authorship and
participation facts, retain their transaction locks and database constraints, and re-evaluate after
the relevant lock when authority can change. The frontend receives only server-authored allowed
resource-action sets and calls `can(action)`. Domain choices are projected through concrete fields:
`allowed_project_participations`, `allowed_participation_changes`, `allowed_invitation_roles` and
`allowed_roles`. The frontend renders those values and never reconstructs policy from roles.
Dotted keys in the wire contract and Audit Events serialize a resource/action pair; they do not
define a second policy vocabulary. MCP continues through the generated HTTP API and the same
business enforcement points; durable workflows re-read facts and authorize each attempt rather
than persisting an earlier decision.

The policy bundle is organized as inherited role deltas and then by resource/action. CRUD-like
operations use `create`, `read`, `update` and `delete`; relation facts distinguish own-author and
moderation decisions instead of introducing action aliases. Domain transitions keep their
specific verbs, and `manage` is used only when the policy deliberately grants a whole subordinate
mutation family. Relation-constrained decisions keep the same resource-action key; policy relations
remain internal to Access, while API projections expose the domain choices needed by each surface.

Citation Style lookup and access control cross the Library Interface. Library delegates CSL
formatting to `inquiro`, whose CSL engine is a required dependency. The optional citation extra
supplies the built-in style catalog; custom CSL renders without that catalog. Library reports
unknown styles as input errors and preserves unexpected rendering failures as Implementation
errors.

`inquiro.bibliography` is the facade for standard Work interchange, Citation Key generation,
Citation Styles and rendering. Its `options`, `keys`, `styles`, `formats` and `engine` modules
follow the import-linter layer contract. Field and type conversion is delegated to commonmeta-py;
there is no parallel Bibliography Record or Reference Type registry. `inquiro.work` validates the
locked external schema and supplies neutral projections; `inquiro.work_models` is generated from
that schema. Candidate Records contain Work, Provider context and diagnostics. Library owns
ImportBatch JSON and business merge policy. Inquiro accepts no Quirebase or SQLAlchemy objects.
The [support matrix](item-metadata-json.md) records explicit upstream conversion restrictions.

Scholarly inline Rich Text crosses the Inquiro Interface through one restricted conversion
operation. Its restricted rendering representation is sanitized HTML containing only `i`, `b`,
`sup` and `sub`, without attributes. The private Implementation maps the equivalent supported
LaTeX commands (`emph`, `mkbibemph`, `textit`, `textbf`, `textsuperscript` and `textsubscript`) to
Inquiro-owned nodes and renders canonical HTML, LaTeX or plaintext. Library preserves the validated
Work, including its source titles and abstracts. Citation rendering sanitizes temporary display
values, including nested contributor names, before passing them to citeproc; it preserves stored
Work and interchange snapshots. Citation Key generation, Search, recommendations, archive names and
non-rich export formats explicitly request plaintext. Inline `$...$` formulae remain verbatim in
the canonical representation and bibliography round-trips. The frontend Web UI Adapter alone
projects them through Temml into allowlisted MathML. `pylatexenc` and bibliography implementation
types do not cross the Inquiro Interface.

Item metadata mutation crosses Library through `create_item`, `revise_item_metadata` and
`regenerate_citation_key`. Creation and revision validate the generated standard Work plus
Library's title, payload-size, calendar-date and Citation Key limits. Library owns permission,
Item version CAS, Search coordination, Audit, transactional enqueue and commit. The commands
return an Item UUID and version. `library.item_metadata` owns complete replacement;
`library._metadata` owns record-local Provider merge policy, preserving omitted and local facts.

`Item.work` is the sole bibliographic snapshot, including ordered credits, subjects, files and
identifiers. `library.catalog` supplies authorized Workspace/Project candidates to Search,
Contributor suggestions and facets. JSON expressions are isolated in `library._json_queries`;
facets count distinct Items and never infer shared researcher identity. Existing full-text
projections remain rebuildable. New JSON indexes or facet projections require measured need.

Commonmeta owns Work type vocabulary and field constraints. The separate Item Citation Key
retains its formula preview and 128-character business limit. Manual dates preserve standard
precision, including valid full timestamps; Provider date normalization never invents missing
month/day components. Source attributes without a standard representation receive diagnostics,
and valid records in an ImportBatch can be confirmed alongside failed records.

Work.id and top-level Work.identifiers are the only bibliographic identifier source. Multiple
values of one kind and multiple Items with shared identifiers are allowed. Library duplicate
suggestions, Provider imported indicators and import warnings compare supported identifiers
within authorized Workspace Items, excluding container, contributor and related-resource IDs.
No identifier association, projection table, claim or Workspace uniqueness invariant exists.
The internal Item UUID remains its identity. Identifier input is query context retained in
CandidateRecord.lookup_identifier; adapters never force it into returned identities. OpenAlex
lookup consumes commonmeta-py's reader directly, including its URL-form identifiers and files.

Identifier lookup Import Batches use `metadata` as their input format. Lookup and metadata sync
Audit Events record the actual metadata source in `provider` and the requested lookup route in
`lookup_provider`. Query values and search terms are not recorded, following ADR 0003. Lookup
provenance is not concatenated into the batch's format name.

Metadata limits are business rules shared by manual creation, revision and Import confirmation.
JSON Contributor snapshots have no former Author-column name length or identity-key limit.
Titles contain at most 1,000 visible text characters inside the Work JSON value. No B-tree
indexes the full rich title, and the Work payload has a separate 1 MiB limit.
Full-text Search continues to use its own FTS5/GIN projections. Title pagination and the preliminary
ordering used by duplicate detection may require an explicit database sort; a future optimization
must use a bounded plaintext ordering projection rather than indexing the complete HTML value.
Persisted Citation Keys contain at most 128 characters. Explicit keys are validated without
truncation; automatic generation budgets the author and title parts while preserving the year.
Audit target IDs use the same 255-character protocol limit as persisted workflow IDs, because an
Audit Event may identify either a UUID resource or a prefixed workflow execution. Invalid input
raises a domain validation error before commit on both SQLite and PostgreSQL.

The generated Commonmeta Work supplies metadata types to inbound adapters; Item write envelopes
add only business properties such as expected version and Citation Key. Adapters do not mirror
Work fields or maintain another bibliographic schema. HTTP response DTOs and pure projections live beside their capability routes under
`web/api`; MCP derives its schemas and execution from that OpenAPI contract instead of owning a
second response model or orchestration path.

Operations over a user-selected set of Items live in `library.bulk_items`. This Module owns the
bulk-operation transaction, all-selected existence checks, concrete action authorization, one
Audit Event and transactional cleanup enqueue. Project assignment uses `project_item.manage`, Tag
assignment uses `tag.use`, Tag creation independently uses `tag.create`, and deletion uses
`item.delete`. Neither single nor bulk Item deletion requires metadata-update authority.
Multi-Item document download crosses this Library seam; its implementation may call the
Documents assembly interface for archive construction after selection authorization. Library does
not define single-Item metadata behaviour or Item section queries.

Opening an Item crosses the Library interface through `open_item_section` with a typed
`ItemSection`. Overview, Metadata, Files, Organize, Annotations and Discussion each return a
section-specific read model; only the Web adapter maps those views to API projections. Access
validation, section query selection and recent-reading persistence remain coordinated behind the
same operation seam. The implementation lives in `library.item_sections`, which owns reads for
one opened Item and no Item mutation or bulk behaviour. Its Organize projection calls
`projects.list_item_organize_projects` for every discoverable active Project and its participation
fact, without directory pagination. Projects uses one membership-generation participation
predicate for this query, directory views and detail. Library retains Item assignments, Tags and
section composition. Effective participation requires an active User and current active membership;
governance discovery of a managed Project does not imply participation. The adapter projects each independent
Item capability from the resolved context, without metadata-edit or delete boolean mirrors.

Library's `get_item_metadata_sources` supplies on-demand metadata synchronization choices from
one authorized Work snapshot and its Item version. It uses Inquiro recognition, comparison and
configured Provider capabilities, with no upstream I/O or reading-history mutation. This action
read model belongs to `library.identifiers`; Overview carries no identifier lookup projections.

Section composition consumes Documents-owned `DocumentInfo` values through
`list_item_revisions`, `list_item_attachments` and `count_item_attachments`. These frozen summaries
expose file names, sizes, media types and processing facts without FileObject descriptors or
storage keys. Metadata sections use isolated generated Work snapshots; Web does not traverse Contributor ORM
relationships. HTTP projection functions accept
the concrete section type. Stable scalar Item, Tag and Project mappings remain shared reads.

Documents owns the complete Annotation browse query. `count_item_annotations`,
`list_item_annotation_views` and paginated `list_document_annotations` share private-author,
Project discovery, deletion and moderation rules; each count/data statement rechecks Project
discovery. The section operations consume an already authorized Workspace context and Item and
do not complete the caller's transaction. Browsing includes hidden and archived Annotations for
moderators; PDF export always excludes them. Annotation revision choices also use `DocumentInfo`.

Annotation and Annotation Reply CRUD cross the Documents interface through typed create/update
commands and shared views. Documents owns the canonical per-page geometry and style schema,
authorization coordination, optimistic versioning, annotation soft deletion, Audit Events and projection to
PDF export. Web, REST and MCP are inbound Adapters over that Interface; EmbedPDF objects are
translated only inside the Web asset and never enter Documents persistence or API wire contracts.
Annotation scope and Project binding are fixed at creation. Update commands carry authored content
and the expected version only; the existing ProjectItem is held through the mutation, and Replies
continue to inherit the same audience.

Tag selection is presented by the Item Organize section and committed through additive/remove commands
(`add_tag_to_item` and `remove_tag_from_item`). Existing Tags may be matched case-insensitively
against an Item Tag Recommendation, while candidates absent from the taxonomy are returned as
suggested names. Tag reads expose the selected Workspace's taxonomy to its active members.
The creator of a Tag has no separate visibility or management authority; Workspace
resource-action decisions govern taxonomy edits.
Taxonomy maintenance crosses the Library interface through rename, delete and
`merge_tags`; these operations mutate only Tag and association rows and never invalidate Search.

Item Tag Recommendation generation crosses the Library Interface through generation-request and
workflow operations. Library owns assembly and cleaning of title, abstract and latest ready
File Revision text, transient recommendation state and stale-workflow guards. A generation token
supersedes queued work when source data changes; engine and model provenance are not persisted for
this disposable, reproducible result.
Its Implementation calls the reusable `rubrica` Interface for recommendation computation. Model
files for KeyBERT are local administrator-provided inputs; the Adapter never accepts a remote model
identifier. Library metadata writes enqueue generation transactionally through Core's DBOS
Adapter, and the Library-owned workflow invokes the Library operation.

Opening a Project crosses the Projects interface through `open_project_workspace`, which returns
a typed read model containing the Project, active explicit participants for `open` and `managed` modes,
the caller's participation state, and assigned Items. Workspace membership and concrete
resource-action decisions are checked against the boundary-resolved WorkspaceContext behind that
operation. ProjectParticipant gates discoverability only for `managed` Projects; it never grants
Workspace authority or canonical Item access. Projects have no owner or ownership-transfer
operation; `created_by` is provenance only. Only the Web adapter
maps the typed view to an API projection.
The read model reuses the ProjectParticipantInfo value returned by participation commands; it does
not wrap mutable User objects. `active_participants` excludes suspended memberships and inactive
Users, while their stored ProjectParticipant selections remain available for reactivation.
Managed participation uses `POST /projects/{id}/participants` and
`DELETE /projects/{id}/participants/{user_id}`; these commands do not change Workspace membership.

`update_project_settings` is the single Projects interface operation for changing name, description
and participation. The Project settings form uses this operation directly.
The Web adapter sends only changed name, description and participation fields in one partial PATCH;
omitted fields retain their values from the locked Project. Choices are validated before mutation
and committed with their Audit Event in one transaction. A transition to Workspace participation
requires UI confirmation because it permanently clears explicit participant selections, including
suspended members. Metadata changes do not rewrite participation or its associations.

Projects owns exclusive root locks for aggregate mutations and shared guards for subordinate
associations. Other Project-scoped mutation callers explicitly select their root lock through Access
before locking children; `ActionSpec.mutating` does not select a Project lock implicitly. Project
mutation authority comes from Workspace resource-action policy; ProjectParticipant has no role and never
grants authority. `workspace` participation is implicit with no ProjectParticipant rows; `open` Projects
are discoverable to all active Workspace
members and permit self-join/leave; `managed` Projects are discoverable only to participants and
Workspace governors, who curate participation. Collection reads, direct loaders and root locks use
one SQL discovery predicate; mutations also recheck discoverability in a fresh statement after acquiring
the lock. Only Workspace governors may create managed
Projects. Moving to `workspace` clears explicit associations in the same transaction; switching
between `open` and `managed` preserves them. There is no last-participant or Project ownership
invariant, and Workspace-member lifecycle only removes terminated participants rather than
synchronizing implicit Project participants. Managed Project scope never changes access to
canonical Workspace Items. Item assignments use the Project root plus FK/unique-key
idempotency and do not participate in a global lock graph. Library bulk assignment crosses this
Projects interface while retaining ownership of the surrounding bulk-operation transaction and
Audit Event.

Instance administrators do not receive an implicit Projects interface. They may inspect Workspace
tenancy metadata and suspend or recover governance, but Project content remains behind Workspace
membership. Exceptional content reads use the reason-required, read-only break-glass operation and
do not change ordinary endpoint authorization.

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
or catalog. Each Provider definition declares its metadata source name and primary Identifier
Namespace separately. Both names route explicit identifier requests. Bibliography conversion consumes standard Work
values without importing the private Provider catalog or maintaining identifier/type registries.
Container identifiers remain within Work.container and never identify an Item.
One bounded transport Implementation applies timeout, response-size, rate-limit and
HTTP-error rules before dispatching through the production HTTP Adapter or test Mock Adapter.
Metadata requests reject redirects; PDF acquisition follows a bounded redirect chain, streams into
a managed temporary file, enforces the document-size limit and validates the PDF header. Lookup
maps an upstream 404 to Candidate-not-found; Search maps it to an empty page.

Inquiro owns the fixed Provider catalog, display names, credential requirements and supported
search sorts. `metadata_provider_choices(config)` returns immutable Search/Lookup choices available for its
configuration and the shared search-clause limit, without exposing credentials or adapters.
Quirebase Library maps runtime settings and returns this description; Web and browser clients do
not maintain their own Provider lists or credential rules. The catalog, automatic-detection order
and dynamic registration remain private; the description does not create a plugin extension seam.

Quirebase owns the business behaviour around Inquiro results. For lookup and Search, Library
constructs and closes the runtime within each operation, explicitly maps Candidate Records to its
write/read models, translates package failures to typed domain errors and owns Discovery auditing.
Import staging, preview and confirmation return an immutable `ImportBatchPreview`, reusing the shared
bibliographic metadata values. Library joins staged source descriptors to candidates and returns
typed source summaries and diagnostics; storage keys and source association IDs stay internal.
Only the batch's current actor receives its workflow identity. Web serializes that result directly.
Document acquisition is currently a standalone Inquiro capability; any Quirebase workflow that
adopts it must cross the Library Interface rather than importing Inquiro from Web.

Batch PDF Import crosses the Library Interface through `stage_pdf_import_batch`,
`retry_pdf_import_batch` and `commit_import_batch`. Staging validates and uploads at most 50 PDFs, creates a pending Import
Batch and transactionally enqueues its preparation workflow. Separate durable steps materialize PDFs
and extract DOI values, check one DOI against accessible Items in a short transaction, and retrieve
Candidate Records without holding a database transaction; Provider retries therefore do not repeat
PDF parsing. One final transaction
de-duplicates results and makes the batch ready. A terminal preparation error transactionally
marks the owning workflow's batch failed without deleting its staged PDFs. Cancellation, exhausted
workflow recovery and missing workflow records converge a pending batch to failed when it is viewed
or retried; retry returns it to
pending with a new workflow identity. Diagnostics for individual PDFs do not block
confirmation of the remaining candidates. Confirmation creates each Item and
attaches its staged PDF as a File Revision in one transaction. Confirmation revalidates Candidate
Record DOIs against currently accessible Items before writing, and cleanup preserves staged files
still referenced by another pending Import Batch.

The Core Infrastructure Module owns one thin `ObjectStore` facade over obstore's Local and S3
data planes. Business Modules persist native AA FileObject descriptors and operate on object keys, metadata,
short-lived download targets and asynchronous byte streams; obstore types and backend configuration
do not cross that seam. Web keeps authorization before download signing; Core owns the native AA
signing operation and its bounded expiry. Import Batches own their staged descriptor list while
durable preparation receives serializable source receipts. Components that require a local
`Path`, including PyMuPDF, use the facade's scoped materialization operation. HTTP adapters pass
the returned obstore-backed byte stream directly to `StreamingResponse`; streaming ZIP assembly
uses one unbuffered async-generator bridge and selects `ZIP_AUTO` from each member's known size.

All ordinary physical Document deletion crosses the Documents interface.
`documents.objects` owns the canonical descriptor references, final reservation check, expiration
retirement and idempotent physical deletion. Library provides `import_staging_object_keys` for
retained PDF staging, including pending, ready and failed batches; committed batches are excluded.
Operations owns inventory, age cutoffs, scheduling and reporting, and calls Documents for both
scan protections and final cleanup. The generic Core object-reservation encoder/parser distinguishes
reservation from cleanup intent and supports own-workflow exclusion without knowing business tables.
Documents reads reservations, staging sources and committed Document destinations in that order,
then rechecks every key immediately before its physical delete. This preserves protection when a
workflow finishes or Import confirmation atomically transfers staged ownership during the check.
Every logical upload owns one
preallocated UUID object, so rollback and terminal workflow cleanup can delete that key without a
local lock. Pending Import Batches and active workflow attributes are durable object reservations.
The workflow-first upload interface creates a DBOS execution, streams
the object, and sends a durable completion message; a short datasource transaction stores a pending Revision from the completed upload receipt.
Ordinary and imported PDFs then share a retryable inspection step: object I/O, full text and page
geometry stay outside durable outputs and open database transactions. The final short transaction
checks the Revision and current attempt, publishes ready/Search state and enqueues
`FileRevisionChanged` atomically. Ready retries return IDs; missing Revisions are never recreated.
Failed or interrupted processing retains the source for a `file.manage` retry with a new attempt. Documents owns the durable
`FileRevisionChanged` event contract, and the Library workflow that handles it updates derived
Library state without creating a reverse dependency. Operations
reconciliation lists the Object Store once and only deletes old managed UUID objects after
using Documents-owned protections at discovery and immediately before deletion. Item deletion and
Import Batch
discard transactionally enqueue idempotent Documents cleanup workflows on a non-partitioned cleanup
queue. Revision work is partitioned by File Revision and bounded independently from synchronous
Item/Revision Search projection updates and Recommendation inference. Core queries active workflow reservations
directly instead of scanning terminal history. Storage metrics aggregate recorded sizes from business
tables without issuing Object Store HEAD requests; an Operations-owned scheduled integrity workflow
performs scan, deletion, rechecks and thumbnail size backfills inside one ordinary retryable
step. Only small counters enter its checkpoint. A singleton latest scan stores exact error totals
and at most 100 samples; start and completion timestamps distinguish failed or interrupted checks. Successful annotation exports persist lightweight Annotation Export Artifact
records; scheduled maintenance retires still-expired matching descriptors in bounded
expiration-ordered datasource transactions. Their returned keys are checkpointed with retirement
before a retryable Documents deletion step, which still protects other references and reservations.
DBOS history scanning is unnecessary. Workspace Search rebuilds use `workspace_maintenance.run`
and reauthorize every bounded
Item/Revision batch; Workspace renaming remains an independent `workspace.update` decision.
Global Search rebuilds and bulk Tag Recommendation requests use bounded keyset Item batches
rather than one large datasource output. Unknown keys and doctor probes are never managed.

Workspace teardown holds the exclusive Workspace root through authorization, archive checks, snapshots,
root deletion, Audit, durable enqueue and commit. Search's `remove_workspace` removes both derived
projections before the cascade, including SQLite FTS rows. Documents supplies its descriptor
snapshot; database foreign keys cascade to Annotations and Replies. Library
supplies retained Import Staging keys. These owner operations use the caller's Session without
committing or rolling it back. Workspaces enqueues bounded cleanup batches in the deletion
transaction; cleanup intent does not reserve those keys.

### Retained metadata and workflow history

Hourly Operations maintenance runs owner-provided, bounded purge operations in short independent
transactions. Expired sessions and throttle windows retire next cycle; terminal Invitations,
Workspace Invitations, invalid API Tokens and terminated membership generations retire after 30
days; Audit Events after 90 days; ordinary deleted Annotations/Replies after their 24-hour Undo
window. Restore authorization and final updates recheck that window. Moderator deletion physically
removes the root and Replies immediately. Import Batches retire seven days after their last state
change; reads do not renew them, and active or unconfirmed durable preparations remain protected.
Library owns the expiration predicate and batch deletion, including transactional staging cleanup;
Operations advances a bounded keyset cursor so protected old preparations cannot starve later records.
These positive deployment settings are not runtime application policy. ItemRead history is retained in full.
The fixed-primary-key `MaintenanceSnapshot` stores only the latest integrity and cleanup results,
with separate start timestamps protecting each against stale concurrent writes.

Core's `workflow_storage` is the only SDK-table retention adapter. Completed terminal DBOS history
retires after seven days, parent before child; native parent and operation-output child references
protect children while any parent exists. Workflow status, its cascading system checkpoints and
datasource outputs retire in one transaction. Every cycle separately sweeps orphan datasource
outputs, even with no expired workflows, so an independently committed late SDK error converges on
a later run. Retired IDs cannot be resumed or reused; cancellation alone is not proof of quiescence.
Ordinary enqueue and datasource execution continue through the SDK unchanged. Domain content and
Artifact download authority never depend on terminal workflow outputs or retained Audit evidence.

### Object lifecycle interface contracts

`delete_item_documents` runs under the caller's authorized, exclusive Item root locks in stable
order. It locks existing ProjectItem rows before their Annotations, matching Reply writes and
preventing a lock inversion during the Item cascade. It collects File Revision, PDF Thumbnail
and Attachment keys, fences Reply insertion with Annotation locks, and deletes Document children
with their Annotations and Replies through cascading foreign keys. It returns
keys without object-store I/O or transaction completion. Single and bulk Library deletion retain
Item deletion, Search removal, Audit, transactional cleanup enqueue and commit. Independently
expiring Annotation Export Artifacts retain their own lifecycle.

`prepare_item_document_copy` snapshots source Documents in the caller's read transaction and
returns an `ItemDocumentCopy` whose descriptors and cleanup receipts remain private to Documents.
Library ends that transaction before `copy_objects`, then reauthorizes both Workspaces and locks
the source Item before `install`. Installation locks and revalidates all source descriptors,
creates independent File Revisions and Attachments and updates revision Search in the caller's
transaction. Library owns Item metadata and Contributor snapshots, Item Search, Audit and commit.
On failure Library rolls back before `discard`, which rechecks durable references so an ambiguous
commit cannot cause deletion of objects already referenced by committed target Documents.

Documents exposes `protected_object_keys` for scan protections and `delete_unreferenced_objects`
for final cleanup. They require a Session with no pending writes and end their read transactions
with rollback so each final check reads fresh protection facts. Protection includes File Revisions,
PDF Thumbnails, Attachments, Annotation Export Artifacts, Library staging and active workflow
reservations. Full scans enumerate facts without inventory-sized SQL parameter lists. Cleanup can
exclude its current workflow without excluding other owners; absent objects are success. The UUID
protocol requires reservation before upload and forbids new work from adopting old unreferenced
keys; the checks do not make database writes atomic with arbitrary Object Store I/O.

`list_expired_export_artifacts` returns bounded expiration-ordered receipts.
`retire_expired_export_artifacts` rechecks identity, object key and expiration, then returns keys
for the caller's datasource transaction to checkpoint with descriptor retirement. Neither operation
completes the caller's transaction. Renewed or replaced descriptors remain protected.

`snapshot_workspace_documents` returns Document object keys under
the caller's exclusive Workspace root lock. Library's `import_staging_object_keys` and Search's
`remove_workspace` use the same caller transaction without commit or rollback.

An internal helper imported across Modules is an architectural pressure point. Repeated use is
a signal to move the concept to its owner or deepen the owning interface; it is not a reason to
create a generic shared-utilities package.

A zero direct-call count is not sufficient evidence that a business capability is obsolete.
Remove an operation only after its behavior is covered by a deeper interface or an explicit
product decision retires it; test-only use cases require the same review.

## Allowed dependency directions

Every new top-level dependency must be added to the import contracts and justified here. Existing
directions are:

| Source | May depend on | Ownership reason |
| --- | --- | --- |
| `access` | `core`, `models` | Evaluate policies using persisted identities and domain errors |
| `accounts` | `access`, `audit`, `core`, `models`, `operations`, `workspaces` | Authentication persistence, account-level authorization, Audit Event recording, runtime registration policy, Workspace provisioning and the Workspace-owned account-deactivation guard |
| `audit` | `access`, `core`, `models` | Administrative authorization, authorization errors and Audit Event persistence |
| `library` | `access`, `audit`, `core`, `documents`, `models`, `operations`, `projects`, `search` | Authorization, persistence and auditing; selected-Item document assembly; Project-gated bulk assignment; runtime Provider/import settings; Library-owned workflows and search-index synchronization |
| `projects` | `access`, `audit`, `core`, `documents`, `models` | Authorization, Project persistence and audit recording; Documents-owned Annotation cleanup when detaching a ProjectItem |
| `documents` | `access`, `audit`, `core`, `library`, `models`, `operations`, `search` | Authorization, owned-object persistence, auditing, Library-owned staging reference facts, Operations runtime settings, Documents workflows and revision-owned Search projection |
| `operations` | `access`, `accounts`, `audit`, `core`, `documents`, `library`, `models`, `search`, `workspaces` | Infrastructure access, operational persistence, owner-provided retention operations, Documents-owned protection/deletion and export retirement, Workspace-authorized maintenance workflows, global integrity coordination and audit recording |
| `search` | `models` | Build and query the derived search representation |
| `workspaces` | `access`, `audit`, `core`, `documents`, `library`, `models`, `operations`, `search` | Workspace authorization, membership/invitation persistence, Audit, runtime creation policy, Documents-owned teardown/cleanup, Library staging facts and Search-owned projection removal |
| `web` | Business Modules, `access`, `accounts`, `audit`, `core`, `documents`, `library`, `mcp`, `models`, `operations`, `projects`, `search` | Invoke use cases, own capability-local HTTP DTOs and projections, expose `/api/v1` through explicit Bearer or Login Session authentication, enforce cookie-request Origins, format responses, serve the static application and compose the MCP HTTP mount |
| `mcp` | `accounts`, `audit`, `core` | Verify API Tokens at the MCP transport, select a fixed OpenAPI operation allowlist, bind trusted MCP provenance and invoke the same `/api/v1` handlers through an in-process ASGI client |
| `core` | Nothing above infrastructure | Infrastructure must not know business concepts |

The reverse Documents → Library edge imports only `import_staging_object_keys` through the Library
facade, at execution time to avoid facade initialization cycles. Workspaces consumes the same fact.
Architecture tests restrict those callers to this symbol. Operations → Documents imports only the
owned object protection, deletion, expiration listing, export retirement and expired Annotation/Reply
purge operations. Operations → Library consumes its owned Import Batch expiration operation.
Operations → Accounts/Workspaces likewise consumes only their narrow retention
facades; the owner supplies predicates and Operations supplies cutoffs, batching and commits. Documents →
Operations remains runtime settings only; the `operations-implementation` Import Linter contract
protects all other Operations implementation modules from business callers. These bounded surfaces
do not permit cleanup scheduling or business rules to migrate between owners.

Dependencies on standalone workspace packages are also explicit:

| Source | May depend on | Ownership reason |
| --- | --- | --- |
| `documents` | `inquiro` | Render canonical scholarly Rich Text as plaintext for archive filenames and manifests |
| `library` | `inquiro`, `rubrica` | Adapt reusable metadata, bibliography, citation and recommendation computation to Library business operations and typed domain errors |
| `search` | `inquiro` | Project canonical scholarly Rich Text into the plaintext derived search representation |

The `documents` and `search` edges are restricted to `inquiro.richtext`; they do not permit those
Modules to call Provider, bibliography or citation operations. Those business workflows still
cross Library. The Python Web Adapter does not depend on Inquiro; browser-only Rich Text projection
belongs to the frontend Adapter.

Standalone workspace packages never depend back on Quirebase. Audit Event construction and
administrative queries cross only the `quirebase.audit` Interface.

Business Modules never import FastAPI, MCP transports or vendor AI SDKs. Inbound adapters do
not own transactions, ORM persistence, audit recording, object storage or search-index writes.
True external systems receive a port and production/test adapters; local concrete dependencies
remain concrete until a second adapter is justified.

Run `uv run lint-imports` or `make lint-architecture` to check imports across Quirebase, Inquiro
and Rubrica. The same check runs through prek locally and in CI, and `make lint-all` includes it.
Protected contracts list each Module's allowed direct callers; they preserve the documented
direct dependency policy even where business Modules have legal indirect dependencies or cycles.
Type-checking imports are included. Bibliography and Provider internals use exhaustive layer
contracts, while Search adapters use an independence contract. New top-level Modules need a role
and a protected contract; new Bibliography or Provider implementation modules need a layer.

Import Linter is a development dependency. It checks module imports, including relative imports
and imports from parent packages. It does not check symbol-level rules, dynamic imports,
transaction completion, authorization or Audit Event construction; the architecture and behavior
tests retain those responsibilities. Package-owned tests may exercise private implementation seams;
root integration tests continue to respect the Bibliography facade.

## Change completion criterion

An architecture change is complete when every affected concept has one owner, every new
cross-package dependency is documented and enforced, tests exercise an agreed seam, and the
architecture suite fails if the old violation is reintroduced.
