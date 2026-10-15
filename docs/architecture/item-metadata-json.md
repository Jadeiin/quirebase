# Item Work, identifiers and queries

`Item.work` stores a Commonmeta v1.0 Work JSON object. `commonmeta-schema==1.0.1` is the schema
source; `commonmeta-py==0.309` is the conversion implementation. The Work is validated as the
schema's Work definition, rather than its broader entity root. Python models are generated with
`datamodel-code-generator==0.83.0`; strict fields, enums, nested variants, extra-property rejection
and the official validator preserve constraints that code generation cannot express alone.
Absent fields serialize by omission. The standard's nonempty arrays cannot be cleared using `[]`;
a complete manual replacement clears a field by omitting it.

Library requires a nonempty title, at most 1,000 visible characters, valid calendar publication
dates and a Work payload of at most 1 MiB. `citation_key` is a separate Item property with a
128-character limit. Inquiro accepts a standard Work without a title; these Item requirements
are Quirebase business policy. Inquiro never imports Quirebase, authorization or ORM mappings.

## Writes and lossless editing

HTTP create accepts `{metadata: Work, citation_key?: string}`; update additionally requires
`expected_version`. Omitted Citation Key preserves the existing key; explicit null clears it.
Detail and overview return the Work and Citation Key. Overview and Files reuse the overview's
Work rather than fetching a second detail snapshot. `GET /workspaces/{workspace_id}/metadata/schema`
returns the locked official schema after Workspace authorization. The Web UI lazily loads
`@sjsf/form` 3.9.0 with its Skeleton 5 theme to edit a deep copy of the complete Work. Changing
`type` does not clear contributors, identifiers, funding, relations or other hidden fields.
Advanced JSON edits must pass original-schema validation and be applied before saving. Work is
also copied deeply between Workspaces.

Library's single write seam validates every persisted payload even when the caller already holds
a typed Work, because Pydantic copies can bypass validation. Provider merge, Import confirmation
and metadata rescan all normalize through that same seam.

The editor selects `$defs.work`, retaining only the official `$schema`, `$id`, `$defs` and `$ref`
context. The registry's array root is not merged into the Work. The upstream Draft 2020-12
converter supplies a Draft-07 rendering schema; an independent `@cfworker/json-schema` 4.1.1
validator checks the original Draft 2020-12 schema on JSON application and submission without
runtime code generation or a weaker CSP. Library remains authoritative for business constraints,
authorization, version checks and persistence.

The adapter disables automatic minimum-array, empty-object and const defaults. Objects whose
`anyOf` branches contain only `required` lists render as ordinary objects, retaining those
validation conditions without a branch selector that deletes data. Nested arrays support explicit
addition, removal and reordering; removing the last entry omits an optional field. Field titles,
enums, array controls and validation messages use Lingui. Desktop editing uses two columns for
primary controls and Identifier/Funding panels; nested scalar fields use two or three columns based
on their own container width. Titles, descriptions and complex object fields span their section,
while repeated entries can appear side by side when space permits. Narrow layouts use one column
without horizontal overflow. Section summaries supply the group title once, and action buttons
retain a compact width. Nested objects and arrays (including contributor affiliations) default to
collapsed, with their fields kept mounted so closing a section never changes the Work. Person and
Organization name fields remain visible. Field errors open all collapsed ancestors; expanded state
survives language changes. Overview shares the editor’s enum translations, deduplicates affiliation
names only for display and includes Container details. PDF URL input uses a Skeleton Combobox with
unique HTTP(S) candidates from Work.files and supports manually entered URLs. Item bibliography
actions expose CSL citation, BibTeX, RIS, CSL-JSON and Commonmeta, matching Account defaults.
Switching Item identity resets the PDF URL and search drafts, including cached-page navigation.
Publication Date retains partial dates, calendar/keyboard editing and full
timestamps. DOM text inputs omit schema `pattern` attributes
because HTML's UnicodeSets expressions have different semantics; original-schema validation still
checks those patterns.

Citation Key and the Item version stay outside the Work. The editor keeps the version captured
when editing began. Failed requests retain the full draft and Citation Key; HTTP field errors map
to controls and focus the affected field. A version conflict loads the latest saved snapshot for
review and requires an explicit choice to retain the draft against the new version or discard it.
Unmodified drafts can refresh after Provider sync, while successful saves reset the editor to the
saved snapshot. Draft equality compares JSON values, independent of property order.

