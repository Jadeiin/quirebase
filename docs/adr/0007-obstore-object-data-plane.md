---
status: accepted
---

# ADR 0007: obstore object-storage data plane

## Context

File Revisions, Attachments, thumbnails and annotation-export artifacts were coupled to local
filesystem paths. This prevented web and worker processes from sharing those objects through S3,
made HTTP Range delivery backend-specific, and exposed local I/O details across business Modules.

## Decision

Core owns one small `ObjectStore` facade backed by obstore `LocalStore` or `S3Store`. Its contract
covers byte, path and asynchronous-stream uploads; metadata; range reads; streaming reads;
deletion; prefix listing; and scoped local materialization. Business Modules depend on this
contract and object keys, never on obstore or backend paths.

Every logical upload owns an immutable UUID object key, following
[ADR 0008](0008-dbos-workflows-and-owned-uuid-objects.md). The backend publishes a completed
object atomically. Quirebase uses overwrite semantics for idempotent retries of the same upload,
which also permits multipart uploads.

FastAPI streams obstore `GetResult`/`BytesStream` bodies directly. ZIP responses use stream-zip
with `ZIP_AUTO(known_size)` per member and an unbuffered asynchronous-generator bridge whose
cancellation explicitly closes the active source stream. PyMuPDF receives a direct local object
path for LocalStore and a scoped temporary download for S3Store.

## Consequences

- Web and workers can share revision, attachment, thumbnail and annotation-export objects through
  a common bucket and prefix.
- Backup/restore supports local object storage; S3 deployments use an independent bucket backup policy.
- Authorized S3 PDF/export downloads can use short-lived native signatures; local delivery streams.
- [Object lifecycle contracts](../architecture/object-lifecycle.md) define workflow reservations,
  reference checks and physical deletion. [Deployment](../DEPLOYMENT.md#object-storage) covers
  backend configuration and signed-delivery requirements.
