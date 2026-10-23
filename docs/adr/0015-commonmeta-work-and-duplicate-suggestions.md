---
status: accepted
---

# Commonmeta Work and duplicate suggestions

An Item's UUID identifies its Workspace record; bibliographic identifiers describe the research
output and cannot safely claim a unique Item. Persist the official Commonmeta v1.0 Work in
`Item.work`, with `id` and `identifiers` as its bibliographic identifier source. Commonmeta owns
the bibliographic schema and type vocabulary.

Library suggests duplicates when authorized Workspace Items share exact Work identifier values.
Multiple identifiers of one kind and multiple Items with the same identifier are allowed.
Container, contributor and related-resource identifiers never establish Item matches. Duplicate
detection runs only when explicitly requested; Discovery and Import never scan stored Works for automatic warnings or an inferred “already imported” state. Identifier
collisions cannot reject creation or instruct an automatic merge.
Per-Item version checks and confirmation replay while the ImportBatch receipt exists remain
application invariants.

Inquiro owns the external Work contract, generated Python types, reader/writer integration,
identifier comparison normalization and bounded Provider I/O. Library owns Item requirements,
merging, authorization, persistence, search coordination and durable import recovery. Frontend
uses generated OpenAPI types and the locked official schema supplied by Library, preserving
fields outside the visible editor controls.

Interchange support is bounded by the pinned upstream conversion's ability to preserve semantics.
The [contract and support matrix](../architecture/item-metadata-json.md) records those limits,
identifier grouping rules and regeneration commands.
