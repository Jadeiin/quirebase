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
transport. Reuse it for the lifetime of one operation so its HTTP client can reuse connections.
For multiple independent identifiers, `lookup_many(values, provider="auto")` accepts 1–50 strings
and returns an ordered tuple of `LookupOutcome(value, result)`. Each result is a `CandidateRecord`
or a `LookupFailure` with `code` (`invalid_request`, `not_found`, `unavailable`) and `message`.
Failures also carry `rate_limited` and optional `retry_after_seconds`, preserving upstream 429 hints
for callers that own durable backoff. Inquiro does not retry these failures internally.
Repeated input positions remain separate outcomes; invalid identifiers and upstream failures do
not remove successful siblings. Invalid batch shapes raise `InvalidProviderRequest` before I/O.
Cancellation propagates and joins in-flight requests before the runtime closes.

Batch lookup merges arXiv `id_list` and PubMed EFetch `id` requests, matching returned identities
to the input positions and preserving explicit arXiv versions. Parsed lookup keys normalize PMIDs
to ASCII decimal without leading zeros and fold arXiv letter case; `LookupOutcome.value` retains
the original input. Oversized metadata responses split
by distinct parsed lookup keys under the original byte limit, keeping all positions for the same
key together. A single key that still exceeds the limit fails for all its input positions without
further requests. Other Providers use their existing singleton
endpoints with at most three simultaneous requests per `lookup_many` call. In particular,
OpenAlex retains its free single-entity endpoint; Crossref retains its lighter single-DOI endpoint.
Batch input does not imply switching to a list/filter endpoint. Rate-limit and other upstream
request failures become outcomes without automatic retries or request fan-out. A shared runtime
does not coordinate quotas across processes. Single `lookup` retains its candidate/exception contract.
For a metadata 429, `ProviderRateLimited` (a `ProviderUnavailable` subclass) carries
`retry_after_seconds` parsed from Retry-After delta-seconds or an HTTP-date. No hint produces `None`.
The host owns waiting and retry policy; OpenAlex does not try its alternate DOI URL after a 429.

Candidate Records separate the metadata source (`provider`), query context
(`lookup_identifier`), and the standard Commonmeta `work`. For lookup,
`lookup_identifier` preserves the parsed input; for Search, it supplies the identifier to use in
a subsequent lookup. A DOI lookup against OpenAlex keeps the DOI as its lookup input and returns
the OpenAlex Work URL and DOI in `work.id` and `work.identifiers`. Crossref and DataCite retain
their source names in `provider`. Works can contain multiple identifiers in each namespace;
lookup inputs are never added as confirmed identities. Identifier comparison uses ASCII-only
DOI case folding; non-ASCII differences remain significant.

Explicit requests accept metadata source names or their primary Identifier Namespaces:
`openlibrary`/`isbn`, `nasa_ads`/`bibcode`, `pubmed`/`pmid`, and `ieee`. PMC's Identifier Namespace
is `pmcid`; it supports Search and document acquisition, but has no metadata lookup adapter.

The `commonmeta` source supports explicit DOI lookup through
`https://commonmeta.org/{doi}?format=commonmeta`, returning the complete standard Work.
It requires no credentials and supports Lookup only. Generic DOI routing keeps its existing
default. The hosted service cannot safely resolve DOI values containing `?`, `#` or `%`;
these inputs receive an explicit error when `commonmeta` is selected.

`work.contributors` contains standard Person/Organization credits, roles, identifiers and
affiliations. The credit's `type` selects the active entity. PubMed lookup uses EFetch XML for
complete author names, collective authors and affiliations; its Search adapter uses ESummary.
Authorless provider records omit the optional contributors collection. Name parsing and suffix
projections for citation writers operate on temporary copies and never replace stored name fields.

Keywords live in `work.subjects`; delimiters inside a source term remain part of that term.
`work.url` contains the landing page and `work.files` contains downloadable links and MIME types.
Optional nonempty collections are omitted when no usable values remain. Source-only facts with
no standard field receive conversion diagnostics. CLI JSON and bibliography exports consume
the same Work contract.

