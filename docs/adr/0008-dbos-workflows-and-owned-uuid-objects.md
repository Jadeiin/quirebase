# ADR 0008: DBOS workflows and owned UUID objects

Status: accepted. Supersedes the Job/Pipeline and FileLock decisions in ADR 0002 and ADR 0006,
and the SHA-addressed object layout and reservation requirement in ADR 0007.

Quirebase uses DBOS 2.x for durable execution. Web is a DBOS Client and a separately invoked
`quirebase worker` process owns workflow execution. Workflow definitions live with the Documents,
Library, or Operations capability whose behaviour they implement; Core exposes only the durable
operation interface and DBOS Adapter. DBOS system tables share the physical application database
but are infrastructure state, not Quirebase domain models.

Every logical upload owns a preallocated UUID object identity. Its key is the lowercase,
hyphenless UUID split into two directory shards (`ab/cd/<uuid>.<suffix>`), with the suffix selected
from a closed set. Object-store transport and size checks provide upload integrity; Quirebase does
not persist content digests. Because equal uploads never share an object, a failed workflow can
delete the object it owns without reservations or file locks. Object type,
owner, references, and lifecycle remain in database and workflow metadata rather than key prefixes.

The upload protocol is workflow-first: create the workflow, write its preallocated object, then
send a durable completion message. External I/O occurs in retryable idempotent steps and database
changes occur in short transactions. Recovery uses stable executor IDs; terminal orphan cleanup is
owned by Operations reconciliation. Legacy 64-hex CAS objects are migrated offline and no CAS read
compatibility path remains after cutover.
