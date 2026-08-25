# Discovery: Online metadata lookup and external search

The Import page accepts known DOI, PMID, arXiv, OpenAlex, and ISBN identifiers. Automatic detection chooses the Provider. Results enter an import preview and are not written until the user confirms.

Online Search is a Discovery workflow separate from Import. It accepts fielded clauses using provider-supported AND, OR, or NOT combinations, plus source-specific sorting, year bounds, and pagination. OpenAlex only permits OR between adjacent conditions on the same field; the application rejects unsupported cross-field OR instead of changing its meaning. Discovery results are never trusted as import payloads: selecting a candidate submits only its provider and identifier, refetches the complete record, and enters the same preview-before-commit flow.

DOIs are queried first through Crossref and fall back to DataCite when Crossref has no record. PMID uses NCBI PubMed ESummary, arXiv uses its Atom API, ISBN uses Open Library, and OpenAlex IDs use the Works API. Explicit lookups also support NASA ADS (`bibcode`) and IEEE Xplore (`article_number`). Discovery supports OpenAlex, Crossref, PubMed, PMC, arXiv, Open Library, NASA ADS, and IEEE Xplore. Provider metadata can be incomplete and should be reviewed before confirmation.

Set `INQUIRO_CONTACT_EMAIL` to a monitored operator address. `INQUIRO_NCBI_API_KEY` and `INQUIRO_OPENALEX_API_KEY` are optional; `INQUIRO_NASA_ADS_TOKEN` and `INQUIRO_IEEE_API_KEY` are required to query NASA ADS and IEEE Xplore respectively. Timeouts and maximum response size are controlled with `INQUIRO_TIMEOUT_SECONDS` and `INQUIRO_MAX_RESPONSE_BYTES`.

The implementation does not resolve arbitrary URLs or landing pages. It connects only to fixed HTTPS Provider endpoints; redirects are rejected. Queries are authenticated application actions, result pages are bounded, search terms are not written to audit events, and imports require preview confirmation.

Run deterministic Provider tests with
`uv run pytest -q packages/inquiro/tests/test_provider_lookup.py packages/inquiro/tests/test_provider_search.py`.
Run the Quirebase integration tests with
`uv run pytest -q tests/test_metadata_lookup.py tests/test_online_search.py`. The diagnostic script
requires internet access and may fail when an upstream service is unavailable or rate-limits the
deployment.

Official API documentation:

- Crossref REST API: <https://www.crossref.org/documentation/retrieve-metadata/rest-api/>
- DataCite single DOI retrieval: <https://support.datacite.org/docs/api-get-doi>
- NCBI E-utilities (PubMed & PMC): <https://www.ncbi.nlm.nih.gov/books/NBK25499/>
- arXiv API: <https://info.arxiv.org/help/api/user-manual.html>
- OpenAlex authentication and rate limits: <https://help.openalex.org/api/authentication/>
- Open Library Search API: <https://openlibrary.org/dev/docs/api/search>
- NASA ADS API: <https://github.com/adsabs/adsabs-dev-api>
- IEEE Xplore API: <https://developer.ieee.org/>
