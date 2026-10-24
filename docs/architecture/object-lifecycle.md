# Object lifecycle and durable cleanup

Core supplies object transport and workflow infrastructure. Documents owns persisted file
references and physical deletion; Library owns PDF Import staging; Operations owns scheduling,
inventory and reporting. [ADR 0008](../adr/0008-dbos-workflows-and-owned-uuid-objects.md) explains
UUID ownership and [ADR 0009](../adr/0009-durable-import-and-object-maintenance.md) explains durable
preparation and maintenance.

## Upload and processing

Each logical upload owns a preallocated UUID object key. SHA-256 is computed during streaming and
stored in its FileObject descriptor for content comparison. Equal uploads have independent keys.
The workflow-first protocol creates a DBOS execution, streams the object and sends a durable
completion message. A short datasource transaction persists a pending File Revision from the
completed upload receipt.

Ordinary and imported PDFs share a retryable inspection step. Object I/O, extracted text and page
geometry stay outside checkpoints and open database transactions. Finalization checks the Revision
and current attempt, publishes ready state and revision Search, and enqueues `FileRevisionChanged`
atomically. Ready retries return identities; a missing Revision is rejected. Failed processing
retains the source for a `file.manage` retry with a new attempt. Documents owns the change event;
a Library workflow consumes it to update derived Library state.

Revision work uses revision partitions with bounded global/worker concurrency. Object cleanup has
a separate non-partitioned queue; Recommendation inference has its own queue. Search projection
updates accompany their canonical write transaction.

## PDF Import staging

An Import Batch persists staged FileObject descriptors with stable source UUIDs. Candidates refer
to source UUIDs, while durable preparation receives serializable receipt snapshots. Separate
steps extract a lookup identifier per file. Each Provider-group lookup step rechecks actor/Workspace
eligibility and loads settings, ends its read transaction, then retrieves Candidate Records through
`lookup_many`. Only outcomes enter its checkpoint. arXiv/PubMed use native request merging;
Crossref/OpenAlex retain singleton endpoints inside the shared runtime. At most 50 PDFs enter a batch.
PDF lookup accepts an arXiv ID only from an `arXiv:` watermark rotated upward in the first page's
left margin (within the leftmost 10%, capped at 72 points), including legacy IDs and version suffixes.
That watermark takes precedence over DOI metadata. Otherwise lookup uses explicit XMP DOI fields
(`prism:doi`, `pdfx:doi`/`DOI`, or `dc:identifier`), then first-page publisher update/citation links
(Crossmark, MDPI check-update or `action/showCitFormats`), then PDF Info Title/Subject values that
consist entirely of a DOI, optionally with a DOI resolver or `doi:`/`urn:doi:` prefix. As a final
fallback, first-page printed `Digital Object Identifier` or `DOI:` labels and `Cite this:`
self-citations identify the article. Printed labels normalize typographic ligatures; a self-citation
must contain its DOI in the same text block. Reference sections and everything after them are
excluded from this fallback.
Conflicting identifiers at the first available evidence tier leave the PDF unidentified; lower
tiers cannot resolve that ambiguity. Body text, reference lists, keywords, ordinary DOI resolver
links and generic `lookup/doi` links are not identity evidence, even on the first page. No later
pages are scanned for lookup. Without an unambiguous identifier, the PDF follows the ordinary
basic-candidate path.
Library selects the identifier and routes through Inquiro; Documents supplies embedded metadata,
first-page links and text layout without selecting scholarly identifiers.
Lookup inputs remain private Import Batch query context, separate from the Provider-returned
identifiers in Work metadata. Repeated normalized lookup identifiers within one batch produce a
warning while retaining both PDFs, including basic candidates with deferred metadata. Finalization
rebuilds these warnings from the complete merged batch in source order, so partial retries compare
refreshed candidates with retained siblings without accumulating warnings.
One final transaction publishes the ready preview for the matching workflow generation.

