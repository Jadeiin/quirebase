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
| `library` | Business Module | Items, Authors, Identifiers, Tags, Discussion Messages and Audit Events |
| `projects` | Business Module | Projects, Project membership and Item assignment |
| `documents` | Business Module | File Revisions, Attachments, Annotations and annotation exports |
| `discovery` | Business Module | Providers, Candidate Records, Import Batches, bibliography interchange and Citation Styles |
| `pipeline` | Business Module | Jobs, leases, retries and PDF inspection handlers |
| `operations` | Business Module | Runtime settings, health, backup and maintenance operations |
| `search` | Outbound adapter Module | The Library Search port plus SQLite and PostgreSQL adapters |
| `web` | Inbound adapter Module | HTTP parsing, authentication dependencies and response formatting |
| `core` | Infrastructure Module | Configuration, database setup, storage, cryptography, i18n and base errors |

`cli.py` is an inbound adapter. `models.py` is currently a shared persistence mapping, not
a business Module and not the owner of the concepts it maps. It remains unified until the
ownership above and the lifecycle invariants tracked in #3 are stable enough to split without
creating cyclic ORM Modules.

## Interfaces

A Module interface is the smallest surface callers need to exercise a business capability.
For business Modules, prefer use-case operations, typed commands/results and domain errors.
Transport types, ORM query construction, adapter selection and synchronization details stay in
the implementation.

Package `__init__.py` files are convenience entry points, not a published compatibility ABI.
Add exports only for caller-facing use cases, results or errors. Do not re-export concrete
adapters or another Module's interface: callers import Search from `quirebase.search`, for
example, never through `quirebase.operations`.

An internal helper imported across Modules is an architectural pressure point. Repeated use is
a signal to move the concept to its owner or deepen the owning interface; it is not a reason to
create a generic shared-utilities package.

## Allowed dependency directions

Every new top-level dependency must be added to the policy test and justified here. Existing
directions are:

| Source | May depend on | Ownership reason |
| --- | --- | --- |
| `access` | `core`, `models` | Evaluate policies using persisted identities and domain errors |
| `accounts` | `core`, `models`, `library` | Authentication persistence plus the Library-owned Audit Event sink |
| `library` | `access`, `core`, `models`, `discovery`, `pipeline`, `search` | Authorization and persistence; upstream metadata/identifier integration; PDF inspection; search-index synchronization |
| `projects` | `access`, `core`, `models`, `library`, `search` | Authorization, Project persistence, audit recording and Item index synchronization |
| `documents` | `access`, `core`, `models`, `library`, `operations`, `pipeline` | Authorization, file persistence, auditing, runtime settings and durable export/inspection jobs |
| `discovery` | `access`, `core`, `models`, `documents`, `library`, `operations`, `pipeline`, `search` | Candidate authorization, import/file operations, Item creation and audit, provider settings, inspection and indexing |
| `pipeline` | `core`, `models`, `library`, `operations`, `search` | Durable execution, audit recording, maintenance handlers and index updates |
| `operations` | `core`, `models`, `library` | Infrastructure access, operational persistence and audit recording |
| `search` | `models` | Build and query the derived search representation |
| `web` | Business Modules, `access`, `core`, `models` | Invoke use cases and format their returned ORM-backed views during the current persistence phase |
| `core` | Nothing above infrastructure | Infrastructure must not know business concepts |

The broad `library` ↔ `discovery` relationship and the shared Audit Event dependency are known
deepening candidates. New code must not expand those relationships without first selecting an
owner and a narrower interface.

Business Modules never import FastAPI, MCP transports or vendor AI SDKs. Inbound adapters do
not own transactions, ORM persistence, audit recording, object storage or search-index writes.
True external systems receive a port and production/test adapters; local concrete dependencies
remain concrete until a second adapter is justified.

## Change completion criterion

An architecture change is complete when every affected concept has one owner, every new
cross-package dependency is documented and enforced, tests exercise an agreed seam, and the
architecture suite fails if the old violation is reintroduced.
