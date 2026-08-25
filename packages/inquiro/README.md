# inquiro

Academic metadata discovery, multi-provider search, bibliography interchange, and CSL citation engine.

Provider lookup, Search and PDF acquisition use one synchronous runtime:

```python
from inquiro import DocumentRequest, ProviderRuntime, SearchClause, SearchQuery

with ProviderRuntime() as providers:
    candidate = providers.lookup("10.1038/s41586-019-1666-5")
    page = providers.search(
        SearchQuery(
            provider="crossref",
            clauses=(SearchClause("title", "and", "machine learning"),),
        )
    )
    with providers.acquire_document(
        DocumentRequest("https://example.org/article.pdf")
    ) as document:
        consume(document.stream)
```

The runtime owns the fixed Provider catalog, identifier parsing, credentials and bounded HTTP
transport. `acquire_document` accepts an HTTP(S) PDF URL or a scholarly identifier supported by a
document Provider. Native document Adapters support arXiv IDs, OpenAlex Work IDs and DOI lookup,
Crossref DOI full-text links, PMCIDs through the current PMC AWS article datasets, and the
documented PDF URL from open-access IEEE article metadata. It performs bounded streaming GETs,
follows PDF redirects, verifies the PDF header and returns a managed temporary stream with size and
SHA-256 metadata. Tests can inject
`MockExchange` through
`ProviderRuntime.with_exchange`; concrete Provider Implementations and registrations are private.

Bibliography and citation functionality has separate Module Interfaces under
`inquiro.bibliography` and `inquiro.citations`.

## CLI

The package installs an `inquiro` command for local use, smoke tests, and agent workflows. It
writes successful results as JSON to stdout:

```console
$ inquiro lookup 10.1038/s41586-019-1666-5
$ inquiro search crossref "machine learning" --field title --per-page 5
$ inquiro search openalex quantum --clause author not Einstein
```

`python -m inquiro` provides the same interface. Known errors are JSON on stderr and use exit code
2 for invalid requests, 3 for a missing Candidate Record, and 4 for an unavailable Provider.

Provider credentials and identity settings are read from `INQUIRO_CONTACT_EMAIL`,
`INQUIRO_OPENALEX_API_KEY`, `INQUIRO_NCBI_API_KEY`, `INQUIRO_NASA_ADS_TOKEN`, and
`INQUIRO_IEEE_API_KEY`. OpenAlex PDF acquisition requires its API key because the content endpoint
is metered; ordinary OpenAlex metadata lookup remains available without one.
