# Business concurrency testing

The contracts come from [ADR 0011](../adr/0011-unified-business-concurrency.md) and the
current Workspace model in [ADR 0013](../adr/0013-workspaces-as-data-governance-and-acl-boundaries.md).
Workspace membership owns authority; Projects have no owner. Short synchronous commands use
their admission boundary; durable finalizers reauthorize before publishing canonical state.
An explicit conflict is an allowed result. Tests must not assume that every competing request succeeds.

## Conflict matrix

The machine-readable invariant registry is [concurrency_cases.json](../../tests/concurrency_cases.json).
Tests identify their contract with `@pytest.mark.concurrency_case("id")`. The report lists actual
parameterized node IDs, so a passed selected schedule does not imply all possible orders are covered.

| Invariant IDs | Competing operations | Current schedules and observations |
| --- | --- | --- |
| `discussion-root-delete`, `reply-root-delete` | Root deletion / discussion moderation or annotation reply | Workspace or Project root held first; public mutation waits; full cascade finishes; mutation rejects the vanished root |
| `workspace-read-delete`, `foreign-lock-isolation` | Workspace read or foreign discussion ID / deletion or row lock | List, detail and governance read before deletion commits, then owner lookup; foreign IDs do not lock another Workspace's rows; admin response handling also has a regression in `test_http.py` |
| `item-reading` | Item Overview / Metadata reads | Both commit orders with independent sessions and an uncommitted reading insert on SQLite and PostgreSQL; PostgreSQL also commits a newer read before an older request's native upsert; one reading record retains the latest timestamp |
| `login-throttle` | Concurrent failures, successful-login clear / failure upsert, expiry cleanup / window reset | A competing first insertion increments without losing a failure; a clear committed before the upsert lets the failure start a new window; conditional expiry deletion preserves a newly reset window |
| `workspace-archive-write`, `project-archive-write` | Archive / discussion write | Admitted Workspace write finishes before archive; Workspace or Project archive commits before a waiting writer rechecks lifecycle |
| `actor-revocation`, `governance-demotion` | User deactivation or admin demotion / authorized mutations | Invitation, import confirmation, ownership transfer, governance and password boundaries; import explicitly observes the User → Workspace wait chain |
| `ownership-transfer`, `membership-identity` | Two ownership transfers or rejoins | One authoritative Workspace owner; one current membership; losing authority is rechecked |
| `participation-recheck`, `relation-idempotency` | Project join/leave, mode switch, member suspension or duplicate association additions/removal | Participation follows current mode/membership; independent guards remain shared; duplicate additions create one relation. Leave committed before a duplicate Join's reread causes a conflict, leaves no selection and adds no Join Audit Event; an explicit fresh Join succeeds. A competing single insert before the batch's native insertion preserves other links and counts only newly added links. Removal after a bulk Tag insert skips a duplicate leaves that link removed, preserves other new links and commits one bulk Audit Event |
| `upload-finalization` | Upload finalizers for different Items / Workspace archive | Ordinary and Graphical Abstract finalizer guards share the Workspace root; a second Item proceeds while the first transaction remains open. Archive waits for that guard, and finalization rechecks authority after archive commits |
| `annotation-recheck`, `assignment-item-delete` | Reply/scope change or assignment / moderation, detachment or Item deletion | Waiting mutation rechecks lineage and authority; integrity failures become domain errors |
| `annotation-version` | Two Annotation or Reply edits with version 1 | First edit held before commit; second edit waits, then receives version 2 conflict; one successful edit and one audit event |
| `metadata-version` | Two metadata replacements with version 1 | Both winner orders; exactly one version 2 result; loser receives `VersionConflict`; public Item view, full-text search and audit agree |
| `import-replay` | Two confirmations / retry after losing a committed response | Both caller startup orders queued at one Batch; same Item IDs on confirmation and fresh-Session replay; one import audit per Item; real full-text search |
| `settings-install`, `author-install`, `citation-style-install` | Overlapping first-setting or Author batches / duplicate Citation Style installation | Native setting upserts retain the complete validated batch; Author savepoint recovery preserves missing identities and the caller transaction; Citation Style duplicates produce a domain conflict and permit a distinct installation in the same Session |

The root-deletion tests directly hold/delete parent rows to control the database cascade, then invoke
public business mutations. The metadata and import tests inspect final state through public Library,
Search and Audit interfaces. They use native PostgreSQL search tables rather than mocking Search.

The report's `evidence_enabled` flag distinguishes scenarios using the shared harness from legacy
tests with local synchronization. Legacy results are included in the matrix but do not gain SQL/lock
evidence automatically. The upload-finalizer guard tests exercise a private authorization helper;
neither those tests nor the in-memory durable client prove crash recovery through a real DBOS restart.

