# Item Work, identifiers and queries

`Item.work` stores a Commonmeta v1.0 Work JSON object. `commonmeta-schema==1.0.1` is the schema
source; `commonmeta-py==0.309` is the conversion implementation. The Work is validated as the
schema's Work definition, rather than its broader entity root. Python models are generated with
`datamodel-code-generator==0.86.0`; strict fields, enums, nested variants, extra-property rejection
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
`@sjsf/form` 3.9.1 with its Skeleton 5 theme to edit a deep copy of the complete Work. Changing
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
primary controls and Identifier/Funding panels; nested scalar fields use intrinsic Grid tracks based
on their available width, without nested size containment. Titles, descriptions and complex object
fields span their section, while repeated entries can appear side by side when space permits.
Narrow layouts use one column without horizontal overflow. Section summaries supply the group title
once, and action buttons
retain a compact width. Nested objects and arrays (including contributor affiliations) default to
collapsed. Section controls mount on first expansion and remain mounted after closing; hidden
optional controls are not mounted. The complete Work lives in the form state independently
of these controls, so untouched sections remain available for validation, JSON editing and saving.
Active Person and Organization name fields remain visible; inactive entity facts stay available
in a collapsed section.
Optional empty controls are hidden by default. Each object offers an Add field selector that reveals
one official-schema property and focuses its control; Show all fields exposes all optional controls.
Previously populated or explicitly revealed controls remain visible when cleared. Array controls
remap this state and pending expansion requests on moves, removal and copying, including nested
entries; deleted entries cannot transfer their field state to later additions. These presentation
choices never add, prune or sanitize Work values, and schema validation still checks the complete draft.
Section summaries show entry counts and a short content preview, while nested lists use separators
instead of additional card borders. Field errors reveal hidden fields and open all collapsed
ancestors; expanded state survives language changes. Overview shares the editor’s enum translations,
deduplicates affiliation names only for display and includes Container details. PDF URL input uses a
Skeleton Combobox with
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
When both given and family names are supplied, the same complete name can also match different
splits of a compound surname, such as Hossein / Bonyan Khamseh and Hossein Bonyan / Khamseh.
This exact comparison never overrides conflicting entity IDs or supplied full names. Matching
credits retain the local given/family split while adding Provider identifiers, affiliations and roles.
When the same entity matches separate role credits, merging prefers an identical role set, then
a credit containing all incoming roles. When neither exists, a unique credit sharing an incoming
role can receive upstream role extensions while preserving its local roles and affiliations.
An ambiguous contribution already represented by local facts is not appended again, so unchanged
syncs retain separate Author and Editor rows.

## Identifier comparison and suggestions

The persisted sources are `Work.id` and top-level `Work.identifiers`. No identifier table,
workspace uniqueness invariant or identifier reservation exists. Lookup comparison supports Inquiro's
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

Duplicate suggestions use exact stored values, independently of lookup normalization. SQL groups
equal primary `Work.id` values, or equal top-level identifier type/value pairs; `Other` identifiers
also require the same nonempty scheme. Primary IDs and additional identifiers are separate keys.
Empty or whitespace-only keys are ignored; values otherwise preserve case, whitespace and URI
spelling. A key must occur on at least two different Items. Groups do not connect transitively
across different keys, and identical groups are shown once. Only authorized Workspace Items are
examined. Container identifiers (including book ISBN or journal ISSN), relations, references,
funders and contributor identifiers are excluded. Detection runs only for an explicit Library
duplicate request across the authorized Workspace. Discovery and
Import do not load stored Works or infer an `imported` state. PDF batches can still report repeated
DOIs within the bounded batch. PDF scanning preserves an existing manual DOI and
may add a DOI already used by another Item. Valid imports are never rejected for shared identity.

Exact-title mode groups equal stored Work titles with the same case-sensitive comparison.
Same-PDF mode groups equal `FileRevision.file.checksum` values across distinct Items, considering
only ready PDF revisions; Attachments and thumbnails are excluded. Upload, import and copy streams
compute SHA-256 once and persist `sha256:<lowercase hex>` in the existing FileObject JSON.
Scanning performs database reads only and does not download or backfill historical files.
Its scanned count is the number of distinct Items with an eligible PDF checksum; other modes
count all Items in the authorized Workspace. File paths and physical ownership remain UUID-based.

ImportBatch stages `{work, citation_key?, _source_id?}` and diagnostics. Valid records can be
confirmed even when other input records failed. Confirmation locks the batch, creates each Item
once, retains committed UUIDs for replay, and clears staged records/files. PDF workflows keep
stable source IDs, checkpoint replay, authorization rechecks and object cleanup.

Search indexes title, descriptions, Author/Editor names, subjects and only the Work's own
identifiers. Existing SQLite FTS5 and PostgreSQL tsvector projections remain rebuildable.
Filtering and distinct-Item facets query nested Work contributors/subjects directly over the
same authorized scope. Facets use Library's filters, ordering and Item-page bounds before expanding
contributors/subjects, and return all candidates and distinct-Item counts on that page. No targeted
JSON index is added without query/performance evidence.
Exact author and keyword selection compares returned facet values verbatim, preserving
leading/trailing whitespace and repeated interior whitespace. An empty given name projects as
an absent first name in facets, suggestions and exact filtering; the stored Work stays intact.
Author display names prefer the active entity's credited name, falling back to given then family
parts when it is blank. Display parts are trimmed without changing exact-filter values. A grouped
family/given pair retains its credited name only when all matching credits agree; otherwise it uses
the structured fallback rather than attributing one credit's name variant to the whole group.
The search projection includes the active contributor's credit name and supplied family/given
parts. Legacy NCBI URLs are interpreted by their resource path: `/pubmed/` identifies PubMed,
while `/pmc/articles/` identifies PMC; unrelated paths do not supply a comparison identifier.

