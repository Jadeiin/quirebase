# Further Advanced Alchemy adoption

Research baseline: Advanced Alchemy **1.11.0**, pinned by `pyproject.toml`, on
`prototype/advanced-alchemy-use-cases` at `c2808d5`. Findings combine application inspection,
installed dependency source and disposable in-memory probes. PostgreSQL compilation was checked;
live PostgreSQL and S3 behavior were not exercised. The investigation below preceded implementation; the resulting choices are recorded in the accepted
[persistence decision](../adr/0014-advanced-alchemy-persistence.md).

## Implementation outcome

The follow-up implements the existing-use-case recommendations: bounded Workspace member
directories, the Library/User/Audit offset contract, Project detail summary with an independently
paginated Item section, native file-presence and sorting filters, batch-owned staged PDF descriptors,
optional native S3 signing, nested bibliography loaders and API Token result conversion. It preserves
one initial migration and adds no previous-schema adapter. ADR 0014 defines the accepted boundaries;
the [implementation record](../architecture/advanced-alchemy-implementation.md) preserves current
choices. The sections below retain the original investigation and alternatives.

EncryptedText is explicitly excluded by the user. MFA and semantic search require new product
flows and were deferred after the user selected enhancement of existing use cases only. Direct S3
delivery is a deployment opt-in because private object endpoints cannot be reached by browsers.
Native signature generation is verified offline; it does not establish live S3/CORS compatibility.