`test_durable_recovery.py` separately exercises real process death with DBOS. It stops the PDF
Import executor after completed extraction/database checkpoints, changes live descriptor metadata
and runs production recovery in a fresh process. It then stops a confirmation process after its
canonical commit, before returning a response, and retries confirmation from another process.
The test checks original durable input semantics, checkpoint reuse, stable Item identity, one
successful Audit/side-effect set, file ownership transfer and rejected-object cleanup. Both database
variants use fresh migrations and isolated databases; PostgreSQL requires database-creation rights.
This covers these selected boundaries, rather than every finalizer or cleanup crash schedule.

## Run and reproduce

Use a **dedicated disposable PostgreSQL database**. These fixtures create and drop application tables.
Do not point them at an application database. PostgreSQL is the supported multi-worker database;
SQLite tests cannot establish row-lock correctness.

```sh
export QUIREBASE_TEST_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/quirebase_test
uv sync --extra postgres --frozen
uv run pytest -q tests/test_postgres_concurrency.py tests/test_concurrency_harness.py \
  tests/test_concurrency_reporting.py \
  --concurrency-report-dir=concurrency-results --junitxml=concurrency-results/junit.xml

# Replay the exact parameterized schedule from coverage.json or a failure artifact.
uv run pytest -q \
  'tests/test_postgres_concurrency.py::test_concurrent_metadata_replacements_reject_stale_version[alpha-first]' \
  --concurrency-report-dir=concurrency-results

# Real process death, checkpoint recovery and lost confirmation responses.
uv run pytest -q tests/test_durable_recovery.py
```

Without the PostgreSQL URL, database cases skip. A skipped case is never counted as passing coverage.
`shared_postgres` serializes destructive schema fixtures across pytest workers with an advisory lock;
the competing transactions inside a test remain independent and concurrent.

## Shared interleaving harness

`postgres_race.session("actor")` owns a separate Session and pins its connection across commits.
`start()` owns the competing task; `join()` observes its outcome with a bounded wait.
`wait_blocked("waiter", "holder")` waits for that **direct** edge in `pg_blocking_pids`, rather than
assuming SQL has started after a fixed sleep. PostgreSQL can queue a second contender behind the first
contender's tuple lock, giving `second → first → holder`; assert the actual edges explicitly.
Use bounded Events for an application-level checkpoint, and `note()` to label its release.

Place business assertions inside a named verification Session when a live failure snapshot matters.
Unexpected Session errors, pytest failures and harness timeouts capture evidence before Session
cleanup or task cancellation. A failure detected only after all actors have closed still retains
their SQL/wait trace, but its activity snapshot may contain no live actors.

On failure the harness writes `failures/<node-hash>-<worker>.json` containing the node ID, named
backend PIDs, elapsed SQL/transaction/wait trace, original exception type and SQLSTATE, server version/isolation,
`pg_stat_activity` and `pg_locks`. The first failure and first snapshot survive subsequent cleanup
errors. Collection is bounded and diagnostic errors do not replace the business failure. The trace
omits bound parameters, connection URLs and exception-message parameter dumps; PostgreSQL's current
query text can still contain SQL literals. Use synthetic inputs for these artifacts.

Every owned task is cancelled and awaited before schema teardown. Forgetting to join an operation
fails the test. Actor connections also have lock/statement/idle-transaction limits. Harness tests
verify actual blocking, PID stability after commit, timeout cleanup, pytest failure capture,
parameter omission and a real deadlock's SQLSTATE `40P01`.

## CI and follow-up coverage

The mandatory PostgreSQL CI job runs the contracts, invariant scenarios and harness/report tests on
PostgreSQL 18, alongside fresh migrations and doctor checks. It uploads coverage JSON/Markdown,
JUnit and any failure snapshots, including when tests fail. The separate nightly/manual replay
workflow runs five rounds on five isolated databases and retains each round's artifacts for 14 days.
The nightly schedule becomes active when that workflow reaches the default branch. These are repeat
runs of controlled schedules, not generated random interleavings.

Browser E2E also covers a PDF source refresh completing during a private draft's Save click.
The ordinary post-switch edit scenario waits for the selected source response and verifies the
actual PATCH body. CI retains failed browser traces/screenshots and repeats these two PDF scenarios
five times (30 on manual runs). Inspect the trace's DOM, input events and request body before attributing
an intermittent missing-text failure to a persistence race.

Expand coverage in this order:

1. Move remaining legacy synchronization to the harness and add inverse commit orders where the
   invariant differs. Keep the operation pair, order and expected outcome visible in each node ID.
2. Extend real DBOS process-death coverage beyond PDF preparation checkpoints and post-confirmation
   response loss to upload finalizers and failures during outbox delivery/object cleanup. Observe
   through business interfaces and storage.
3. Add Hypothesis state machines for generated lifecycle/role/version histories, retaining a seed
   and minimized sequence. Sequential state machines need an explicit scheduler to explore races.
4. Model a narrowly scoped difficult protocol in TLA+/TLC when its possible states outgrow executable
   scenarios. Keep its invariants aligned with this registry and the ADRs.

For a new failure, first identify the violated contract, operation pair and observed wait/commit
order. Minimize it into a deterministic regression. Repair the owning aggregate's lock order, CAS
predicate or database constraint; do not add blanket retries or a universal lock graph.
