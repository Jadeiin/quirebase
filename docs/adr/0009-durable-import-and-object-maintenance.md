---
status: accepted
---

# ADR 0009: durable Import preparation and object maintenance

## Context

PDF Import preparation performed PDF inspection and Provider calls inside an HTTP request. Item
deletion and Import Batch discard performed best-effort physical cleanup after their database
commit. Storage metrics issued one or more Object Store requests per stored record, while a worker
owned an uncheckpointed infinite maintenance loop.

## Decision

Library represents PDF Import preparation as a pending Import Batch owned by a DBOS workflow.
The request validates and stores each upload, then transactionally enqueues preparation. Retryable
steps separately extract DOI values and retrieve Candidate Records, while a datasource transaction
checks each DOI against accessible Items; Provider retries do not repeat PDF parsing. One datasource
transaction publishes the ready preview. A terminal preparation failure transactionally marks the
batch failed while retaining its staged objects. Cancellation, exhausted workflow recovery and a
missing workflow record are lazily reconciled to failed when the batch is viewed or retried; retry
transitions it back to pending under a new workflow identity. Lazy reconciliation updates only a
still-pending batch whose workflow identity matches the observed terminal execution, so a stale
request cannot overwrite a concurrent retry. The Import Batch and active workflow attributes reserve
staged object keys.

Documents owns an idempotent object-cleanup workflow on a dedicated non-partitioned queue. File
Revision workflows use revision partitions with bounded queue-wide and worker concurrency. Item
deletion and Import Batch discard enqueue cleanup in the same transaction as their logical deletion.
Library Search projection and Recommendation inference use separate queues so slow local inference
does not delay projection. Operations retains reconciliation as a correctness backstop: each
integrity scan lists the Object Store once, compares that inventory with database references, and
delegates reference and reservation protection to Documents, which rechecks each orphan key
immediately before physical deletion. Core owns reservation/cleanup-intent metadata; Library
provides retained PDF staging facts. Reservation reads precede staging-source and committed
Document-destination reads so finalization and confirmation transfers remain protected.

Storage metrics use SQL counts and recorded byte sizes. PDF Thumbnail size is recorded with its File
Revision. A persisted integrity-scan result supplies availability diagnostics; opening an admin page
never scans or issues per-object HEAD requests. Integrity I/O steps return proposed PDF Thumbnail
size backfills, which are committed together with the scan result in a datasource transaction.

DBOS Schedule runs Operations maintenance hourly on the serialized Operations queue. Workflow and
step checkpoints replace the worker-owned sleep loop. Active object reservations are queried by
active DBOS states, and global Search rebuilds and bulk Tag Recommendation requests use bounded
keyset datasource-transaction checkpoints. Successful annotation exports create lightweight
Annotation Export Artifact records containing their object identity, filename, size and expiration;
maintenance retires still-expired matching descriptors through Documents in bounded datasource
transactions. The returned object keys are checkpointed atomically with retirement before a
retryable Documents deletion step rechecks all remaining references. Recovery therefore retains
keys after descriptors disappear, without reading terminal DBOS history.
See [the object lifecycle interface contracts](../architecture/modules.md#object-lifecycle-interface-contracts).
Read-heavy datasource transactions use `READ COMMITTED` where the database supports it, while
business state transitions retain `SERIALIZABLE` isolation or explicit row locking.

## Consequences

- Provider latency and process interruption no longer hold open the PDF Import HTTP request.
- Logical deletion is atomic with durable cleanup intent; physical deletion remains idempotent and
  periodic reconciliation remains the terminal safety net.
- Metrics describe database-recorded logical storage immediately. Missing-object diagnostics are as
  fresh as the latest integrity scan and expose its timestamp.
- This decision supersedes ADR 0007's statement that a database-backed staged-object reservation is
  future work.