Verification at the original implementation snapshot: the backend suite passed 1,074 tests with 89
configured skips; the frontend passed
114 unit tests, 156 browser tests and five real full-stack tests, including durable PDF Import.
Ruff, mypy, frontend type/style/lint checks, localization and generated API types passed. A fresh
SQLite database passed initialization and doctor; a separate migration-only database had no Alembic
schema drift. The single PostgreSQL initial revision compiled offline; live PostgreSQL and S3/CORS
remained unverified at that snapshot. Browser suites run sequentially because they share the
frontend build directory. Subsequent [CI at dd9118e](https://github.com/Jadeiin/quirebase/actions/runs/37598255080)
passed live PostgreSQL, controlled concurrency and S3 object-store contracts. Direct browser S3/CORS
configuration remains a deployment-specific requirement.

An isolated same-lock build of the previous commit already exceeded six bundle budgets. This
follow-up adds about 1.1 KiB raw / 0.3 KiB gzip to the shared shell, mostly localized directory copy;
Library controls add about 1.4 KiB raw / 0.5 KiB gzip. Affected budgets now reflect the measured
application without adding libraries or broadening the PDF dependency boundary.

## Recommendation

| Priority | Native capability | Complete application use case | Expected benefit |
| --- | --- | --- | --- |
| P0 | `LimitOffset`, `OffsetPagination`, typed statement filters | Bounded member directories and Project Item lists; one local directory contract | Consistent search, sorting and page controls; bounded queries and projections |
| P0 | `EncryptedText` with `FernetBackend` | Provider credentials with configured/replace/clear settings | Encrypted database values and fewer secrets returned to the browser |
| P1 | `StoredObject(multiple=True)` / `FileObjectList` | PDF Import Batch staging, retry, confirmation and cleanup | One typed file descriptor format across persistent file use cases |
| P1, S3 deployments | `FileObject.sign_async` | Authorized short-lived PDF/export downloads | Less application bandwidth and native signing rather than another signer |
| Opportunistic | Repository `load=` and `ResultConverter.to_schema` | Owned aggregate loading profiles and simple Web response DTOs | Delete repeated loading/mapping code where there is a real repeated pattern |
| Product-dependent | `TOTPSecret`, `OneTimeCode` | Administrator MFA and recovery challenges | Native encrypted secrets and hashed code values beneath a complete account flow |
| Product-dependent | `Vector` | Semantic Library Search | A useful storage type after an embedding/search product is chosen |

Implement the first two as separate complete changes. Then close the PDF staging descriptor gap.
Signed downloads depend on the deployment and reader requirements; MFA and semantic search are
new product capabilities rather than immediate persistence simplifications. Benefits above are
qualitative; these probes do not establish latency or throughput gains.

## Bounded directories and native filters

Workspace and Project directories already use native offset pagination, with a default of 25
and a maximum of 100. The remaining concrete gaps are:

- [Workspace member APIs](../../src/quirebase/web/api/workspaces.py) return complete lists for
  both the ordinary directory and governance view. Add username search, stable ordering and
  bounded pages, loading usernames and decision projections only for page roots. Participant
  selectors must resolve selected identities independently of their currently loaded page.
- [Project detail](../../src/quirebase/projects/workspaces.py) loads every assigned Item, and
  `ProjectWorkspace.svelte` renders that entire collection. Reuse Library Search's already
  authorized `project` filter for the paginated Item section; Project detail can return summary
  facts and the total instead of another unbounded Item list. Preserve the existing archived
  Project and Item lifecycle behavior when sharing the query.
- [Library Search](../../src/quirebase/library/catalog.py) already delegates slicing/counts to
  `ItemService` and `LimitOffset`, but its wire result remains `items,total,page,per_page`.
  Administrative User and Audit directories also use page-based envelopes. A breaking-change
  cleanup can standardize local directories on `items,total,limit,offset` and one frontend page
  experience. Envelope renaming alone has little value without consistent controls and limits.

AA provides `SearchFilter`, `OrderBy`, `BeforeAfter`, `OnBeforeAfter`, `ComparisonFilter`,
`CollectionFilter`, `ChoicesFilter`, `BooleanFilter`, `NullFilter`, `ExistsFilter` and
`FilterGroup`. These can replace repetitive predicates for supported product filters: created
or updated ranges, allowed sort fields, lifecycle states, and whether an Item has files.
An `ExistsFilter` avoids multiplying root rows through an association join. Full-text Library
Search remains owned by the existing SQLite/PostgreSQL search adapters.

Parse a small, explicit request contract in Web, pass domain values through the business
interface, then construct native AA filters inside the owner. Keep authorization/discoverability
in the base statement before count and slicing. Retain independent counts for empty pages and
an identity tie breaker for equal sort values. AA filters do not impose a maximum page size or
make arbitrary client-selected fields an appropriate public contract.

AA 1.11.0 supplies `OffsetPagination`, not a native cursor/keyset paginator. Keep Annotation
cursor navigation and maintenance keyset batching. Complete taxonomy and policy choice
projections have different semantics from directories. External Provider pagination is likewise
an upstream protocol, not another local ORM list to rename.

Acceptance should cover empty pages retaining their total, equal-key ordering, revoked membership,
managed Project discovery versus participation, and selecting an entity absent from the current
page. These are product/query contracts rather than tests of AA's implementation.

## Provider credential encryption and settings interaction

[SystemSetting.value](../../src/quirebase/models.py) is plain `Text`. Runtime keys include
`ncbi_api_key`, `openalex_api_key`, `nasa_ads_token` and `ieee_api_key`.
[Settings reads](../../src/quirebase/operations/settings.py) return those values, and
`AdminSettingsView` exposes them to the settings form. `RuntimeSettingsRequest` currently has
default values for every field, and the route calls `model_dump()` without `exclude_unset`.
Changing only the column type would leave the browser disclosure and replacement semantics intact.

Use native `EncryptedText` with an explicit, stable key provider and declare the
`advanced-alchemy[cryptography]` extra. Application inspection found no SQL predicates on
`SystemSetting.value`: values are selected by key and interpreted in Python. Encrypting the
entire small value column is consequently a simple option, avoiding a second secret table or
conditional persistence representation. It makes the key necessary to read persisted ordinary
settings too; document that operational consequence.

The complete use case includes:

- Core configuration supplies a durable encryption key; initialization, restart, backup/restore
  and missing-key behavior are explicit. AA's deprecated random default key changes on restart.
- Operations retains a private effective-settings read for Provider calls. The administrative
  projection returns a configured status for secrets, with replacement and clear controls.
  The form does not refill secret values. Redact credentials in the displayed database URL too.
- Omitted secret fields preserve the current setting. Explicit replacement and clear are separate
  requests; `exclude_unset` is essential at the request boundary. An empty runtime override
  currently disables an environment-provided credential, so define “clear” versus “use environment
  default” deliberately rather than silently changing that behavior.
- Audit Events continue recording modified key names without values. Keep batch validation,
  caller-owned transactions and concurrent first-creation recovery.
- Use a named key callable imported by the Alembic revision template, preserving native type
  rendering. A literal key is included in the type's `repr` and must never enter a migration.

An in-memory type probe verified ciphertext differs from plaintext and decrypts correctly. It
also confirmed a literal constructor key appears in `repr`. Resolving a callable on every access
allows a changed key to take effect, but does not supply multi-key decryption or re-encrypt old
rows. Key rotation needs a separately defined procedure; it is not delivered by the callable.

Acceptance should include restart with the same key, wrong/missing-key failure, encrypted raw
database values, a secret-free administrative response, and partial saves preserving unrelated
credentials. This follows the current alpha schema policy rather than adding an older-schema
conversion layer.

## Finish persistent file descriptors in PDF imports

File Revisions, Attachments and Annotation Export Artifacts already use `StoredObject`.
[PDF imports](../../src/quirebase/library/imports.py) still store
`_pdf: {object_key,size,original_name}` inside candidate dictionaries.
`_pdf_object_keys()` in Library and `_import_object_keys()` in
[maintenance](../../src/quirebase/operations/maintenance.py) independently decode those values.
Confirmation removes the `_pdf` payload to release the batch's reservation.

Native `StoredObject(backend="documents", multiple=True)` persists multiple `FileObject`
descriptors and reloads a mutable list; `FileObjectList` is the provided list type alias.
A plausible follow-up is one batch-owned staged-file field with a stable source reference in
each candidate. File metadata carries filename/size/content information, while candidate data
carries bibliographic values and diagnostics. Do not associate them by array position, or keep
both a canonical file field and a duplicated `_pdf` descriptor.

This is an integration candidate based on source inspection, not a completed schema experiment.
Verify that batch-level ownership remains sufficient before selecting it. If each uploaded
source needs independent processing state or lineage, a child record with one `StoredObject`
is clearer than encoding that lifecycle into file metadata.

The change must cover staging, failed preparation, retry, confirmation, discard, integrity scans
and reference-aware deletion together. Failed batches retain their reservation; committed batches
retain idempotent Item results and release staged references in the same transaction. Durable
inputs remain serializable domain values; ORM `FileObject` instances do not enter checkpoints.
Crash/replay and cleanup tests matter more than a descriptor round-trip demo. Automatic file
listeners stay disabled because ownership can transfer without the object being physically deleted.

## Native signed downloads for S3

`FileObject.sign_async(expires_in=..., for_upload=False)` delegates to `ObstoreBackend` signing.
It can sign GET downloads and PUT uploads; backend signing also accepts batches. The default
expiry is one hour, so application use should specify a short lifetime.

Start with authorized PDF or export downloads if S3 traffic warrants it. Documents resolves the
current resource and authorization, signs the persisted descriptor, and returns a download target
through a domain/Web projection. For export artifacts, the URL expiry must be bounded by the
artifact's remaining lifetime. Reader range requests, browser CORS/CSP, content disposition and
error recovery need end-to-end verification. A previously issued URL remains usable until its
expiry after authority is revoked; that behavior must suit the selected lifetime.

Local storage can lack signing support and continues through its streaming transport. Native
`FileObject.get_content_async()` returns fully buffered bytes, so replacing the current obstore
stream/range API with it would regress large-file delivery.

Direct browser upload is a separate later use case. It requires preallocated ownership and
reservation, completion verification, size/PDF validation, durable inspection and cleanup of
abandoned uploads. A native signer supplies the URL, not this lifecycle. No live S3 probe was run.

## Smaller opportunities and feature foundations

Repository `load=` supports nested relationship profiles and explicit SQLAlchemy loader options.
Repeated Item author/identifier loaders in `access/items.py` and Document revision-to-Item
loading in `access/documents.py` are candidates for an owner-local profile. Use collection
`selectinload` and deliberate scalar loading; wildcard loading broadens queries unexpectedly.
This is worthwhile where it deletes repeated aggregate-loading knowledge, not as another shared
generic repository abstraction.

`ResultConverter.to_schema` is already integrated for simple administrative DTOs. Extend it
opportunistically to attribute-only Web projections as those routes change. It supports Pydantic,
msgspec and attrs target schemas in 1.11.0; it does not make authorization, concrete policy choices
or renamed/nested product fields automatic. Native conversion belongs in Web, while business
services retain transport-neutral interfaces.

`TOTPSecret` provides an encrypted secret and `TOTPProvider` with verification and provisioning
URIs; it needs the `pyotp` extra. `OneTimeCode`/`HashedOneTimeCode` provide hashed code values
with expiry, redemption and attempt state. They are suitable foundations for administrator MFA
and account recovery if those features are prioritized. Accounts must still implement enrollment,
login challenges, recovery, revocation, audit, TOTP replay prevention, and atomic code redemption.
`.redeem()` returns a new value that must be persisted under a lock/CAS; password-cost hashing
must remain off the event loop. Existing random indexed Session/API Token/Invitation hashes serve
a different lookup protocol and do not benefit from replacement with this type.

`Vector(dim)` uses pgvector for PostgreSQL when available and JSON fallback otherwise. SQLite
can store values, but its distance operations raise `NotImplementedError`. Semantic Library Search
needs an embedding workflow, model/version selection, vector index and an explicit SQLite search
implementation or product limitation. The column type alone does not supply that feature.

## Verified limits of additional helpers

These findings apply to the installed 1.11.0 implementation; reevaluate after an upstream change.
No upstream issues or external messages were submitted as part of this research.

| Helper | Verified behavior | Adoption consequence |
| --- | --- | --- |
| FastAPI `provide_filters` | Different configurations return the same callable and overwrite its global `__signature__`. Creating a search/boolean provider changed an earlier pagination provider's signature. Its page size has `ge=1` but no upper bound, with `currentPage/pageSize` aliases. | Use explicit request parsing with native statement filters. Reconsider the factory after an upstream fix and route/OpenAPI contract checks; do not build a generic clone or monkeypatch. |
| `SQLAlchemyAsyncQueryRepository.get_one` | A two-column SELECT returned only the first scalar (`str`). `get_one_or_none` turned a valid scalar zero into `None`. | It is unsuitable for current multi-column read-model and aggregate queries. |
| QueryRepository counts | For an offset beyond two existing rows, the window path returned total zero and the basic path raised `NoResultFound`; a multi-column window count raised `ValueError`. `get_many` did preserve complete Rows. | Keep explicit SQL for Annotation/revision projections, Tag counts and storage metrics. The ordinary model repository's configured independent count path is a separate implementation. |
| Native `OnConflictUpsert` | Simple replacement worked on SQLite and compiled to PostgreSQL. Exposed updates are `column=excluded.column`; the helper has no custom conditional/increment update or `DO NOTHING` mode. | Use selectively for simple replacement upserts. Keep login throttle CASE/increment SQL and association insertion whose rowcount determines whether to audit. |
| `UniqueMixin` | Source performs a SELECT and session-local caching/add, without database-conflict savepoint recovery. | It does not replace concurrent Author/Tag uniqueness handling. |
| Repository cache | Native AA writes queue invalidation; retained Core/CAS/association SQL bypasses that mechanism. Authorization and discovery depend on other tables as well. | Do not enable cache for authorization-sensitive roots without a complete dependency/invalidation design. Built-in Citation Style catalog selection is already `lru_cache`-backed in Inquiro. |
| FastAPI service/extension lifecycle | Can manage session closure, rollback and configurable status-code commits. Existing Core already supplies native configuration and a small shared-session dependency. | Little code is deleted now; preserve caller-owned command/durable transaction boundaries and private services. It is a possible future integration, not a current high-return rewrite. |
| `SlugKey` / slug repositories | Native slug uniqueness is table-wide; available-slug generation checks before insertion. | A future Workspace-scoped URL design would still need scoped uniqueness and race handling. Introducing it now adds a second identity contract. |

`UUIDv7AuditBase`, UUID sentinel support, `DateTimeUTC`, `JsonB`, Argon2 verification/rehashing,
obstore file persistence, native Alembic representations, repositories/services and basic bulk
operations are already present in the baseline. Count these as completed adoption rather than
proposing them again. Keep explicit authorization, CAS, lock order, durable recovery and
reference-aware cleanup where they encode application correctness.

## Evidence and reproduction scope

Dependency source inspected: `advanced_alchemy/filters.py`, `service/pagination.py`,
`service/_util.py`, `repository/_async.py`, `extensions/fastapi/providers.py`,
`types/encrypted_string.py`, `types/file_object/{file,data_type}.py`,
`types/file_object/backends/obstore.py`, `types/totp.py`,
`types/password_hash/one_time_code.py`, `mixins/{uuid,unique,slug}.py`, `operations.py`
and repository cache invalidation.

Disposable probes used installed 1.11.0, in-memory SQLite and synthetic credentials. They checked
filter-provider identity/signature changes, encrypted-value round-tripping and representation,
QueryRepository single/multiple columns and empty pages, and a simple native upsert. Engines were
disposed; no application database, credential, demo script or captured output was added. Feature
recommendations whose backend was not exercised are identified above. This documentation-only
research does not repeat the application test suite or claim its results as new validation.