`acquire_document` accepts an HTTP(S) PDF URL or a scholarly identifier supported by a
document Provider. Native document Adapters support arXiv IDs, OpenAlex Work IDs and DOI lookup,
Crossref DOI full-text links, PMCIDs through the current PMC AWS article datasets, and the
documented PDF URL from open-access IEEE article metadata. It performs bounded streaming GETs,
follows PDF redirects, verifies the PDF header and returns a managed temporary stream with size and
SHA-256 metadata. Tests can inject
`MockExchange` through
`ProviderRuntime.with_exchange`; concrete Provider Implementations and registrations are private.

Bibliography and citation operations live behind `inquiro.bibliography`: Commonmeta Work
parse/export, Citation Key formulas, styles and CSL rendering. `inquiro.Work` is generated from
the pinned official Commonmeta schema; `inquiro.work` supplies standard validation and identifier
comparison helpers. Item persistence, required titles, merging, permissions and duplicate policy
belong to the host application. See the [support matrix](../../docs/architecture/item-metadata-json.md).

## CLI

The package installs an `inquiro` command for local use, smoke tests, and agent workflows. It
writes successful results as JSON to stdout:

```console
$ inquiro lookup 10.1038/s41586-019-1666-5
$ inquiro search crossref "machine learning" --field title --per-page 5
$ inquiro search openalex quantum --clause author not Einstein
```

`lookup` and `search` default to envelopes containing `work`, `provider`, `lookup_identifier`
and conversion diagnostics. They can also export BibTeX, RIS, CSL-JSON or Commonmeta:

```console
$ inquiro lookup 10.1016/j.engappai.2025.112079
$ inquiro lookup 10.1038/s41586-019-1666-5 --format commonmeta
$ inquiro lookup 10.1038/s41586-019-1666-5 --provider commonmeta --format commonmeta
$ inquiro search crossref "machine learning" --format bibtex > references.bib
```

External conversion is delegated to commonmeta-py over locally fetched payloads, without
implicit network resolution. BibTeX/RIS exports with editors are rejected; use Commonmeta or
CSL-JSON. CSL input and final output use the upstream bundled schema; Work types without a
valid upstream CSL conversion produce a structured format error. Malformed import records receive
individual diagnostics while valid siblings remain available. Unsupported custom fields and
source attributes receive diagnostics on import.
The pinned release also requires explicit errors for hyphenated RIS values and versioned Software
CSL output. Temporary conversion guards live in one private Inquiro adapter; independent
[upstream reproducers and a proposed patch](../../docs/upstream/commonmeta-py-0.309/README.md)
document their removal criteria. RIS TI/T1 aliases, CSL local keys and conservative date-range
precision are normalized on temporary input copies.
Bibliography keys are generated and disambiguated within output, without identifier claims.

Bibliography exports accept `--sort-by input|citation_key|author|year|title`,
`--doi-policy include|omit` and `--url-policy include|omit|omit_when_doi`.
The conditional URL policy checks the Work's DOI even if DOI output is omitted.
BibTeX also supports `--preserve-case` and `--encoding unicode|latex`; both representations
escape text safely and preserve inline math. LaTeX mode converts supported characters to
commands, retaining characters without a known representation. Repeat `--exclude-field FIELD`
to omit native BibTeX or CSL-JSON fields (required identity/type fields are protected).
Generic exclusions are unavailable for RIS. All preferences operate on temporary output;
Commonmeta exports always preserve the complete Work snapshot.

`python -m inquiro` provides the same interface. Known errors are JSON on stderr and use exit code
2 for invalid requests, 3 for a missing Candidate Record, and 4 for an unavailable Provider.

Provider credentials and identity settings are read from `INQUIRO_CONTACT_EMAIL`,
`INQUIRO_OPENALEX_API_KEY`, `INQUIRO_NCBI_API_KEY`, `INQUIRO_NASA_ADS_TOKEN`, and
`INQUIRO_IEEE_API_KEY`. OpenAlex PDF acquisition requires its API key because the content endpoint
is metered; ordinary OpenAlex metadata lookup remains available without one.

Commonmeta owns bibliographic classifications and format mappings. Quirebase maintains no
parallel bibliography schema or type registry. Regenerate the Python contract from the locked
schema with `uv run python scripts/generate-commonmeta-models.py` at the repository root.
