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
    with providers.acquire_document(DocumentRequest("https://example.org/article.pdf")) as document:
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

Bibliography and citation functionality lives behind the `inquiro.bibliography` package facade:
neutral records and `record_from_item`, bibliography parse/export across BibTeX, BibLaTeX, RIS
and EndNote, the Citation Key formula DSL with `preview_citation_key`, the built-in Citation
Style catalog and CSL rendering. The package's internal modules are private implementation seams.
`inquiro.canonical` exposes the shared payload cleaning helpers (`clean_markup`,
`clean_rich_markup`, `normalize_reference_type`, …) used by Providers and host applications.

## CLI

The package installs an `inquiro` command for local use, smoke tests, and agent workflows. It
writes successful results as JSON to stdout:

```console
$ inquiro lookup 10.1038/s41586-019-1666-5
$ inquiro search crossref "machine learning" --field title --per-page 5
$ inquiro search openalex quantum --clause author not Einstein
```

`lookup` and `search` keep JSON as their default output and can export Candidate Records directly
as BibTeX, BibLaTeX, RIS, or EndNote:

```console
$ inquiro lookup 10.1038/s41586-019-1666-5 --format biblatex
$ inquiro search crossref "machine learning" --format bibtex > references.bib
$ inquiro search openalex quantum --format ris --per-page 50 > references.ris
$ inquiro lookup 10.1000/example --format endnote --omit-abstract
```

Bibliography exports generate Citation Keys with Inquiro's default formula and disambiguate
collisions within search results. `--encoding latex` selects LaTeX text encoding for BibTeX and
BibLaTeX; `--preserve-case` protects uppercase title text, and `--include-identifiers` adds
non-DOI identifiers.

Titles and abstracts use a deliberately restricted rich-text vocabulary. Inquiro canonicalizes
`i`/`em`, `b`/`strong`, `sup`, and `sub` HTML without attributes, and converts them to and from
`\emph`/`\mkbibemph`/`\textit`, `\textbf`, `\textsuperscript`, and `\textsubscript`. BibTeX and
BibLaTeX retain those semantics as LaTeX; RIS and EndNote receive plaintext. Unknown or unsafe
HTML is removed, while unsupported LaTeX formatting degrades to its argument text. Paired inline
math such as ``H$_2$O`` is preserved verbatim across conversions; unpaired dollars are ordinary
characters.

`python -m inquiro` provides the same interface. Known errors are JSON on stderr and use exit code
2 for invalid requests, 3 for a missing Candidate Record, and 4 for an unavailable Provider.

Provider credentials and identity settings are read from `INQUIRO_CONTACT_EMAIL`,
`INQUIRO_OPENALEX_API_KEY`, `INQUIRO_NCBI_API_KEY`, `INQUIRO_NASA_ADS_TOKEN`, and
`INQUIRO_IEEE_API_KEY`. OpenAlex PDF acquisition requires its API key because the content endpoint
is metered; ordinary OpenAlex metadata lookup remains available without one.
