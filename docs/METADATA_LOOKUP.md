# Online metadata lookup

Open **Import BibTeX/RIS** and use **Look up online metadata**. Accepted inputs are a DOI or `doi.org` URL, a numeric PMID (optionally prefixed `PMID:`), and a current or older-format arXiv ID. Automatic detection chooses the provider. Results are shown in the existing import preview and are not written until the user confirms.

DOIs are queried first through Crossref and fall back to DataCite when Crossref has no record. PMID uses NCBI PubMed ESummary. arXiv uses its Atom query API. Imported fields include title, authors, date, publication, DOI and provider-specific identifiers; abstracts and keywords are included when the provider supplies them. Provider metadata can be incomplete and should be reviewed before confirmation.

Set `QUIREBASE_METADATA_CONTACT_EMAIL` to a monitored operator address. Crossref recommends this for its polite pool and NCBI uses it to contact abusive or malfunctioning clients. `QUIREBASE_NCBI_API_KEY` is optional. Timeouts and maximum response size are controlled with `QUIREBASE_METADATA_TIMEOUT_SECONDS` and `QUIREBASE_METADATA_MAX_RESPONSE_BYTES`.

The implementation does not resolve arbitrary URLs or DOI landing pages. It connects only to fixed HTTPS endpoints at `api.crossref.org`, `api.datacite.org`, `eutils.ncbi.nlm.nih.gov`, and `export.arxiv.org`; redirects are rejected. Queries are authenticated application actions, limited to one record, recorded in the audit log, and always require preview confirmation before database insertion.

Run deterministic adapter tests with `uv run pytest -q tests/test_metadata_lookup.py`. Run a real-provider diagnostic with `uv run python scripts/check-metadata-providers.py`; this requires internet access and may fail when an upstream service is unavailable or rate-limits the deployment.

Official API documentation:

- Crossref REST API: <https://www.crossref.org/documentation/retrieve-metadata/rest-api/>
- DataCite single DOI retrieval: <https://support.datacite.org/docs/api-get-doi>
- NCBI ESummary: <https://www.ncbi.nlm.nih.gov/books/NBK25499/>
