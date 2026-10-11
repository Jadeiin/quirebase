# Item metadata and queries

Item owns ordered `authors` and `editors` snapshots, structured resource `urls`, and individual
string `keywords`. All four use AA JsonB (JSONB on PostgreSQL, JSON on SQLite) and default to
empty arrays. Contributor, Affiliation, Identifier, ResourceLink, CustomField and the complete
BibliographicMetadata value are defined once in `inquiro.models`; Library exposes that metadata
value as `ItemMetadata`. Provider records and stored snapshots reuse the same nested value types.
There is no global Author ID, Contributor position column, Item affiliation text or Item-level
institution list. Institutions belong only to the author/editor credited with them.

Contributor snapshots retain `display_name`, optional `family_name` / `given_name`, `suffix`,
`kind`, namespaced identifiers, record-local affiliations and nullable `is_corresponding`.
Organization credits use their literal display name. Suffixes stay separate until the two-part
bibliography formatting projection. Resource links retain `url`, `kind`, `media_type`, `version`,
`license`, nullable `is_open_access` and `intended_application`. Manual link normalization combines
repeated URLs in order; URL paths are case-sensitive. Keywords never use delimiter encoding.
Contributor name validation normalizes the display name, family/given parts and suffix before
deriving duplicate keys and writing snapshots; blank optional name parts become null.
It rejects casefold-equivalent duplicate bibliographic names within one role, including suffixes;
it does not create researcher identities.
Only authors may be corresponding contributors. JSON credits have no former Author-column length
or casefold-index limit.

`inquiro.metadata` owns source conversion, bibliographic validation, snapshot decoding, merge
rules and bibliography projection. It accepts neutral values and mappings, never application,
ORM or authorization objects. Default Citation Key generation belongs to `inquiro.bibliography`.
`library._metadata` maps ORM fields onto that interface, applies Library's field limits and
translates validation errors. Library retains Workspace permissions, Identifier claims, version
CAS, transaction ownership, Audit Events and synchronization of Search projections.

All external Item identities, including DOI, are stored only in `ItemIdentifier`, with one
namespace per Item and unique `(workspace_id, provider, value)` claims. DOI values strip resolver
prefixes and fold only ASCII A–Z; non-ASCII characters remain distinct. ISBN identities use
Inquiro's parser to remove prefixes, hyphens and spaces and uppercase the `X` checksum character.
Metadata writes and Discovery candidate comparisons use the same namespace normalization.
Provider CandidateRecord
stores DOI only in `identifiers` and exposes a read-only `doi` property. Lookup keys are never
injected as confirmed identities. BibliographyRecord retains its explicit DOI formatting field.
Metadata/API DOI inputs are unified with identifiers and conflicting values are rejected.
Cross-Workspace copies reject claims already assigned in the target Workspace; Import previews
check existing DOI claims, and database uniqueness resolves concurrent claims. Item has no duplicate
serialized identifiers cache. Contributor and institution identifiers describe those credits;
they do not claim Item identities. Metadata reads, citation exports, discovery imported checks
and Search read the relation explicitly, avoiding implicit asynchronous ORM loading. Search
reloads identifier associations when indexing a changed Item so a previously loaded collection
cannot leave removed identifiers searchable.

Commands replace entire JSON arrays rather than mutating nested dictionaries. Contributor and
link changes participate in the same version CAS, transaction, Search update and Audit Event as
the rest of the metadata. Provider/import merges leave omitted/null contributor lists unchanged
and replace explicit lists including empty lists. For matching credits, unspecified name parts,
corresponding status, identifiers, kind and affiliations retain known values; an explicit boolean
overrides the status and an empty affiliation list clears institutions. A missing suffix inherits
a known suffix only when the name matches a unique credit in that role; ambiguous same-name suffixes do not
inherit another credit's attributes. New unknown corresponding status remains null. Link merges
retain known attributes when a source omits them, including preserving false versus unknown open
access. Keyword/link merges retain order and append distinct values. Manual full replacement
clears omitted arrays and does not inherit previous credit attributes. Cross-Workspace copies
deep-copy the JSON snapshots and revalidate all Item fields plus its version before installation.

Display-only credits with unknown kind and name parts may inherit a unique normalized display-name
match, including organization credits; ambiguous display names never inherit another credit's
attributes. Independently supplied suffixes participate in the bibliography name projection and
duplicate validation even when family/given parts are absent.

