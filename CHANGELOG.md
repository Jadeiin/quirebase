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
