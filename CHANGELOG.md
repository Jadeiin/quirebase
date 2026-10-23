## 0.3.0 (2026-10-23)

### BREAKING CHANGE

- Workspace invitation and Citation Style catalogs use
paginated responses; the separate Citation Style options endpoint is
removed. Facet limit and offset now select the Item page.
- Admin Workspace lists return paginated responses, and maintenance reads return storage metrics directly.
- rebuild the initial schema and update import confirmation
and annotation moderation responses. Previous databases and durable
checkpoints are not supported.

### Feat

- **pdf**: make reader sidebars resizable
- **library**: add organization filters and simplify UI copy
- **discovery**: add recoverable search and batch import previews
- **app**: unify paginated catalogs and current-page library facets
- **admin**: unify management tables and governance controls
- **lifecycle**: add bounded retention and import recovery
- **app**: add global quick navigation
- **library**: add refinements and saved views
- **library**: add SQL duplicate scans and streaming file checksums
- **library**: unify item actions and simplify mutation contracts
- **library**: complete preview and organization workflows
- **library**: improve range selection and bulk action feedback
- **library**: add scoped keyboard navigation and selection
- **library**: add table view, previews and metadata sorting
- **workspaces**: add received invitations and self-service leave
- **workspaces**: add administrator ownership governance
- **accounts**: complete invitation lifecycle and admin views

### Fix

- **ci**: account for shared item header styles in bundle budget
- **ui**: use full content width for item headers
- **storage**: register file backends before runtime startup
- simplify streaming uploads and stabilize author tests
- preserve whole author names and repair CI failures
- **ui**: improve author overflow and dashboard date alignment
- **i18n**: format shortcut keys outside translation catalogs
- **projects**: show unavailable state for purged item lists
- **library**: preserve unavailable state for purged Project caches
- **frontend**: improve workspace navigation and editing recovery
- preserve project drafts and normalize dependency lock hooks
- **frontend**: preserve drafts and complete recovery flows
- **admin**: preserve invitation links and reassignment drafts

### Refactor

- rename rubrica package to excerpo
- **storage**: restore the original streaming upload path

## 0.2.0 (2026-10-16)

### BREAKING CHANGE

- Admin overview recent_events and workflow lists now return
limit/offset pages; failed_workflows is replaced by failed_workflow_count.
- Item overview and organize responses use the current detail and Tag matrix shapes, removing redundant identifier, revision, and Tag projections.
- ProviderChoice.identifier_namespace is replaced by
identifier_namespaces in provider capability responses.
- replace POST /imports/identifier with POST /imports/identifiers,
using an identifiers array for both single-record and batch imports.
- replace the previous Item metadata and identifier schema; rebuild existing alpha databases.
- remove the annotation review endpoint and return a paginated
envelope from the Item annotation collection.

### Feat

- **web**: unify pagination and enforce UI styling
- **items**: unify metadata views and library navigation
- **metadata**: streamline editor and stabilize author updates
- **imports**: support batch lookup and tabbed import sources
- **annotations**: follow displayed sources in exports and writes
- **frontend**: edit structured contributors and upstream identifiers
- **tags**: paginate tag listings and bound lookup queries
- **persistence**: extend native AA directories and file workflows
- **persistence**: integrate Alchemy repositories and services
- **persistence**: adopt Alchemy values and bounded directories
- **prototype**: integrate UUIDv7 audit bases and Alchemy use cases
- **annotations**: support multiple sources and unify Item listings
- **workspaces**: align ACL with workspace governance model
- **authz**: replace built-in ACL with Casbin
- **workspace**: add explicit discussion moderation
- **workspaces**: migrate app to workspace-scoped access
- **domain**: implement workspace ACL boundaries
- **domain**: model workspaces as data-governance and ACL boundaries

### Fix

- **projects**: confirm destructive ProjectItem removal
- **frontend**: refresh stale projections after Project and Item changes
- **items**: align controls and preserve OpenAlex author bylines
- **frontend**: refresh cached projections after cross-area changes
- **annotations**: keep scope and project binding immutable
- **concurrency**: handle bulk tag races and share upload locks
- **web**: preserve Project reads and validate archive revisions
- **acl**: enforce participant lineage and atomic mutations
- **acl**: clarify participation and governance semantics
- **persistence**: close UUID and durable replay gaps
- **persistence**: complete native UUID and release validation
- **storage**: bound signed downloads after signing completes
- **acl**: scope conflict recovery and preserve audit provenance
- prevent workspace deletion races and duplicate PDF loads
- **ci**: decouple PostgreSQL tests from frontend build
- **annotations**: filter PDF exports and lock reply roots before children
- **workspaces**: tolerate concurrent deletion during owner lookup
- **workspaces**: preserve PDF import retries and reader permissions
- **workspaces**: scope export styles and honor PDF annotation permissions
- **workspaces**: tighten authorization and project concurrency
- correct workspace ACL projection and invitation audit
- serialize annotation scope with project detachment
- enforce annotation moderation and lifecycle capabilities
- prevent workspace authorization and recovery races
- resolve workspace ACL review findings
- **workspace**: harden ACL concurrency boundaries
- **workspace**: align ownership transfer lock order
- align account invitation links with the invite route
- restore archived Project discovery and discussion reads
- **frontend**: gate workspace actions by effective capabilities
- **access**: enforce project participation and private annotation replies

### Refactor