The editor presents contributor institutions/identifiers and structured link attributes directly.
DOI is edited and displayed with the other upstream identifiers. Editor drafts and writes carry
only the identifier list, avoiding a second cached DOI value when editing or removing that row.
Keywords are individual rows, so semicolons remain part of a term. Custom fields use an explicit
text/JSON value type; strings such as `123`, `true` and `null` stay strings when saved unchanged.
Institution summaries are derived from credited contributors, with no second persisted list.

`LibraryFilter` describes full-text, Tag, Project, year, file-presence, Reference Type and
contributor/keyword conditions. Search, `/items/facets` and suggestions begin with
`workspace_items_query(context)`. Project conditions first authorize discoverability and then
narrow candidate IDs to the Project working set. No facet or suggestion grants access.

`author` and `keyword` match case-insensitive substrings over individual JSON elements; LIKE
wildcards are escaped. Database case conversion is not a portable Unicode researcher-identity
rule. Exact filters are case-sensitive: `keyword_exact`, `author_last_name`, optional
`author_first_name` and `author_suffix`. Missing family names use the literal display name for
queries. Omitted given-name/suffix conditions match any value; empty conditions match absent
values. Substring and exact author conditions are combined in one correlated `EXISTS` and must
match the same contributor element. PostgreSQL uses ORM JSONB
containment prefilters and correlated element checks for nullable/literal names; SQLite uses
correlated JSON expansion. Queries never compare JSON serialization as bibliographic text.

Facets group by the stored family/display name, given name and suffix, complete keyword or
Reference Type and count distinct candidate Item IDs. Each facet sorts by descending count with
deterministic value ties and its own limit (default 50, HTTP maximum 200). Repeated terms count an
Item only once per group. An Item can contribute to several author/keyword groups, whose counts
may sum above the candidate count. Empty arrays produce no contributor/keyword group. Suggestions
return names, suffixes and display text without identity IDs. Case and Unicode variants remain
distinct facet keys; future normalized query keys require an explicit domain rule.

`library._json_queries` builds SQLAlchemy JSON expressions and table-valued functions:
PostgreSQL `jsonb_array_elements[_text]` with LATERAL and SQLite `json_each`. Search owns its
rebuildable full-text projections. `(workspace_id, reference_type)` has a B-tree index. Further GIN
indexes and a facet projection remain deferred: containment indexing does not remove the cost of
expanding and grouping arrays.

The alpha cutover regenerates the initial migration from ORM metadata and retains only that
revision and the existing dialect-specific Search revision, whose parent references the generated
revision. Existing released-data upgrade compatibility is outside this cutover.

## Query measurement

On 2026-10-11, a local ORM-generated dataset contained 10,000 visible Items plus 1,000 Items in
another Workspace. Each visible Item had three contributors, four keyword entries including one
duplicate, one structured URL and alternating journal-article/book types. Credits included
personal identifiers, institution identifiers and organization names. A Project selected 1,000 Items.
Measurements used Python 3.14.5, SQLite 3.50.4 and PostgreSQL 17.10 with ANALYZE, one warm-up and
the median of three calls returning all three facets (limit 50), including authorization. These
are local smoke measurements with no concurrent test or build load; production capacity requires
representative data and workloads.

| Candidate filter | Items | SQLite ms | PostgreSQL ms |
| --- | ---: | ---: | ---: |
| Workspace | 10,000 | 113.05 | 53.99 |
| Journal-article Reference Type | 5,000 | 63.75 | 25.70 |
| Project and year | 166 | 7.67 | 4.80 |
| Exact author name parts | 10 | 86.66 | 15.78 |
| Author substring | 110 | 340.56 | 77.01 |
| Exact common keyword | 10,000 | 127.57 | 58.91 |

EXPLAIN QUERY PLAN showed SQLite using Workspace and Workspace/Reference Type indexes, correlated
JSON scans for element filters, and temporary B-trees for distinct counts and grouping. PostgreSQL
EXPLAIN ANALYZE showed array Function Scans, aggregation/sorts and Memoize for repeated arrays;
the Reference Type case used the composite B-tree, while Project/year used Item/ProjectItem
indexes. Broad Workspace and common-keyword cases selected sequential scans at this dataset's
selectivity. Array scans, particularly SQLite substring queries, remain measurable. These smoke
results do not establish a need for a facet projection or universal GIN indexes; a larger library
or frequent substring autocomplete warrants another measurement with its target latency budget.
