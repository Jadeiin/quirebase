# Online metadata lookup and search

The Import page accepts known DOI, PMID, arXiv, OpenAlex, and ISBN identifiers. Automatic detection chooses the provider. Results enter an import preview and are not written until the user confirms.

Online Search is a separate discovery workflow. It accepts fielded clauses using provider-supported AND, OR, or NOT combinations, plus source-specific sorting, year bounds, and pagination. OpenAlex only permits OR between adjacent conditions on the same field; the application rejects unsupported cross-field OR instead of changing its meaning. Search results are never trusted as import payloads: selecting a candidate submits only its provider and identifier, refetches the complete record, and enters the same preview-before-commit flow.

DOIs are queried first through Crossref and fall back to DataCite when Crossref has no record. PMID uses NCBI PubMed ESummary, arXiv uses its Atom API, ISBN uses Open Library, and OpenAlex IDs use the Works API. Search supports OpenAlex, Crossref, PubMed, arXiv, and Open Library. Provider metadata can be incomplete and should be reviewed before confirmation.

Set `QUIREBASE_METADATA_CONTACT_EMAIL` to a monitored operator address. `QUIREBASE_NCBI_API_KEY` and `QUIREBASE_OPENALEX_API_KEY` are optional; an OpenAlex key can increase the request budget and expose usage tracking under the provider's current plan. Timeouts and maximum response size are controlled with `QUIREBASE_METADATA_TIMEOUT_SECONDS` and `QUIREBASE_METADATA_MAX_RESPONSE_BYTES`.

The implementation does not resolve arbitrary URLs or landing pages. It connects only to fixed HTTPS provider endpoints; redirects are rejected. Queries are authenticated application actions, result pages are bounded, search terms are not written to the audit log, and imports require preview confirmation.

Run deterministic adapter tests with `uv run pytest -q tests/test_metadata_lookup.py tests/test_online_search.py`. The diagnostic script requires internet access and may fail when an upstream service is unavailable or rate-limits the deployment.

Official API documentation:

- Crossref REST API: <https://www.crossref.org/documentation/retrieve-metadata/rest-api/>
- DataCite single DOI retrieval: <https://support.datacite.org/docs/api-get-doi>
- NCBI E-utilities: <https://www.ncbi.nlm.nih.gov/books/NBK25499/>
- arXiv API: <https://info.arxiv.org/help/api/user-manual.html>
- OpenAlex authentication and rate limits: <https://help.openalex.org/api/authentication/>
- Open Library Search API: <https://openlibrary.org/dev/docs/api/search>
