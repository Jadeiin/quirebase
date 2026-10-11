---
status: accepted
---

# Record-local bibliographic metadata

An Item's contributors describe that record's ordered credits; matching names do not establish
a shared researcher identity. Store author/editor snapshots and keyword/URL arrays on Item,
sharing Inquiro's Contributor/Affiliation/ResourceLink values and validated by `inquiro.metadata`
through ItemMetadata and protected by its version, instead of shared Author and
ItemAuthor rows or delimiter-encoded caches. Filtering and facets are separate query capabilities
over authorized Workspace/Project candidates; defer a rebuildable facet projection until measured
costs justify it, retaining relational Identifiers and Tags for their uniqueness and shared-resource
semantics. Institutions remain inside their credited Contributor; remove the top-level affiliation
field and duplicate Item identifier cache. Store DOI with other external identities in
ItemIdentifier, with Workspace uniqueness over canonical values, rather than a dedicated Item
column. CandidateRecord derives DOI from confirmed identifiers; BibliographyRecord retains the
explicit DOI field needed for format conversion. Library owns persistence and policy, while Inquiro owns
source conversion, validation, merge rules and bibliography projection. The [query contract](../architecture/item-metadata-json.md) defines matching and counting.