Library applies complete manual replacement through one authorized Item CAS, search indexing,
audit and durable recommendation transaction. Provider sync reauthorizes and checks the version
after external I/O. Its merge preserves omitted fields and local credits, unions identifiers,
subjects, relations and files, and retains locally entered credit facts and manually chosen
Citation Keys. This policy belongs to Library, not the neutral conversion package.
When a Provider supplies a different primary ID, Library retains the previous primary URI as a
standard top-level identifier before adopting the new ID. Inquiro supplies its standard type and
lookup normalization. Repeated syncs retain that identity once; manual replacement remains complete.
Contributor merging compares shared entity IDs first, then full credit names when both are
supplied, before falling back to family/given parts. Thus suffix-distinguished people such as
John Smith Jr and John Smith Sr remain separate, and repeated unchanged syncs merge each one's
affiliations and roles without increasing author counts.
Matching display names also cannot override conflicting supplied family/given parts, so two
people credited as A. Smith remain distinct when their given names differ.
When the same entity matches separate role credits, merging prefers an identical role set, then
a credit containing all incoming roles. When neither exists, a unique credit sharing an incoming
role can receive upstream role extensions while preserving its local roles and affiliations.
An ambiguous contribution already represented by local facts is not appended again, so unchanged
syncs retain separate Author and Editor rows.

## Identifier comparison and suggestions

The persisted sources are `Work.id` and top-level `Work.identifiers`. No identifier table,
workspace uniqueness invariant or identifier reservation exists. Comparison supports Inquiro's
existing DOI, arXiv, PMID, PMCID, ISBN, OpenAlex, Bibcode and IEEE lookup parsers. Multiple
identifiers in a namespace and duplicate Items may coexist. OpenAlex identifiers use the
Commonmeta URL form, such as `https://openalex.org/W123`; short IDs remain query input only.
DOI comparison folds ASCII letters, preserving non-ASCII distinctions, without rewriting the
stored Work.
Malformed PMID/PMCID resolver strings do not contribute comparison keys and remain stored verbatim.
Resolver URI paths are percent-decoded once for comparison; plain DOI identifiers retain
literal percent sequences. BibTeX, RIS and CSL DOI fields use the raw comparison spelling,
separately from the encoded resolver URI. Temporary reader guards preserve non-ASCII case and
the existing parser's longer DOI prefixes through pinned upstream conversion. Provider-built
DOI Work IDs also percent-encode the resolver path while retaining raw source identifiers.

Library groups connected Items sharing comparison keys as suggestions. It examines authorized
Workspace Items only. Container identifiers (including book ISBN or journal ISSN), relations,
references, funders and contributor identifiers are excluded. Detection runs only for an explicit
Library duplicate request (up to 2,000 Items; similar-title matching up to 500). Discovery and
Import do not load stored Works or infer an `imported` state. PDF batches can still report repeated
DOIs within the bounded batch. PDF scanning preserves an existing manual DOI and
may add a DOI already used by another Item. Valid imports are never rejected for shared identity.

ImportBatch stages `{work, citation_key?, _source_id?}` and diagnostics. Valid records can be
confirmed even when other input records failed. Confirmation locks the batch, creates each Item
once, retains committed UUIDs for replay, and clears staged records/files. PDF workflows keep
stable source IDs, checkpoint replay, authorization rechecks and object cleanup.

Search indexes title, descriptions, Author/Editor names, subjects and only the Work's own
identifiers. Existing SQLite FTS5 and PostgreSQL tsvector projections remain rebuildable.
Filtering and distinct-Item facets query nested Work contributors/subjects directly over the
same authorized candidates. No targeted JSON index is added without query/performance evidence.
Exact author and keyword selection compares returned facet values verbatim, preserving
leading/trailing whitespace and repeated interior whitespace. An empty given name projects as
an absent first name in facets, suggestions and exact filtering; the stored Work stays intact.
The search projection includes the active contributor's credit name and supplied family/given
parts. Legacy NCBI URLs are interpreted by their resource path: `/pubmed/` identifies PubMed,
while `/pmc/articles/` identifies PMC; unrelated paths do not supply a comparison identifier.

A local SQLite probe on 2026-10-13 used 5,000 Works with an 8 KiB description each. Before removal,
a single-record bibliography preview loaded all 5,000 Works (about 40 MiB of descriptions) and took
41.9 ms; afterwards it performed no Item SELECT and took 7.0 ms (6.8 ms at 100 and 1,000 Items).
This is a development measurement, not a production latency guarantee. Separate three-run median
probes at 5,000 Items measured a 25-Item page at 21.5 ms, author suggestions at 25.8 ms, facets at
143.6 ms and explicit identifier duplicates at 67.0 ms. Exact facets and name suggestions still
scan matching JSON metadata inside the database; their output limits do not bound input work.
No identifier projection, cache invalidation system or speculative JSON index was introduced.
Evidence: `.cache/commonmeta-checks/metadata-perf-{before,after}.txt` and `metadata-scaling.txt`.
These probes cover SQLite only; PostgreSQL performance remains unmeasured in this session.

