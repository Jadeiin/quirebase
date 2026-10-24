---
status: accepted
---

# ADR 0005: use a deep standalone runtime for scholarly Providers

Runtime execution follows [ADR 0006](0006-async-runtime-and-persistence.md).

Inquiro is an independently installable package in the Quirebase monorepo. It is independent of
Quirebase business policy and persistence, owns several true external Provider dependencies, and
offers reusable scholarly lookup and Search behaviour outside the application. Quirebase,
Inquiro and Excerpo are released to the same package index at one version so the application wheel
can resolve its exact workspace-package dependencies independently.

Inquiro exposes one asynchronous `ProviderRuntime` with `lookup`, `lookup_many`, `search` and
`acquire_document` operations. The runtime owned the fixed Provider catalog and order, shared
identifier parsing, document-source classification, capability dispatch, typed credentials,
validation, error normalization and transport lifecycle. Its normalized Candidate Record and page
values are immutable; document acquisition returns a context-managed stream with immutable receipt
metadata. Inquiro does not expose clients, registries, Provider protocols, dynamic plugin
discovery, parsing helpers or HTTP-library types through its package facade.

Provider files are leaf Implementations. Shared DOI, ISBN, PMID, arXiv, OpenAlex, bibcode and
article-number parsing belongs to the `identifiers` Module; a Provider must not import a peer
Provider or depend back on the runtime or catalog. A single bounded transport Implementation owns
timeouts, headers, redirect policy, response-size limits, rate-limit handling and HTTP failure
classification. Metadata requests reject redirects; PDF requests follow a bounded redirect chain,
stream into managed temporary storage and validate their size and PDF header. Production HTTP and
test Mock exchanges are Adapters at the same internal seam. The runtime preserves the semantic
difference between lookup 404 (Candidate not found), Search 404 (empty page) and document 404 (PDF
not available).

`lookup` returns one Candidate Record or raises a typed error. `lookup_many` returns an ordered
outcome for each of up to 50 input positions, retaining duplicates and individual failures.
The runtime groups native arXiv and PubMed requests, validates each returned record and bounds
concurrent I/O. Other Providers retain singleton requests: OpenAlex's single-entity endpoint is
free while filters consume budget, and Crossref's single-DOI requests use a lighter request class.
Native Providers implement one batch path for fetching, identity matching and parsing, shared by
single and batch operations. The runtime unwraps a single outcome into the exception contract.
Native batches split on response-size overflow while preserving the configured byte limit;
rate-limit and other request failures do not trigger automatic fan-out or retries. Provider-specific
batch implementations remain private. Single Item updates retain single lookup and its exception
contract. `ProviderRateLimited` preserves an optional Retry-After delay without retrying inside
Inquiro. Batch `LookupFailure` values preserve rate-limit classification and Retry-After as well.
Library adapts PDF lookup failures to checkpointed values and owns durable backoff and
file-level fallback, as defined in [ADR 0009](0009-durable-import-and-object-maintenance.md).

Quirebase Library owns runtime construction and closure through `async with` for each integrated
business operation, sharing one runtime across an identifier Import or a PDF Provider-group attempt.
PDF preparation checkpoints extraction per file and lookup outcomes per group, then retries only
unavailable sources. It maps Inquiro values
explicitly to Library write or read models and translates Inquiro errors to typed domain errors.
Discovery execution and its Audit Event therefore cross the Library
Interface. Document acquisition remains a standalone package capability until a Library operation
adopts it; the Web Adapter never imports Inquiro directly.

## Considered options

- Separate lookup and Search clients were rejected because they duplicated outbound safety,
  credentials and lifecycle policy and created cyclic imports through the Provider registry.
- A separate document-acquisition client was rejected for the same reason. The managed document
  result keeps stream ownership explicit without exposing the transport or Provider adapters.
- A public Provider registration/plugin Interface was rejected because the allowlist is fixed and
  there is no second real extension consumer. Publishing that seam now would widen the Interface
  with registration and Provider-specific knowledge.
- Provider-local copies of DOI parsing were rejected because they duplicate one identifier
  concept. Importing Crossref's private parser from DataCite was also rejected because it made one
  independent Provider depend on a peer Implementation.
- Keeping Web-to-Inquiro calls was rejected because it leaked package errors and split Discovery
  auditing from the business operation.

## Consequences

- Adding a Provider changes the private catalog and its contract tests, not ordinary callers.
- Inquiro retains its bibliography and citation Modules, but callers import those explicit Module
  Interfaces rather than widening the Provider facade.
- Architecture tests enforce the leaf-Provider rule, the documented runtime operations, the narrow
  facade, Library-owned Provider integration and absence of the former lookup/search clients and
  registry.