Bibliography preview formats the supplied Work without querying stored Items. Exact facets and
name suggestions scan matching JSON metadata inside the database; their output limits do not bound
input work.

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

Before conversion, a nonempty OpenAlex `raw_author_name` supplies the work's credited name;
the resolved author profile's `display_name` is only a fallback. ORCID and institution mapping
remain supplied by the upstream reader. This keeps profile-name variants from changing the
published author list during Import or Provider sync.

Provider choices expose each lookup's accepted identifier namespaces from the existing Inquiro
catalog, including DOI lookup through OpenAlex as well as its own Work IDs.
Item Overview contains the Work snapshot without separate DOI or primary-identifier projections.
Overview and Metadata display identifiers directly from Work.id and top-level Work.identifiers,
preserving source strings and keeping container, contributor and related-resource IDs separate.

Metadata sources loads `/items/{item_id}/metadata/sources` only when its action panel opens.
Library authorizes the Item and builds one transient source list from the current Work using
Inquiro's identifier recognition and comparison rules, including supported primary URI forms.
Each source supplies its namespace, normalized lookup value and configured Providers (for example,
an OpenAlex URL becomes `W123`). Unrecognized or unsupported identifier rows retain their source
values with no sync action. Equivalent identifiers are collapsed without modifying the stored
Work, while distinct secondary DOIs remain selectable. The preferred DOI appears first, using
Inquiro's existing selection rule.
The response carries the Item version from the same snapshot, which the sync command uses for
its expected-version check. Opening sources performs no upstream I/O and does not record an Item
read. Its client query uses a stable Item-scoped key and is invalidated once with the Item after
edits, sync and conflicts; a refreshed Overview version does not trigger another sources request.
Provider matching and DOI comparison are not reimplemented in the browser.

Item detail responses expose `id`, `version`, `metadata` and `citation_key`. Overview extends
that same shape with authorization, counts, Tags, thumbnail, copy targets and `latest_revision_id`.
Title, contributors, publication date, publication title, identifiers and description are read
directly from the single Work snapshot. The Metadata page reuses the Overview query so its draft
and expected version come from the same response. Library list responses retain their lightweight
`ItemSearchView` without embedding complete Works.

Item bibliographic links open the current Workspace Library with one exact filter: contributor
name parts, publication year, `publication_title`, `reference_type`, Tag UUID or `keyword_exact`.
Tag filters accept only UUIDs; Tag names are create/edit values and never alternative identifiers.
Publication titles compare the complete `container.title` string; they do not merge journal
identities or aliases. Author links use the existing Author-role name projection, including an
explicit empty given-name parameter for single-field or organization names. Library URLs retain
these exact values through search and pagination and expose removable applied-filter chips.

Duplicate checks require an explicit `identifier` or `title` mode and scan the entire authorized
Workspace. Both use SQLAlchemy `GROUP BY`/`HAVING` and join matching keys to load only matching
Items in one streamed statement. Titles compare the stored Work string exactly, including
formatting, case and punctuation, with SQLite `BINARY` or PostgreSQL `C` collation; missing or
whitespace-only titles are not candidates. Identifier arrays use the existing JSON dialect
expressions and SQL `UNION` to exclude repeated keys within a single Item. No normalized column,
database function, fuzzy matcher, worker thread or application-side connected-component algorithm
is required. Results include `groups` and the `scanned` count. Every path rechecks Workspace
access after detection, including empty results.
Opening Tools or changing match criteria never starts a check.

Organize responses contain authorization, Projects and one Tag matrix. Assigned Tag display is
derived from the complete matrix groups and `assigned_ids`; group names and separate suggestion
category arrays are not repeated in the HTTP response.

Temporary reader normalization and semantic guards for the pinned conversion defects live in
Inquiro's private `_commonmeta_adapters.py`, outside Provider adapters and Library policy.
Compensation sites use `UPSTREAM(commonmeta-py 0.309)` comments describing the pinned defect.
These markers also cover existing role, name, license and source-input repairs. They distinguish
dependency workarounds from Library business rules and normal boundary validation; upgrading
commonmeta requires checking the marked regressions before removing their corresponding repairs.
The 0.311 release still fails the standalone conversion regressions and drops distinct DataCite
contributor roles sharing one ORCID, so conversion remains pinned to 0.309.
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

The alpha initial revision is regenerated from current metadata, with the dialect-specific search
revision following it. The initial schema creates `items.work` and no identifier table. Both
migrations apply to fresh SQLite/PostgreSQL and can roundtrip. Databases stamped by the earlier
alpha chain must be rebuilt; no compatibility data conversion, old durable checkpoints or flat
metadata readers are provided.