A Contributor's `type` selects its active Person or Organization for names, affiliations,
Citation Keys, Provider credit matching, search, facets and typeahead. Both entity snapshots can
remain in a valid Work after a type change, and persistence and Commonmeta export preserve them.
Other-format writers receive a temporary validated copy with the inactive entity removed because
the pinned upstream name writers otherwise prefer Person data regardless of `type`. That copy
never replaces the stored Work or the lossless export value.
For name-only people, the snapshot uses upstream name parsing to populate writer-facing
name parts; mononyms remain a single name. BibTeX/RIS also project given-name-only people into
their single-name slot. CSL retains a supplied given-only name as `given`. Library author
suggestions and facets expose a name without a family component once, with an absent first name,
and exact author filters use that same projection.

## Interchange support and measured limitations

| Direction | Supported scope and limitations |
| --- | --- |
| Commonmeta import/export | Each Work is validated and preserved, including nested funding, relations and multiple identifiers. Exports are arrays of Work snapshots, preserving duplicate Items. These arrays are not deduplicated entity registries. |
| BibTeX import | Multiple entries are split by upstream bibtexparser and individually converted by commonmeta-py. Upstream macro expressions expand per record so undefined or cyclic macros receive individual diagnostics without discarding valid siblings. Grammar events also diagnose malformed declarations that the tolerant parser would otherwise skip as implicit comments, preserving logical record numbers; explicit comments and strings inside fields remain excluded. Opaque Citation Keys become UUID URIs on temporary reader input; the original Citation Key is retained separately, and explicit DOI/URL fields still supply Work identity. Before Commonmeta serialization, original grouped text is normalized with the existing rich-text converter, preserving supported formatting, escaped printable symbols and inline math. Brace-aware contributor splitting preserves protected literal Organization names and Author/Editor roles, while upstream utilities handle person names. Original BibTeX name groups are parsed before text conversion; three-part `von Last, Jr, First` names retain structured parts and suffix facts in the full name for citation/export roundtrips. Custom/unsupported fields receive format-limit diagnostics. |
| RIS import | Multiple records and the standard TI/T1 title aliases are supported. Conflicting title aliases, continuation lines and values containing hyphens receive explicit errors: the pinned tokenizer truncates hyphenated values. Records with KW, A2 or ED are also rejected because the reader emits invalid subjects or loses editors. Other valid records in the batch remain importable. |
| CSL-JSON import | Validated with the upstream bundled CSL schema before conversion, with its contributor utility preserving separate editor roles. Explicit DOI takes priority over a local record key. Opaque and numeric local keys become UUID URIs on a temporary input; they are never inferred as bibliographic identifiers. Date ranges retain only shared year/month components; cross-year ranges omit the publication date. Magazine, newspaper and software input are rejected because the pinned mappings change their meaning. Malformed rows and upstream shape failures receive per-record diagnostics; valid siblings remain importable. |
| BibTeX/RIS export | Upstream writers own field mapping. BibTeX uses the upstream entry dictionary before serialization, then the existing rich-text converter to project HTML and escape TeX-special text, including unbalanced literal braces. Organization authors retain an inner literal-name group, preserving commas and `and`; Person credits retain their structured names. Unicode and inline math are retained. Editor-bearing Works and authors without usable names are rejected with a format error. Secondary identifiers and fields absent from those formats are not lossless; use Commonmeta. |
| CSL-JSON/citations | Upstream conversion and name utilities, then citeproc-py for custom/builtin styles. Author/Editor roles are projected separately because the upstream writer attributes all credits as authors. The writer's unsupported `copyright` property is omitted; Work/Commonmeta retains the complete license. Final projections must pass the upstream bundled CSL schema; unsupported Work types such as ProceedingsArticle produce a validation error instead of invalid CSL. Versioned Software receives an explicit format error because the pinned writer silently changes it into a book. CSL-JSON exports use the disambiguated Citation Keys as record IDs so Items sharing a Work ID remain independently addressable in CSL consumers. Rich text follows upstream CSL output. |

RIS projects display fields to single-line plaintext on temporary writer input, including
contributor names, Container values, Publisher names and subjects. DOI and URL values and the
stored Work remain unchanged.

