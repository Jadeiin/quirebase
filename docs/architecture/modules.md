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
| `library` | Business Module | Items, Authors, Identifiers, Tags and Discussion Messages |
| `projects` | Business Module | Projects, Project membership and Item assignment |
| `documents` | Business Module | File Revisions, Attachments, Annotations and annotation exports |
| `discovery` | Business Module | Providers, Candidate Records, Import Batches, bibliography interchange and Citation Styles |
| `pipeline` | Business Module | Jobs, leases, retries and PDF inspection handlers |
| `operations` | Business Module | Runtime settings, health, backup and maintenance operations |
| `recommendations` | Business Module | Item Tag Recommendation generation, engine selection, input fingerprints and result persistence |
| `search` | Outbound adapter Module | The Library Search port plus SQLite and PostgreSQL adapters |
| `web` | Inbound adapter Module | HTTP parsing, authentication dependencies and response formatting |
| `core` | Infrastructure Module | Configuration, database setup, storage, cryptography, i18n and base errors |

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

Concrete Search adapters and the Search port remain internal to the outbound adapter Module;
callers select the configured implementation through `search_index`. Mutable Job registries,
low-level document staging, ORM synchronization helpers and operational file utilities likewise
stay in their owning implementation modules rather than package facades.

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

Item Tag Recommendation generation crosses the Recommendations interface through one batch-shaped
`recommend` seam implemented by YAKE and KeyBERT adapters. The Module owns assembly and cleaning of
title, abstract and latest ready File Revision text, generation fingerprints and stale-Job guards.
Model files for KeyBERT are local administrator-provided inputs; the adapter never accepts a remote
model identifier. Library metadata writes enqueue generation without committing independently, and
Pipeline executes the registered durable Job handler.

Opening a Project crosses the Projects interface through `open_project_workspace`, which returns
a typed read model containing the Project, the caller's membership, members and assigned Items.
Membership authorization and the related queries remain coordinated behind that operation; only
the Web adapter maps the typed view to template context.

Discovery keeps `search_metadata` and `lookup_metadata` as its Provider-facing business
interfaces. A private Provider registration co-locates identity, identifier aliases and parsing,
supported Search/Lookup capabilities, fixed endpoints and credential requirements. Callers do
not select concrete adapters or inspect the registration; Provider HTTP implementations and
MockTransport contract examples remain behind the two operations. Search-only Providers such as
PMC and lookup-only Providers such as DataCite are represented as capabilities in that one
registration rather than repeated allowlists.

Batch PDF Import crosses the Discovery interface through `stage_pdf_import_batch` and
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
references. Library and Discovery never duplicate object reference rules before deleting
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
| `library` | `access`, `audit`, `core`, `models`, `discovery`, `documents`, `pipeline`, `recommendations`, `search` | Authorization, persistence and auditing; upstream metadata/identifier integration; PDF inspection and Tag Recommendation requests; selected-Item document assembly; search-index synchronization |
| `projects` | `access`, `audit`, `core`, `models`, `search` | Authorization, Project persistence, audit recording and Item index synchronization |
| `documents` | `access`, `audit`, `core`, `models`, `operations`, `pipeline` | Authorization, file persistence, auditing, runtime settings and durable export/inspection jobs |
| `discovery` | `access`, `audit`, `core`, `models`, `documents`, `library`, `operations`, `pipeline`, `search` | Candidate authorization, import/file operations, Item creation and audit, provider settings, inspection and indexing |
| `pipeline` | `audit`, `core`, `models`, `operations`, `recommendations`, `search` | Durable execution, audit recording, maintenance and Recommendation handlers, and index updates |
| `recommendations` | `access`, `core`, `models` | Authorization for forced generation, configuration, local extraction and persisted Item/Job inputs |
| `operations` | `audit`, `core`, `models` | Infrastructure access, operational persistence and audit recording |
| `search` | `models` | Build and query the derived search representation |
| `web` | Business Modules, `access`, `core`, `models` | Invoke use cases and format their returned ORM-backed views during the current persistence phase |
| `core` | Nothing above infrastructure | Infrastructure must not know business concepts |

The broad `library` ↔ `discovery` relationship remains a known deepening candidate. New code
must not expand it without first selecting an owner and a narrower interface. Audit Event
construction and administrative queries cross only the `quirebase.audit` interface.

Business Modules never import FastAPI, MCP transports or vendor AI SDKs. Inbound adapters do
not own transactions, ORM persistence, audit recording, object storage or search-index writes.
True external systems receive a port and production/test adapters; local concrete dependencies
remain concrete until a second adapter is justified.

## Change completion criterion

An architecture change is complete when every affected concept has one owner, every new
cross-package dependency is documented and enforced, tests exercise an agreed seam, and the
architecture suite fails if the old violation is reintroduced.
