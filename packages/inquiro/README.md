# inquiro

Academic metadata discovery, multi-provider search, bibliography interchange, and CSL citation engine.

Provider lookup, Search and PDF acquisition use one asynchronous runtime:

```python
import asyncio

from inquiro import DocumentRequest, ProviderRuntime, SearchClause, SearchQuery


async def main():
    async with ProviderRuntime() as providers:
        candidate = await providers.lookup("10.1038/s41586-019-1666-5")
        page = await providers.search(
            SearchQuery(
                provider="crossref",
                clauses=(SearchClause("title", "and", "machine learning"),),
            )
        )
        async with await providers.acquire_document(
            DocumentRequest("https://example.org/article.pdf")
        ) as document:
            async for chunk in document:
                consume(chunk)


asyncio.run(main())
```

The runtime owns the fixed Provider catalog, identifier parsing, credentials and bounded HTTP
transport. Candidate Records separate the metadata source (`provider`), query context
(`lookup_identifier`), and confirmed record identities (`identifiers`). For lookup,
`lookup_identifier` preserves the parsed input; for Search, it supplies the identifier to use in
a subsequent lookup. A DOI lookup against OpenAlex keeps the DOI as its lookup input and returns
the OpenAlex Work ID and DOI in `identifiers`. Crossref and DataCite return DOI identities while
retaining their source names in `provider`. Confirmed identities contain at most one value per
identifier namespace; lookup inputs are not appended to them.

Explicit requests accept metadata source names or their primary Identifier Namespaces:
`openlibrary`/`isbn`, `nasa_ads`/`bibcode`, `pubmed`/`pmid`, and `ieee`. PMC's Identifier Namespace
is `pmcid`; it supports Search and document acquisition, but has no metadata lookup adapter.

Candidate Record `authors` contains `Contributor` values with a display name, source-supplied
family/given names and suffixes, person/organization kind, author identifiers, per-record affiliations and
nullable corresponding-author status. Each `Affiliation` can retain institution identifiers,
country code and the original affiliation text. OpenAlex maps authorship affiliation strings to
its institutions, including ROR identifiers. PubMed Lookup uses EFetch XML for complete author
names, collective authors and affiliations; its Search adapter still uses ESummary.
`Contributor.bibliographic_name` provides a separate formatting projection for sources that only
supply display names, without presenting inferred name parts as upstream facts. The two-part
bibliographic projection includes a supplied suffix in the family name.

`keywords` is a tuple of terms; delimiters inside one upstream term remain part of that term.
`urls` contains `ResourceLink` values whose `kind` distinguishes landing pages and full text.
Where the source provides them, links retain media type, version, license, open-access status and
intended application. Adapters use the API's link fields instead of guessing from URL suffixes.
For optional collections, `None` means unavailable and an empty tuple means explicitly empty.
These structured values are also exposed in CLI JSON; bibliography export consumes them directly.

`acquire_document` accepts an HTTP(S) PDF URL or a scholarly identifier supported by a
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
`clean_rich_markup`, `normalize_publication_date`, …) used by Providers and host applications.

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

BibTeX and BibLaTeX derive supported Item Identifier Namespaces from the fixed Provider
definitions. ISSN remains a custom field because it identifies a journal.
Chapter ISBNs remain custom bibliographic fields because they identify the containing book;
book ISBNs remain Item identifiers. Recognized `eprint`
archives use canonical namespaces (`PubMed` becomes `pmid`); unspecified or unknown archives
remain custom fields. The bibliography API exports them with
`BibliographyExportOptions(include_custom_fields=True)`.

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

Reference Type semantics and directional mappings live in `inquiro.reference_types`. One enum
selects supported types from citeproc-py's bundled CSL schema, followed by the preprint extension.
The engine is a base dependency; the style catalog remains in the citation extra. Custom CSL
validation and rendering work without the optional style catalog. Import mappings specify
the source format or Provider; exporters choose an explicit target format, including CSL.
Unsupported file types become document with a warning and retained source type in custom fields.

Publication Dates use `python-dateutil` for textual parsing and retain only explicit year, month
or day precision. Ranges reduce to their shared year or month; cross-year ranges have no single
Publication Date. Provider, bibliography import and CSL output share this normalization.