- **library**: simplify Item copy and metadata write seams
- **metadata**: adopt Commonmeta Work for Item metadata
- **inquiro**: centralize metadata provider capabilities
- **library**: return typed import previews
- **library**: persist structured metadata and scoped JSON facets
- **workspaces**: delete owned roots and simplify lifecycle APIs
- **inquiro**: centralize structured bibliographic metadata
- **frontend**: adopt Skeleton controls and improve metadata editing
- **metadata**: standardize item types and provider records
- simplify annotations and unify reader controls
- consolidate module ownership and migration tooling
- **modularity**: centralize invariant and lifecycle ownership
- **persistence**: use module-owned SQLAlchemy operations
- **persistence**: restore native conflict writes
- **persistence**: centralize concurrent writes in repositories
- **projects**: unify participant terminology
- **persistence**: enforce Advanced Alchemy boundaries
- **library**: persist item aggregates with Alchemy services
- **access**: clarify project discovery and participant contracts
- **access**: simplify grants and validate Workspace integrity
- **workspaces**: clarify participation and state commands
- **projects**: simplify choices and settings contracts
- **access**: align capabilities and collaboration choices
- **access**: separate base grants from concrete variants
- **access**: reuse read contexts and tighten policy projections
- simplify audited layers and strengthen lifecycle tests

## 0.1.4 (2026-09-21)

### Feat

- **frontend**: replace web UI with Svelte application (#14)
- **projects**: add lifecycle and discovery controls
- **logging**: unify runtime log output
- **pdf**: improve annotation sync and canonical exports

### Fix

- **pdf**: strip NUL bytes from extracted PDF text
- harden validation and workflow projections
- **projects**: serialize project mutations
- **workflows**: harden durable queues and recovery
- update CI workflow with bun setup and MinIO configuration
- update MinIO client configuration for improved storage setup

### Refactor

- **concurrency**: narrow business concurrency boundaries
- **workflows**: harden durable import state
- **workflows**: make imports and maintenance durable
- **workflows**: adopt AsyncSQLAlchemyDatasource for durable DB steps

## 0.1.3 (2026-09-02)

### Feat

- enhance maintenance workflows with progress tracking
- show workflow progress for tag recommendations
- migrate background jobs to DBOS workflows
- **storage**: add obstore-backed object storage
- migrate runtime I/O to async
- manage document thumbnails and attachment roles
- add token-authenticated MCP and HTTP APIs
- **inquiro**: deepen bibliography interchange
- add managed PDF acquisition to inquiro
- add inquiro CLI and package-owned tests
- add offline tag recommendations and batch PDF imports

### Fix

- harden DBOS workflow and migration seams
- preserves thumbnail ownership after commit, moves nondeterministic work into retryable DBOS steps, and uses database-side workflow aggregation
- ensure FileLock is thread-safe in LocalObjectStore
- serialize graphical-abstract replacement
- remove local research refs
- migrate unsafe authenticated requests from URL query
- protect in-flight staged objects from concurrent deletion
- adjust static path to artifacts config

### Refactor

- extract reusable provider and recommendation packages
- migrate transport to httpx2

## 0.1.2 (2026-08-21)

### Feat

- harden bibliography, citation and annotation export with timezone-aware asset pipeline
- improve password feedback and export cleanup
- wire three-tier document export with shared annotation visibility
- overhaul item export and annotation workflows

## 0.1.1 (2026-08-17)

### Feat

- **metadata**: improve structured item metadata
- **tools**: tabbed tools workspace, tag quick filter link, client pagination, and format compliance
- **discovery**: normalize canonical reference types, isolate upstream adapters, and enhance metadata sync
- **library**: add rich bibliographic metadata, structured authors, UIDs sync, and tag matrix picker
- **admin**: expand admin workspace into multi-tab operations console
- add citations, EndNote, and search sources
- add multi-source online search
- complete library management workflows
- split item workspace into focused pages
- enhance research workspace interactions
- add simplified Chinese frontend translations
- redesign research workspace

### Fix

- harden upstream metadata synchronization
- preserve metadata migration and authorization invariants
- **library**: support tag uuid and name filtering in library and tools tag links
- **ui**: align tag picker matrix with responsive css grid, vertical badge centering, and group filtering
- **migration**: pass created_at timestamp in item_identifiers backfill
- **make**: anchor VENV to CURDIR and harden i18n targets
- **pipeline**: make kind_prefix keyword-only in list_jobs_admin to preserve positional limit
- **discovery,admin**: clean lookup error handling and query system jobs by kind prefix
- **admin**: address operational review findings in maintenance, settings, and file reference preservation
- resolve cross-platform resource locking and template decoding issues on Windows
- import httpx for type hints and enforce bibcode validation
- address review comments on citation styles, lookup providers, and EndNote format
- return an empty annotation delete response
- isolate PDF viewer layout styles
- stabilize CI asset checks

### Refactor

- clarify item module responsibilities
- enforce persistence ownership
- localize discovery providers
- type item workspace views
- deepen item metadata mutations
- establish audit module ownership
- enforce module and domain state boundaries
- **library,web**: enforce pure CQS in get_item_workspace_data and clean get_tag_matrix signature
- **library,web**: enforce domain standards, remove read-side effects, and atomize item updates
- **i18n,web**: finalize babel migration with reviewed fixes
- **domain**: harmonize ubiquitous language and terminology with CONTEXT.md
- **i18n,adr**: update babel extraction mapping and align ADR 0004 terminology
- **assets,i18n**: untrack static/vendor, migrate i18n to babel, and record LLM architecture ADR
- align citation and search modules with domain boundaries and specs
- modular monolith architecture with explicit transaction and security boundaries
- remove legacy compatibility
