# DDD and deep-module improvement roadmap

This roadmap deepens the single-context modular monolith established in
`docs/architecture/modules.md`. It prioritizes domain ownership, interface leverage and
maintainer locality. File length alone is not a reason to split a Module.

Tracking issue: [#4 Roadmap: deepen domain modules and interfaces](https://github.com/Jadeiin/quirebase/issues/4)

## Evidence baseline

- `library` exposes 39 package symbols and `discovery` exposes 40.
- `ItemMetadataUpdate` contains more than twenty scalar strings plus JSON-encoded identifiers,
  JSON-encoded custom fields and dictionary-shaped contributors.
- `get_item_workspace_data` returns `dict[str, Any]` whose shape changes across six string
  section values; its Web caller must know keys, placeholder defaults and loaded relationships.
- Audit operations live under `library`, although Accounts, Documents, Projects, Discovery,
  Operations and Pipeline record Audit Events.
- Discovery search and lookup already present small external interfaces backed by multiple real
  Provider adapters. Their opportunity is internal locality, not a wider public interface.
- `models.py` and broad package facades still reflect the current implementation graph, so
  decomposing them before deeper use-case seams would freeze accidental coupling.

## Candidate assessment

| Priority | Candidate | Current interface problem | Target seam | Dependency and test strategy |
| --- | --- | --- | --- | --- |
| 1 | Audit Event ownership | Correct behavior behind the wrong owner creates false Library dependencies | A small `quirebase.audit` business interface for recording and administrative queries | SQLAlchemy is local-substitutable; test through the business interface with the real SQLite database |
| 2 | Item metadata mutation | Callers understand JSON parsing, contributor synchronization, identifier precedence, version checks, indexing, auditing and commit order | Typed create/revise commands returning a small mutation result | Real SQLite plus SQLite/PostgreSQL Search adapters; no repository port |
| 3 | Item Workspace | A section-dependent untyped dictionary leaks query and ORM-loading knowledge | Typed section selector and typed read models; opening owns recent-read recording | Business-operation tests per section plus one HTTP tracer bullet |
| 4 | Discovery Providers | Public interface is deep, but one Provider change is spread across registries, aliases, credentials and large central files | Internal Provider registration and per-Provider locality behind unchanged search/lookup interfaces | True external boundary; shared adapter contracts use `httpx.MockTransport` |
| 5 | ORM mappings and facades | Shared mapping and large export surfaces may encode obsolete coupling | Select a mapping layout only after ownership stabilizes; export use cases/results/errors | Prototype alternatives, migration/import tests and unchanged behavior suites |

## Sequence

### 1. Establish Audit as a domain owner

Issue: [#5 Move Audit Event ownership out of Library](https://github.com/Jadeiin/quirebase/issues/5)

This is the first slice because it removes false dependency edges without changing business
behavior. The deletion test justifies the Module: deleting the audit helper would reproduce
event construction and detail serialization across many callers. The implementation remains
concrete because only one persistence adapter exists.

Done means all capabilities record through the Audit interface, Library no longer re-exports
Audit operations, and architecture tests show that Accounts, Documents, Projects, Operations
and Pipeline do not depend on Library solely for auditing.

### 2. Deepen Item mutation

Issue: [#6 Deepen the Item metadata mutation interface](https://github.com/Jadeiin/quirebase/issues/6)

Design the interface twice before implementation:

- complete typed metadata replacement grouped into domain values;
- focused commands for bibliographic metadata, contributors, identifiers and generated keys.

Compare them on caller knowledge, atomic invariants, number of methods and ability to express the
current HTML workflow without snapshots. Resolve Creator versus Item Owner terminology before
selecting authorization names.

Done means public commands contain no JSON-encoded values or `dict[str, Any]` contributors, and
permission, concurrency, persistence, Search synchronization and Audit recording remain atomic
behind the selected operation seam.

### 3. Introduce typed Item Workspace read models

Issue: [#7 Replace Item Workspace dictionaries with typed read models](https://github.com/Jadeiin/quirebase/issues/7)

Treat each workspace section as a caller-visible result type while retaining one cohesive query
Module. Move recent-read recording behind the open-workspace operation so callers cannot forget
the side effect or record reads for inaccessible Items.

Done means templates receive typed views or a Web-owned mapping and no business operation returns
the section-dependent dictionary.

### 4. Improve Provider locality without shallowing Discovery — completed

Issue: [#8 Localize Discovery Provider implementations behind contracts](https://github.com/Jadeiin/quirebase/issues/8)

ADR 0005 supersedes the original function-based sketch. Inquiro now exposes one deep
`ProviderRuntime` with `lookup` and `search`; the runtime owns the fixed catalog, shared identifier
knowledge, dispatch, credentials and bounded transport. Quirebase Discovery crosses the Library
Interface, so Web has no package-specific dependency or error knowledge.

Done means adding a Provider changes one leaf Implementation, the private catalog and contract
examples; peer Provider imports and duplicated transport policy are rejected by architecture
tests. This criterion is now satisfied.

### 5. Reassess persistence mapping and package facades

Issue: [#9 Reassess ORM mapping ownership and package facades](https://github.com/Jadeiin/quirebase/issues/9)

This step is blocked by #5, #6, #7 and #8. Prototype both capability-local mappings with a metadata
aggregator and a centralized persistence package with enforced ownership imports. Select or
reject decomposition based on cycles, migration ergonomics, relationship locality and caller
knowledge.

Prune package exports only after callers use the deeper interfaces. Internal Python paths are not
a compatibility commitment, so do not add long-lived re-export shims.

Selected direction: the prototype preserved on `prototype/issue-9-orm-layouts` showed that
capability-local mappings require a metadata aggregator while cross-capability ORM relationships
remain coupled. Keep the centralized persistence mapping, enforce a complete conceptual-owner
map, load it directly from Alembic, and keep concrete adapters and internal collaborators out of
package facades. The detailed comparison is in `docs/architecture/orm-ownership.md`.

## TDD execution rules

- Agree and name the seam in each issue before the first test.
- Work vertically: one failing behavior example, minimal implementation, then the next example.
- Use real local persistence and Search adapters; mock only true external Provider HTTP traffic.
- Once a deeper interface has equivalent behavior coverage, delete tests that reach through it to
  internal collaborators or ORM layout.
- Preserve a small number of HTTP and end-to-end tracer bullets for adapter integration.

## Explicit non-goals

- Do not create generic Service, Repository or Utilities layers.
- Do not add a storage port while `LocalObjectStore` is the only justified adapter.
- Do not split Discovery modules merely because they are long.
- Do not split `models.py` before the preceding ownership work.
- Do not include ADR 0004 or AI/MCP implementation in this roadmap.

## Roadmap completion criterion

The work is complete when issues #5 through #9 are resolved, the dependency policy reflects
domain ownership, business callers no longer handle transport-shaped Item metadata or untyped
workspace dictionaries, Provider additions are local and contract-tested, and persistence
organization follows the proven Module seams.