Valid PDFs with no recognized identifier or no matching Provider metadata remain staged as optional
basic candidates. Their Work uses a local UUID URN, `Document` type and an escaped filename stem
as its title, without inferred authors, dates or upstream identifiers. Preview exposes the stable
source UUID and marks these candidates as basic; no Item exists before confirmation. Diagnostics
for staged PDFs carry the same source UUID; filenames and row numbers are display context.
Users explicitly select basic source UUIDs in the confirmation request. Identified candidates are
included normally, while unselected basic PDFs are skipped. Unknown source UUIDs are rejected, and
a selection with no candidates cannot be committed. A batch containing only basic candidates is
ready for review. Unreadable PDFs remain file errors. Transient Provider failures are checkpointed
with a basic candidate, a per-file diagnostic and retry information rather than escaping as a step
exception. Library attempts metadata retrieval at most three times per file, with `DBOS.sleep_async`
between attempts. `Retry-After` accepts delta-seconds or an HTTP-date; absent or invalid hints use
5- and 10-second exponential delays. A group waits for the largest delay required by its failed inputs,
then submits only unavailable sources. Successful outcomes from earlier attempts are retained by
source UUID. Eligibility is rechecked before each attempt. Completed extraction and group lookup
steps, including failed Provider outcomes and sleep deadlines, replay during recovery. A process
failure before a group step checkpoints may repeat that group's requests; completed group steps do
not repeat successful siblings during recovery or backoff.

One preparation has a 60-second total wait budget. If a group's required retry wait exceeds the
remaining budget, its unavailable sources are deferred without another request; other Provider
groups can still execute. Delays are never shortened to fit the budget. This is per-workflow backoff,
not coordination of credentials across workers. Exhausted or deferred lookups produce warning codes
`provider_rate_limited` or `provider_unavailable`, retain their PDF as an optional basic candidate
and preserve the lookup value in batch query and diagnostic context, outside Work metadata.
These failures do not mark the whole batch failed or become `metadata_not_found`.

A ready PDF batch with these warnings may use the existing retry command. It selects deferred
sources by diagnostic source UUID and reuses their persisted lookup context without re-reading
the PDF. It retains successful candidates, their source UUIDs and all staging. Finalization
merges retained and refreshed candidates in original file order under the batch/workflow guard.
Concurrent confirmation and retry serialize on the batch root; stale failure publication uses a
conditional update so it cannot overwrite a newer retry. PDF previews expose an opaque
`preview_version` to all authorized readers, independently of actor-only workflow visibility.
Each retry changes that preparation generation. Confirmation supplies the reviewed version as
`expected_preview_version`; the locked batch rejects missing or superseded versions before mutation,
even after retry finalization returns the batch to ready. The UI offers Retry metadata alongside
confirmation; optional basic candidates may also be explicitly imported while metadata is unavailable.
After Import, ordinary Metadata editing and identifier-based updates can
complete the Item without an additional Item lifecycle state.

