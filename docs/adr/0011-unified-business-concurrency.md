# ADR 0011: unified concurrency controls for business writes

Status: accepted.

## Context

Quirebase accepts writes through Web, API and MCP adapters while DBOS workflows can finish after
the request that started them. A single concurrency mechanism cannot distinguish all relevant
conflicts: a stale editor form, an Item deletion racing an upload, a retried create request and an
out-of-order Library Search projection have different identities and validity rules. Process locks
or globally serialized queues would also fail to coordinate multiple application and worker
processes.

ADR 0006 already requires short database transactions and final revalidation after external I/O.
ADR 0008 and ADR 0009 establish durable workflows and stable UUID object ownership. This decision
defines the database-visible concurrency protocol used by those operations.

## Decision

### Match the token to the conflict

Quirebase uses separate monotonic tokens rather than overloading `Item.version`:

| Mechanism | Owner and purpose | Advances when |
| --- | --- | --- |
| `Item.version` | Library optimistic concurrency for a User's stale bibliographic metadata snapshot | Bibliographic metadata changes |
| `Item.tag_collection_version` | Library optimistic concurrency for a whole-Tag-collection snapshot | Any Item Tag assignment changes |
| `Item.lifecycle_state` and `Item.lifecycle_fence` | Library lifecycle boundary preventing durable work from committing children to a deleting Item | Item deletion begins; the state changes from `active` to `deleting` and the fence advances |
| `Item.aggregate_sequence` | Source sequence for Library Search | Any indexed Item aggregate input changes, including metadata, Tags, Projects and ready File Revision text |
| `Item.recommendation_sequence` | Source sequence for Item Tag Recommendation input | Title, abstract or ready File Revision text changes |
| Recommendation generation token | Identity of one requested recommendation generation | A generation is explicitly requested or superseded |

Every Item Tag mutation advances `Item.tag_collection_version`, including incremental, bulk,
delete and merge paths. Therefore a stale whole-collection replacement cannot erase a concurrent
assignment, while a Tag edit cannot create a false conflict for an independent metadata form. Tag
and Project changes do not advance `recommendation_sequence`, because they are not recommendation
inputs. Replayed incremental add/remove commands that find the requested assignment state already
present do not advance either the collection token or projection sequence and do not emit a second
Audit Event.

Library Search projections persist `source_sequence` and accept an update only when its sequence is
at least as new as the stored projection. PostgreSQL enforces this in one conditional upsert;
SQLite acquires its writer lock before reading canonical Item state or the stored sequence, then
performs the guarded FTS replacement. The dialect-native Search schema belongs exclusively to
Alembic migrations; request and workflow transactions never probe or mutate schema. Library Search
remains derived state: it does not define whether the business write itself is valid.

### Serialize aggregate transitions in canonical order

Cross-row invariants use database-backed aggregate gates. Projects owns the Project write gate;
Library owns the Item lifecycle gate. Access may coordinate the locks required to make a final
authorization decision, but it does not own Project or Item business transitions.

Transactions that touch more than one aggregate acquire gates in this order:

```text
Project -> Item -> File Revision / Annotation -> association rows
```

Multiple objects at one level are locked by stable ID order. PostgreSQL uses row locks. SQLite uses
a conditional no-op update where a write gate is required, acquiring its database writer lock while
preserving the same business outcome. The implementation does not use process locks or queue-wide
serialization as a substitute for these invariants.

### Give retried creates a stable operation identity

Caller-retried creation operations carry an operation ID that is normalized and bounded before
persistence. Item creation stores the ID under an Item Owner-scoped unique constraint and returns
the original result on replay. File Revision and Attachment workflows use preallocated UUIDs and
derive their operation identity from those UUIDs.

Import Batch confirmation stores its commit operation ID and final Item IDs. Per-Item keys are a
fixed-length SHA-256 derivation of the commit operation ID and record index, so every valid
255-character parent ID produces storage-safe deterministic child IDs. There is one current key
format; no legacy derivation branch is retained.

Import Batch confirmation follows this state machine:

```text
pending -> ready -> committing -> committed
pending -> failed -> pending
ready -> discarded
```

The `ready -> committing` transition, Item and File Revision creation, Audit Events, recorded result
and `committed` transition occur in one transaction. The Import Batch database gate is acquired
before its state is read, including through a no-op write on SQLite where row-level `FOR UPDATE` is
unavailable. A retry with the same operation ID returns the recorded Item IDs. A different operation
ID conflicts, and a committed batch remains as the idempotency record while relinquishing staged-object
reservations.

### Fence durable workflow commits and re-authorize them

Uploads, imported File Revision inspection and Import Batch preparation perform Object Store, PDF
or Provider work outside business transactions. Upload and imported File Revision finalization
validate the Item identity and captured lifecycle fence before writing. Upload commits also lock
and re-read the captured User and relevant Project membership, then re-evaluate Item edit authority.
Permission revocation and Item deletion therefore serialize with the final write rather than racing
a stale request-time decision. Import Batch preparation instead publishes only to the still-pending
batch whose workflow identity it carries.

Recommendation results carry their workflow ID, generation token and recommendation source
sequence. A result is published only if all still match under the Item gate. File Revision changes
advance the source sequence before enqueueing replacement work, so stale output is discarded and a
new generation can converge. Durable function parameters required by this protocol are mandatory;
the alpha cutover provides no replay shim for checkpoints created against the earlier signature.

### Keep one command in one short transaction

A business command owns its permission revalidation, state transition, associated row changes,
projection registration/update and Audit Event. External calls and expensive computation stay
outside that transaction; workflow finalization uses a new short transaction. Helpers do not commit
unless committing is their declared operation boundary.

Independent uniqueness and counter operations use database atomicity: dialect-appropriate upserts
record Login Throttle failures and monotonic Item read timestamps. Contributor identity uses one
case-insensitive, null-safe database uniqueness rule, while Tag and Contributor get-or-create paths
recover from uniqueness races inside savepoints. SQLite and PostgreSQL may use different locking
syntax but must expose the same business result.

## Consequences

- Stale editor and Tag matrix submissions fail explicitly instead of silently replacing newer
  state.
- Deletion has a deterministic winner against in-flight uploads and imported File Revision
  inspection.
- Repeated Item creation and Import Batch confirmation return stable results without duplicate
  business objects.
- Out-of-order Library Search and Item Tag Recommendation work cannot overwrite newer derived
  state.
- Permission changes are effective at durable workflow commit time.
- Multi-aggregate operations must document and test their position in the canonical lock order.
- Schema migrations preserve database integrity during the cutover, but no dual API, stored-data or
  persisted-workflow compatibility layer is part of this decision.

## Scope and follow-up

This decision establishes the core concurrency foundation; it does not claim that every write path
has completed the final architecture. Follow-up work will move Library Search writes behind durable
projection intents, consolidate lifecycle locking under the Library-owned seam, extend commit-time
authorization to synchronous mutations with minimal grant-path locks, and route Library bulk
Project assignment through a Projects-owned typed command. Caller retry identities for HTTP/MCP
uploads and the final Batch-scoping/discard representation for Import commit identities also remain
explicit follow-up decisions.

## Rejected alternatives

- One universal Item version was rejected because Tag and Project changes would unnecessarily
  invalidate recommendations, while lifecycle changes require a stronger fence than an editor CAS.
- Process-local locks were rejected because they do not coordinate Web and worker processes.
- Global queue concurrency of one was rejected because it hides missing aggregate rules and
  serializes unrelated work.
- Last-write-wins collection replacement and projection writes were rejected because they can lose
  accepted concurrent changes or regress derived state.
