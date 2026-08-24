# ADR 0005: use a deep standalone runtime for scholarly Providers

Status: accepted.

Inquiro is an independently installable package in the Quirebase monorepo. It is independent of
Quirebase business policy and persistence, owns several true external Provider dependencies, and
offers reusable scholarly lookup and Search behaviour outside the application. Quirebase,
Inquiro and Rubrica are released to the same package index at one version so the application wheel
can resolve its exact workspace-package dependencies independently.

Inquiro exposes one synchronous `ProviderRuntime` with `lookup` and `search` operations. The
runtime owns the fixed Provider catalog and order, shared identifier parsing, capability dispatch,
typed credentials, validation, error normalization and transport lifecycle. Its normalized
Candidate Record and page values are immutable. Inquiro does not expose clients, registries,
Provider protocols, dynamic plugin discovery, parsing helpers or HTTP-library types through its
package facade.

Provider files are leaf Implementations. Shared DOI, ISBN, PMID, arXiv, OpenAlex, bibcode and
article-number parsing belongs to the `identifiers` Module; a Provider must not import a peer
Provider or depend back on the runtime or catalog. A single bounded transport Implementation owns
timeouts, headers, redirect refusal, response-size limits, rate-limit handling and HTTP failure
classification. Production HTTP and test Mock exchanges are Adapters at the same internal seam.
The runtime preserves the semantic difference between lookup 404 (Candidate not found) and Search
404 (empty page).

Quirebase Library owns runtime construction and closure for each business operation. It maps
Inquiro values explicitly to Library write or read models and translates Inquiro errors to typed
domain errors. Discovery execution and its Audit Event therefore cross the Library Interface;
the Web Adapter never imports Inquiro.

## Considered options

- Separate lookup and Search clients were rejected because they duplicated outbound safety,
  credentials and lifecycle policy and created cyclic imports through the Provider registry.
- A public Provider registration/plugin Interface was rejected because the allowlist is fixed and
  there is no second real extension consumer. Publishing that seam now would widen the Interface
  with registration and Provider-specific knowledge.
- Provider-local copies of DOI parsing were rejected because they duplicate one identifier
  concept. Importing Crossref's private parser from DataCite was also rejected because it made one
  independent Provider depend on a peer Implementation.
- Keeping Web-to-Inquiro calls was rejected because it leaked package errors and split Discovery
  auditing from the business operation.

## Consequences

- Existing internal Python signatures and compatibility aliases are replaced rather than shimmed;
  every Quirebase caller and contract test migrates atomically in the monorepo.
- Adding a Provider changes the private catalog and its contract tests, not ordinary callers.
- Inquiro retains its bibliography and citation Modules, but callers import those explicit Module
  Interfaces rather than widening the Provider facade.
- Architecture tests enforce the leaf-Provider rule, the narrow facade, Library-only application
  dependency and absence of the former lookup/search clients and registry.