Terminal failure retains staging for retry. A pending batch whose workflow is terminal or missing
converges to failed when read or retried, provided its workflow identity still matches. Retry
assigns a new workflow identity. Individual file diagnostics allow valid sibling records to proceed.
Confirmation locks the batch, creates Items and transfers accepted PDFs to File Revisions atomically,
then clears staging and transactionally enqueues cleanup for skipped PDFs. Discard and expiration
release both identified and basic staging through the existing cleanup flow. Committed receipts
retain Item IDs for replay; later confirmations return that receipt regardless of a changed selection
or obsolete preview version.
Identifier and within-batch warning rules follow the
[Work contract](item-metadata-json.md#identifier-comparison-and-suggestions).

## Reference protection

`documents.objects` owns descriptor references, reservation checks, expiration retirement and
idempotent physical deletion. Library's `import_staging_object_keys` reports pending, ready and
failed retained PDF batches; committed receipts reserve no staging. Core's reservation encoder
separates active ownership from cleanup intent and supports excluding the current cleanup workflow.

Protection reads occur in this order:

1. Active workflow reservations.
2. Library staging sources.
3. Committed Document destinations, including export artifacts.

That order preserves protection while a workflow finishes or confirmation transfers ownership.
Operations lists the Object Store once for reconciliation and asks Documents for protection at
discovery and immediately before deletion. Only old managed UUID keys are eligible; unknown keys
and doctor probes remain outside reconciliation.

## Object lifecycle interface contracts

`delete_item_documents` runs under the caller's authorized exclusive Item locks in stable order.
It locks ProjectItem rows before their Annotations, matching Reply writes, and collects Revision,
Thumbnail and Attachment keys. Annotation locks fence Reply insertion; foreign keys cascade
Document deletion through Annotations and Replies. It returns keys without object I/O or transaction
completion. Library retains Item deletion, Search removal, Audit, cleanup enqueue and commit.
Annotation Export Artifacts expire independently.

`prepare_item_document_copy` snapshots source descriptors in the caller's read transaction and
returns an `ItemDocumentCopy`. Library ends that transaction before `copy_objects`, then reauthorizes
both Workspaces and locks the source Item before `install`. Installation locks and compares all
source descriptors, creates independent Revisions/Attachments and updates revision Search inside
the caller's transaction. Library owns Item Work, Item Search, Audit and commit. On failure it rolls
back before `discard`, which rechecks committed references before deleting copied objects.

`protected_object_keys` and `delete_unreferenced_objects` require a Session without pending writes.
They end their read transactions with rollback so final checks read fresh facts. Protection includes
Revisions, Thumbnails, Attachments, export artifacts, staging and active reservations. Full scans
avoid inventory-sized SQL parameter lists. Absent objects count as successful deletion. The upload
protocol reserves before writing and gives every new upload a fresh key; new work cannot adopt old
unreferenced keys between these checks and physical deletion.

`list_expired_export_artifacts` returns bounded expiration-ordered receipts.
`retire_expired_export_artifacts` rechecks identity, key and expiry and returns keys for checkpointing
with descriptor retirement. Both use the caller's datasource transaction. A later retryable deletion
step rechecks all references, protecting renewed or replaced descriptors.

`snapshot_workspace_documents`, Library's staging snapshot and Search's `remove_workspace` use the
caller transaction under an exclusive Workspace root lock. Workspaces retains authorization,
archive checks, root deletion, Audit and bounded cleanup enqueue through commit. Search removes
both projections before the cascade, including SQLite FTS rows. Cleanup intent carries its own
authority from the deletion transaction and does not reserve deleted keys.

## Maintenance and retained state

Storage metrics aggregate recorded counts and sizes. Opening administration does not issue
per-object requests. The scheduled integrity step scans, deletes, rechecks and backfills Thumbnail
sizes without checkpointing inventory. Its output contains small counters. `MaintenanceSnapshot`
retains the latest integrity and cleanup results, exact error totals and at most 100 samples;
separate start timestamps prevent stale concurrent results from replacing newer runs.

Hourly maintenance invokes bounded owner-provided purge operations in short transactions.
Library's Import expiration predicate protects active or unconfirmed durable preparations; an
Operations keyset cursor prevents protected old records from starving later eligible records.
[Deployment](../DEPLOYMENT.md#retained-data) defines retention settings and user-visible effects.

Core's `workflow_storage` is the SDK-table retention adapter. Terminal history retires parent before
child, preserving native parent and operation-output dependencies while a parent exists. Status,
system checkpoints and datasource outputs retire atomically; every cycle also sweeps orphan
datasource receipts. Retired workflow IDs cannot be resumed or reused. Cancellation alone does not
establish quiescence. Business content, artifact download authority and object cleanup use domain
descriptors and durable cleanup intent independently of terminal history.

Global Search rebuilds and bulk Recommendation requests use bounded keyset checkpoints. Workspace
rebuilds additionally reauthorize `workspace_maintenance.run` for every Item/Revision batch.
