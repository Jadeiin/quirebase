# ADR 0007: obstore object-storage data plane

Status: accepted.

## Context

File Revisions, Attachments, thumbnails and annotation-export artifacts were coupled to local
filesystem paths. This prevented web and worker processes from sharing those objects through S3,
made HTTP Range delivery backend-specific, and exposed local I/O details across business Modules.

## Decision

Core owns one small `ObjectStore` facade backed by obstore `LocalStore` or `S3Store`. Its contract
covers byte, path and asynchronous-stream uploads; metadata; range reads; streaming reads;
deletion; prefix listing; and scoped local materialization. Business Modules depend on this
contract and object keys, never on obstore or backend paths.

Content-addressed objects remain SHA-256 keyed and immutable. Concurrent identical writes use
overwrite semantics: the backend publishes a completed object atomically, and identical bytes may
replace identical bytes. Quirebase does not use put-if-absent because that would inhibit multipart
uploads. Existing local leases remain solely as transitional cleanup coordination and are not
implemented as S3 object locks.

FastAPI streams obstore `GetResult`/`BytesStream` bodies directly. ZIP responses use stream-zip
with `ZIP_AUTO(known_size)` per member and an unbuffered asynchronous-generator bridge whose
cancellation explicitly closes the active source stream. PyMuPDF receives a direct local object
path for LocalStore and a scoped temporary download for S3Store.

## Consequences

- Web and workers can share revision, attachment, thumbnail and annotation-export objects through
  a common bucket and prefix.
- Backup/restore remains local-backend-only in this phase; the existing physical CAS key layout is
  unchanged.
- An external cutover must copy existing objects while preserving keys.
- A database-backed staged-object reservation is still required to make remote cleanup safe across
  process crashes and races. Presigned delivery and a shared policy for all generated artifacts
  remain later work.