Citation rendering copies CSL values through the existing restricted rich-text converter before
citeproc receives them. All display strings, including nested names, retain only `i`, `b`, `sup`
and `sub` without attributes for HTML, or become plaintext for text output. Script/style content
and active markup are removed at this boundary, while the Work and interchange snapshots remain
unchanged. This is Inquiro's rendering safety policy, not a temporary dependency workaround.

Export preferences operate on temporary writer projections. BibTeX supports safe Unicode text
or LaTeX character commands and optional title case protection. DOI/URL policies apply to
BibTeX, RIS, CSL-JSON and rendered CSL bibliographies. `omit_when_doi` checks the original Work's
valid DOI even when DOI output is omitted. Native field exclusions apply only to BibTeX and
CSL-JSON, case-insensitively, with required identity/type fields protected. Sorting supports
input order, Citation Key, first author, year and title; record/key pairs remain attached.
Rendered CSL follows the style's sorting, and Commonmeta always preserves the full Work.

BibLaTeX, EndNote Tagged, arbitrary `custom_fields`, journal abbreviation preferences and
custom-field/identifier export switches are removed.
The UI exposes only supported formats and options. Known CLI failures remain structured JSON
on stderr; lookup/search retain bounded transport, credentials, aliases and exit codes.

Crossref, DataCite and OpenAlex use commonmeta-py's readers directly with `no_network=True` over
explicitly fetched payloads. Crossref's optional link MIME field is supplied as absent when
missing. Other Providers assemble the standard Work at their source boundary and reuse upstream
name helpers. Empty Crossref license arrays are omitted before conversion, and authorless
Provider records omit the optional contributors property. Provider conversion cannot retain
arbitrary source-only fields. OpenAlex's reader
uses `best_oa_location` for PDF links and does not retain corresponding-author flags, raw
institution text or location access/version flags; lookup reports that limitation. We do not
maintain a second OpenAlex metadata shape or repair those fields in its adapter.

Provider choices expose each lookup's identifier namespace from the existing Inquiro catalog.
Metadata sources uses those configured capabilities to render sync actions, while unsupported
identifiers remain visible. Identifier display rows are deduplicated without modifying the Work;
repeated standard identifier rows remain valid storage and export values.
Authorized Item Overview responses include optional `primary_lookup_identifier` query context,
using the existing Inquiro lookup-key type. Library derives it from the primary Work URI when that
supported identity is absent from top-level identifiers, comparing both with Inquiro's rules.
Metadata sources combines this context with identifier rows and configured lookup choices.
Only the DOI already shown in the dedicated DOI panel is omitted from those rows, comparing
resolver and bare spellings with the DOI normalization rules above. Secondary DOIs remain
visible and selectable for sync.

Temporary reader normalization and semantic guards for the pinned conversion defects live in
Inquiro's private `_commonmeta_adapters.py`, outside Provider adapters and Library policy.
Compensation sites use `UPSTREAM(commonmeta-py 0.309)` comments describing the pinned defect.
These markers also cover existing role, name, license and source-input repairs. They distinguish
dependency workarounds from Library business rules and normal boundary validation; upgrading
commonmeta requires checking the marked regressions before removing their corresponding repairs.
[Independent upstream reproducers and a proposed patch](../upstream/commonmeta-py-0.309/README.md)
cover the identified RIS/CSL defects without importing either application package. The patch
is a review artifact and is not applied to the installed dependency. Each guard can be removed
when a tested dependency release preserves that behavior; no parallel format converter is maintained.

The POC and golden tests exercise multiple records, Unicode credits, organizations, affiliations,
rich titles, Preprint/Dataset types, editor roles, DOI-less Works, multiple IDs and hidden fields.
The pinned readers/writers are the reason for explicit restrictions rather than a parallel
conversion engine. commonmeta-py brings its upstream transitive dependencies, including its
publishing/PDF libraries; this installation cost is accepted for replacing local conversion.
`commonmeta-ts` currently supplies identifier utilities, without a Work editor/conversion API;
frontend therefore consumes the same backend schema and generated contract.

## Regeneration and alpha cutover

```sh
uv run python scripts/generate-commonmeta-models.py
bun run --cwd frontend api:generate
```

The generator selects only Work-reachable definitions from the installed official schema and
records no handwritten field schema. Commit generated Python/OpenAPI TypeScript output together
with dependency locks. Repeated generation must produce no content change.

The initial revision remains `cde8b41cfa2d`; the search revision still follows it as
`bd688512265a`. The initial schema creates `items.work` and no identifier table. Both migrations
apply to fresh SQLite/PostgreSQL and can roundtrip. A database initialized from the old version
of the initial revision must be rebuilt; applying the same revision IDs does not upgrade its
physical schema. No old durable checkpoints or flat metadata are accepted on this breaking branch.
